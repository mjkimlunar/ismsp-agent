# -*- coding: utf-8 -*-
"""두 지표를 잰다.  `python evaluate.py [-n 3] [--split eval]`

  ① 도구 호출 적절성 — 실제로 부른 도구 집합이 기대 도구 집합과 **정확히** 일치하면 1점.
     하나라도 더 부르거나 덜 부르면 0점이다. 엄격하지만, 근거를 어느 문서에서
     가져왔는지가 답변 품질을 좌우하므로 여기를 느슨하게 재면 지표가 의미를 잃는다.

  ② 답변 적절성 — 필수 사실이 전부 있고 금지 표현이 하나도 없으면 1점.
     필수 사실은 표현 묶음으로 적혀 있어서 말이 달라도 사실이 맞으면 통과한다.

같은 입력을 여러 번 돌리면 결과가 흔들린다. -n 으로 반복 횟수를 정하고 평균을 본다.
한 번만 재고 좋아졌다고 말하면 안 된다.
"""
import argparse
import json
import re
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

from config import DATA

# 문서마다 가운뎃점 문자가 다르고(ㆍ · ∙) 띄어쓰기도 제각각이라 맞춰 놓고 비교한다.
_MIDDOT = re.compile(r"[ㆍ·∙•]")


def norm(s):
    return _MIDDOT.sub("", re.sub(r"\s+", "", (s or ""))).lower()


def load_cases(split=None):
    raw = json.loads((DATA / "goldenset.json").read_text(encoding="utf-8"))["cases"]
    return [c for c in raw if split is None or c["split"] == split]


# ── 지표 ① ────────────────────────────────────────────────────────
def score_tools(case, called):
    """기대 도구 집합과 정확히 일치하는지."""
    expect, got = set(case["expect_tools"]), set(called)
    if expect == got:
        return 1, ""
    missing = sorted(expect - got)
    extra = sorted(got - expect)
    parts = []
    if missing:
        parts.append(f"안 부름 {missing}")
    if extra:
        parts.append(f"더 부름 {extra}")
    return 0, " / ".join(parts)


# ── 지표 ② ────────────────────────────────────────────────────────
def score_answer(case, answer, escalated):
    """필수 사실이 다 있고 금지 표현이 없으면 통과. 넘기기 문항은 넘겼는지도 본다."""
    fails = []
    a = norm(answer)

    if case["escalate"] and not escalated:
        fails.append("넘겨야 하는 문의인데 직접 답함")

    for group in case["must"]:
        if not any(norm(alt) in a for alt in group):
            fails.append(f"필수 사실 빠짐: {group[0]}")

    for bad in case["forbid"]:
        if norm(bad) in a:
            fails.append(f"금지 표현: {bad}")

    return (0 if fails else 1), " · ".join(fails)


def score(case, result):
    """한 건을 두 지표로 채점한다. 파이프라인을 돌리지 않고 결과만 받는다."""
    t, t_why = score_tools(case, result.get("tools", []))
    a, a_why = score_answer(case, result.get("answer", ""),
                            result.get("escalated", False))
    return {"id": case["id"], "tool_ok": t, "answer_ok": a,
            "tool_why": t_why, "answer_why": a_why,
            "route": result.get("route", "?"), "expect_route": case["route"],
            "route_ok": int(result.get("route") == case["route"])}


# ── 실행 ──────────────────────────────────────────────────────────
def one_round(cases):
    from agent import run

    def go(c):
        try:
            return c, run(c["question"])
        except Exception as e:
            return c, {"answer": f"[실행 실패] {e}", "tools": [], "route": "?",
                       "escalated": False}

    with ThreadPoolExecutor(max_workers=4) as ex:
        return [score(c, r) for c, r in ex.map(go, cases)]


def summarize(rows):
    n = len(rows)
    return {
        "n": n,
        "tool": sum(r["tool_ok"] for r in rows) / n,
        "answer": sum(r["answer_ok"] for r in rows) / n,
        "route": sum(r["route_ok"] for r in rows) / n,
    }


def main(n, split, show_fail):
    from router import warmup
    warmup()

    cases = load_cases(split)
    print(f"평가셋 {len(cases)}건 · {n}회 반복\n")

    runs, all_rows = [], []
    for i in range(n):
        rows = one_round(cases)
        s = summarize(rows)
        runs.append(s)
        all_rows.extend(rows)
        print(f"  {i + 1}회차  도구 {100 * s['tool']:5.1f}%  "
              f"답변 {100 * s['answer']:5.1f}%  (분류 {100 * s['route']:5.1f}%)")

    def avg(k):
        return sum(r[k] for r in runs) / n

    print(f"\n{'─' * 58}")
    print(f"  ① 도구 호출 적절성   {100 * avg('tool'):5.1f}%   "
          f"(최저 {100 * min(r['tool'] for r in runs):.1f} · "
          f"최고 {100 * max(r['tool'] for r in runs):.1f})")
    print(f"  ② 답변 적절성        {100 * avg('answer'):5.1f}%   "
          f"(최저 {100 * min(r['answer'] for r in runs):.1f} · "
          f"최고 {100 * max(r['answer'] for r in runs):.1f})")
    print(f"     참고: 카테고리 분류 {100 * avg('route'):5.1f}%")
    print(f"{'─' * 58}")

    # 케이스별 통과 횟수 — 어디가 흔들리는지 본다
    by = {}
    for r in all_rows:
        d = by.setdefault(r["id"], {"tool": 0, "answer": 0, "why": []})
        d["tool"] += r["tool_ok"]
        d["answer"] += r["answer_ok"]
        for w in (r["tool_why"], r["answer_why"]):
            if w and w not in d["why"]:
                d["why"].append(w)

    print("\n케이스별 (도구/답변, n회 중 통과 횟수)")
    for cid in sorted(by):
        d = by[cid]
        mark = "  " if d["tool"] == n and d["answer"] == n else "▶ "
        print(f"  {mark}{cid}  도구 {d['tool']}/{n}  답변 {d['answer']}/{n}")
        if show_fail and d["why"]:
            for w in d["why"]:
                print(f"        {w[:110]}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", type=int, default=3, help="반복 횟수 (기본 3)")
    ap.add_argument("--split", default="eval", help="eval / fewshot / all")
    ap.add_argument("-v", action="store_true", help="실패 사유까지 보기")
    args = ap.parse_args()
    main(args.n, None if args.split == "all" else args.split, args.v)
