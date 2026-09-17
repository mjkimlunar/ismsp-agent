# -*- coding: utf-8 -*-
"""멀티턴을 잰다.  `python evaluate_multiturn.py [-n 3] [-v]`

단일턴 지표(evaluate.py)와 같은 두 가지를 재되, 턴 위치별로 나눠 본다.
**1턴은 잘하고 2턴부터 무너지는지**가 이 지표의 요점이다.
앞선 프로젝트에서 2차 턴이 1차 대비 30%p 낮았는데, 그 구간을 한 번도 재지 않아
모르고 지나갔다. 같은 일을 반복하지 않으려고 만들었다.

대화는 순서대로 돌려야 하므로 턴끼리는 병렬로 못 돌린다. 대화 단위로만 나눈다.
"""
import argparse
import json
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

from config import DATA, WORKERS
from evaluate import score_answer, score_tools


def load_conversations():
    return json.loads(
        (DATA / "multiturn_set.json").read_text(encoding="utf-8"))["conversations"]


def run_conversation(conv):
    """대화 하나를 순서대로 돌리고 턴마다 채점한다."""
    from agent import run

    history, rows = [], []
    for i, t in enumerate(conv["turns"], 1):
        try:
            r = run(t["question"], history)
        except Exception as e:
            r = {"answer": f"[실행 실패] {e}", "tools": [], "route": "?",
                 "escalated": False}
        tool_ok, tool_why = score_tools(t, r.get("tools", []))
        ans_ok, ans_why = score_answer(t, r.get("answer", ""),
                                       r.get("escalated", False))
        rows.append({
            "conv": conv["id"], "turn": i, "carry": t.get("carry", False),
            "question": t["question"],
            "tool_ok": tool_ok, "answer_ok": ans_ok,
            "tool_why": tool_why, "answer_why": ans_why,
            "route_ok": int(r.get("route") == t["route"]),
            "route": r.get("route", "?"), "expect_route": t["route"],
        })
        history.append({"question": t["question"], "answer": r.get("answer", "")})
    return rows


def one_round(convs):
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        return [row for rows in ex.map(run_conversation, convs) for row in rows]


def rate(rows, key):
    return sum(r[key] for r in rows) / len(rows) if rows else 0.0


def main(n, verbose):
    from router import warmup
    warmup()

    convs = load_conversations()
    turns = sum(len(c["turns"]) for c in convs)
    carry = sum(1 for c in convs for t in c["turns"] if t.get("carry"))
    print(f"대화 {len(convs)}건 · 턴 {turns}개 (앞 주제를 이어받아야 하는 턴 {carry}개) · {n}회 반복\n")

    allr = []
    for i in range(n):
        rows = one_round(convs)
        allr += rows
        print(f"  {i + 1}회차  도구 {100 * rate(rows, 'tool_ok'):5.1f}%  "
              f"답변 {100 * rate(rows, 'answer_ok'):5.1f}%  "
              f"(분류 {100 * rate(rows, 'route_ok'):5.1f}%)")

    print(f"\n{'─' * 62}")
    print(f"  ① 도구 호출 적절성   {100 * rate(allr, 'tool_ok'):5.1f}%")
    print(f"  ② 답변 적절성        {100 * rate(allr, 'answer_ok'):5.1f}%")
    print(f"     참고: 카테고리 분류 {100 * rate(allr, 'route_ok'):5.1f}%")
    print(f"{'─' * 62}")

    # ── 턴 위치별 ─────────────────────────────────────────────
    by_turn = defaultdict(list)
    for r in allr:
        by_turn[r["turn"]].append(r)
    print("\n  턴 위치별 — 뒤로 갈수록 떨어지는지 본다")
    print(f"    {'턴':>3s}  {'건수':>4s}  {'도구':>7s}  {'답변':>7s}  {'분류':>7s}")
    for t in sorted(by_turn):
        rows = by_turn[t]
        print(f"    {t:>3d}  {len(rows):>4d}  {100 * rate(rows, 'tool_ok'):6.1f}%  "
              f"{100 * rate(rows, 'answer_ok'):6.1f}%  {100 * rate(rows, 'route_ok'):6.1f}%")

    # ── 이어받는 턴 vs 아닌 턴 ────────────────────────────────
    carried = [r for r in allr if r["carry"]]
    fresh = [r for r in allr if not r["carry"]]
    print("\n  앞 주제를 이어받아야 하는 턴인가")
    print(f"    이어받음  {len(carried):>3d}건  도구 {100 * rate(carried, 'tool_ok'):5.1f}%  "
          f"답변 {100 * rate(carried, 'answer_ok'):5.1f}%")
    print(f"    새 주제    {len(fresh):>3d}건  도구 {100 * rate(fresh, 'tool_ok'):5.1f}%  "
          f"답변 {100 * rate(fresh, 'answer_ok'):5.1f}%")

    # ── 턴별 통과 횟수 ────────────────────────────────────────
    key = defaultdict(lambda: {"tool": 0, "answer": 0, "route": 0, "why": []})
    for r in allr:
        d = key[(r["conv"], r["turn"])]
        d["tool"] += r["tool_ok"]
        d["answer"] += r["answer_ok"]
        d["route"] += r["route_ok"]
        d["q"] = r["question"]
        d["carry"] = r["carry"]
        if not r["route_ok"]:
            w = f"분류 {r['expect_route']} → {r['route']}"
            if w not in d["why"]:
                d["why"].append(w)
        for w in (r["tool_why"], r["answer_why"]):
            if w and w not in d["why"]:
                d["why"].append(w)

    print(f"\n  턴별 (n={n}회 중 통과 횟수)")
    for (conv, turn) in sorted(key):
        d = key[(conv, turn)]
        ok = d["tool"] == n and d["answer"] == n and d["route"] == n
        mark = "  " if ok else "▶ "
        tag = "↩" if d["carry"] else " "
        print(f"  {mark}{conv}-{turn}{tag} 도구 {d['tool']}/{n} 답변 {d['answer']}/{n} "
              f"분류 {d['route']}/{n}  {d['q'][:34]}")
        if verbose and d["why"]:
            for w in d["why"]:
                print(f"          {w[:100]}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", type=int, default=3, help="반복 횟수 (기본 3)")
    ap.add_argument("-v", action="store_true", help="실패 사유까지 보기")
    a = ap.parse_args()
    main(a.n, a.v)
