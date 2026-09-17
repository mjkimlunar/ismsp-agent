# -*- coding: utf-8 -*-
"""이관을 얼마나 하고, 그중 얼마가 부당한지 잰다.  `python report_escalation.py [-n 3]`

"이관이 많다" 는 느낌만으로는 고칠 수 없다. 이관에는 두 종류가 있고 값이 정반대다.

  타당한 이관 — 문서에 근거가 없거나, 개별 조직의 심사 결과를 확답해 달라는 요구.
                이건 넘기는 것이 맞고, 억지로 답하면 틀린 안내가 된다.
  부당한 이관 — 문서에 답이 분명히 있는데 못 찾아서 넘긴 것.
                답할 수 있는 것을 사람에게 떠넘기는 셈이라 실패다.

평가셋에 `escalate` 라벨이 있으므로 둘을 갈라 셀 수 있다.
또 이관이 **어느 단계에서** 났는지도 나눈다. 판정 단계와 답변 단계는 고칠 곳이 다르다.
"""
import argparse
from collections import Counter

from evaluate import load_cases
from evaluate_multiturn import load_conversations


def probe_single(cases):
    from agent import run

    out = []
    for c in cases:
        try:
            r = run(c["question"])
        except Exception as e:
            out.append({"id": c["id"], "q": c["question"], "want": c["escalate"],
                        "got": True, "stage": "실행 실패", "why": str(e)[:60]})
            continue
        out.append({
            "id": c["id"], "q": c["question"], "want": c["escalate"],
            "got": r["escalated"],
            # 도구를 하나도 안 불렀으면 판정 단계에서 끊긴 것이다.
            "stage": ("판정" if r["escalated"] and not r["tools"]
                      else "답변" if r["escalated"] else "—"),
            "why": r.get("answer", "")[:0],
            "route": r["route"],
        })
    return out


def probe_multi(convs):
    from agent import run

    out = []
    for conv in convs:
        history = []
        for i, t in enumerate(conv["turns"], 1):
            try:
                r = run(t["question"], history)
            except Exception as e:
                r = {"escalated": True, "tools": [], "answer": "", "route": "?"}
            out.append({
                "id": f"{conv['id']}-{i}", "q": t["question"],
                "want": t["escalate"], "got": r["escalated"],
                "stage": ("판정" if r["escalated"] and not r["tools"]
                          else "답변" if r["escalated"] else "—"),
                "route": r.get("route", "?"),
            })
            history.append({"question": t["question"],
                            "answer": r.get("answer", "")})
    return out


def show(title, rows):
    n = len(rows)
    esc = [r for r in rows if r["got"]]
    wrong = [r for r in esc if not r["want"]]          # 답할 수 있었는데 넘김
    missed = [r for r in rows if r["want"] and not r["got"]]  # 넘겨야 하는데 답함
    right = [r for r in esc if r["want"]]

    print(f"\n{'─' * 66}\n  {title} — {n}건\n{'─' * 66}")
    print(f"    이관율          {100 * len(esc) / n:5.1f}%  ({len(esc)}/{n})")
    print(f"      타당한 이관   {len(right):3d}건  (평가셋이 넘기라고 표시한 문항)")
    print(f"      부당한 이관   {len(wrong):3d}건  ← 답할 수 있었는데 넘겼다")
    print(f"    반대 방향 실패  {len(missed):3d}건  (넘겨야 하는데 직접 답함)")

    stages = Counter(r["stage"] for r in esc)
    if stages:
        print(f"    이관이 난 단계  " + " · ".join(f"{k} {v}건" for k, v in stages.items()))

    for label, items in (("부당한 이관", wrong), ("반대 방향 실패", missed)):
        if not items:
            continue
        print(f"\n    [{label}]")
        for r in items:
            print(f"      {r['id']:<8s} {r['route']:<8s} {r['q'][:50]}"
                  + (f"  ({r['stage']} 단계)" if r["got"] else ""))
    return len(wrong), n


def main(n):
    from router import warmup
    warmup()

    single = load_cases(None)
    multi = load_conversations()

    tot_wrong = tot = 0
    for i in range(n):
        print(f"\n{'═' * 66}\n  {i + 1}회차\n{'═' * 66}")
        w, c = show("단일턴 평가셋", probe_single(single))
        tot_wrong += w
        tot += c
        w, c = show("멀티턴 평가셋", probe_multi(multi))
        tot_wrong += w
        tot += c

    print(f"\n{'═' * 66}")
    print(f"  {n}회 누적 — 부당한 이관 {tot_wrong}건 / 전체 {tot}건 "
          f"({100 * tot_wrong / tot:.1f}%)")
    print(f"{'═' * 66}")
    print("\n부당한 이관이 답변 단계에서 많이 나면, '근거를 못 찾았다' 와")
    print("'근거로 답할 수 없는 문의다' 를 한 규칙으로 처리하는 것이 원인이다.")
    print("앞쪽은 검색을 다시 해야 하고 뒤쪽만 넘겨야 한다.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", type=int, default=1, help="반복 횟수 (기본 1)")
    main(ap.parse_args().n)
