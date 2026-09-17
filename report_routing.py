# -*- coding: utf-8 -*-
"""분류 성능을 정확도·클래스별 F1·macro F1·혼동 행렬로 잰다.
`python report_routing.py [-n 3]`

정확도 하나만 보면 안 된다. 카테고리마다 문항 수가 다르면 큰 카테고리를 잘 맞히는 것만으로
정확도가 올라가고, 작은 카테고리를 통째로 틀려도 표에 잘 안 드러난다.
macro F1 은 카테고리마다 F1 을 따로 내고 그냥 평균해서, 문항이 적은 카테고리도 같은 무게로 센다.

혼동 행렬은 **행이 정답, 열이 예측**이다. (3,4) 칸의 3 은
"정답이 3행 카테고리인데 4열 카테고리로 잘못 본 문의가 3건" 이라는 뜻이다.
대각선이 맞힌 것이고, 대각선을 벗어난 칸이 전부 오분류다. 어느 칸에 몰리는지가 곧 고칠 자리다.
"""
import argparse
import json
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor

from config import DATA, WORKERS

ROUTES = ["MGMT", "PROTECT", "PRIVACY", "CERT", "OTHER"]


def load_cases():
    return json.loads((DATA / "routing_set.json").read_text(encoding="utf-8"))["cases"]


def one_round(cases):
    from router import classify

    def go(c):
        try:
            return c, classify(c["question"])
        except Exception as e:
            return c, {"route": "OTHER", "confidence": 0.0, "reason": f"실패: {e}"}

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        return list(ex.map(go, cases))


def metrics(pairs):
    """pairs = [(정답, 예측), …] → 정확도, 클래스별 지표, macro F1, 혼동 행렬"""
    hit = sum(1 for t, p in pairs if t == p)
    mat = {t: Counter() for t in ROUTES}
    for t, p in pairs:
        mat[t][p] += 1

    per = {}
    for r in ROUTES:
        tp = mat[r][r]
        fn = sum(v for k, v in mat[r].items() if k != r)
        fp = sum(mat[t][r] for t in ROUTES if t != r)
        prec = tp / (tp + fp) if tp + fp else 0.0
        rec = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
        per[r] = {"P": prec, "R": rec, "F1": f1, "support": tp + fn}

    macro = sum(v["F1"] for v in per.values()) / len(ROUTES)
    return hit / len(pairs), per, macro, mat


def show_matrix(mat):
    w = max(len(r) for r in ROUTES) + 1
    print(f"\n  혼동 행렬 (행=정답, 열=예측)\n")
    print("  " + " " * w + "│" + "".join(f"{r[:7]:>9s}" for r in ROUTES) + "   합계")
    print("  " + "─" * w + "┼" + "─" * (9 * len(ROUTES) + 7))
    for t in ROUTES:
        row = mat[t]
        cells = ""
        for p in ROUTES:
            v = row[p]
            if v == 0:
                cells += f"{'·':>9s}"
            elif t == p:
                cells += f"{v:>9d}"                 # 맞힌 칸
            else:
                cells += f"{('*' + str(v)):>9s}"    # 오분류 칸에 표시
        print(f"  {t:<{w}s}│{cells}   {sum(row.values()):>4d}")
    print(f"\n  대각선이 맞힌 것 · *표시가 오분류")


def main(n):
    from router import warmup
    warmup()

    cases = load_cases()
    by_route = Counter(c["route"] for c in cases)
    print(f"분류 평가셋 {len(cases)}건 · {n}회 반복")
    print("  구성 " + " · ".join(f"{r} {by_route[r]}" for r in ROUTES))

    all_pairs, wrong = [], defaultdict(list)
    accs = []
    for i in range(n):
        rows = one_round(cases)
        pairs = [(c["route"], d["route"]) for c, d in rows]
        all_pairs += pairs
        acc, _, macro, _ = metrics(pairs)
        accs.append((acc, macro))
        print(f"  {i + 1}회차  정확도 {acc:.3f}  macro F1 {macro:.3f}")
        for c, d in rows:
            if c["route"] != d["route"]:
                wrong[c["id"]].append((d["route"], d["confidence"], d["reason"]))

    acc, per, macro, mat = metrics(all_pairs)
    print(f"\n{'─' * 62}")
    print(f"  전체 {len(all_pairs)}개 판정 누적")
    print(f"  정확도    {acc:.3f}")
    print(f"  macro F1  {macro:.3f}")
    print(f"{'─' * 62}")

    print(f"\n  {'카테고리':<10s} {'정밀도':>8s} {'재현율':>8s} {'F1':>8s} {'문항':>6s}")
    print("  " + "─" * 46)
    for r in ROUTES:
        v = per[r]
        print(f"  {r:<10s} {v['P']:8.3f} {v['R']:8.3f} {v['F1']:8.3f} {v['support'] // n:6d}")

    show_matrix(mat)

    # ── 실패 분석 ─────────────────────────────────────────────
    if not wrong:
        print("\n  오분류 없음")
        return
    print(f"\n{'─' * 62}\n  오분류 {len(wrong)}개 문항 — 라우터가 스스로 댄 근거를 같이 본다\n")
    idx = {c["id"]: c for c in cases}
    for cid in sorted(wrong):
        c = idx[cid]
        print(f"  [{cid}] {c['question'][:62]}")
        print(f"        정답 {c['route']}")
        for route, conf, reason in wrong[cid]:
            print(f"        → {route} (확신도 {conf:.2f})  {reason[:78]}")
        if c.get("boundary"):
            print(f"        경계: {c['boundary'][:88]}")
        print()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", type=int, default=3, help="반복 횟수 (기본 3)")
    main(ap.parse_args().n)
