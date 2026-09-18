# -*- coding: utf-8 -*-
"""지표를 재서 한 줄로 쌓는다.  `python track.py [-n 1] [--only eval,wild]`

한 번 재고 좋아졌다고 말하면 안 된다는 걸 이 프로젝트에서 세 번 배웠다.
그런데 재측정을 손으로 돌리면 결과가 터미널에 찍히고 사라져서, 지난번보다 나아진 건지
노이즈인지 비교할 수가 없었다. 그래서 **돌릴 때마다 한 줄씩 쌓는다.**

`runs/metrics_history.csv` 의 한 줄이 곧 "그 시점 코드의 성적표" 다.
커밋 해시를 같이 적으므로 나중에 어느 코드였는지 되짚을 수 있다.
(피어리뷰에서 본 khu-academic-agent 의 experiment_log.csv 에서 가져온 방식이다.
 그쪽은 변경 이유를 손으로 적었고, 여기서는 커밋 해시로 대신한다.)

CSV 로 둔 것은 나중에 기계로 다시 읽기 위해서다. 리포트 본문 표로만 갖고 있으면
"지난 다섯 번의 분포" 같은 걸 볼 수 없다.
"""
import argparse
import csv
import io
import subprocess
import time
from datetime import datetime
from pathlib import Path

HIST = Path(__file__).parent / "runs" / "metrics_history.csv"

FIELDS = ["at", "commit", "dirty", "model", "n", "took_s",
          "eval_tool", "eval_answer",
          "wild_tool", "wild_answer",
          "multi_tool", "multi_answer",
          "route_acc", "route_macro_f1", "note"]


def git_state():
    """어느 코드로 잰 값인지 남긴다. 커밋 안 한 변경이 있으면 표시한다."""
    def run(*a):
        try:
            return subprocess.run(a, capture_output=True, text=True,
                                  cwd=Path(__file__).parent, timeout=15).stdout.strip()
        except Exception:
            return ""
    return run("git", "rev-parse", "--short", "HEAD"), bool(run("git", "status", "--porcelain"))


def measure(which, n):
    """골라서 잰다. 앞 단계에서 죽어도 남은 것은 재도록 각각 감싼다."""
    out = {}

    if "eval" in which or "wild" in which:
        from evaluate import load_cases, one_round, summarize
        for split in ("eval", "wild"):
            if split not in which:
                continue
            try:
                runs = [summarize(one_round(load_cases(split))) for _ in range(n)]
                out[f"{split}_tool"] = round(sum(r["tool"] for r in runs) / n, 4)
                out[f"{split}_answer"] = round(sum(r["answer"] for r in runs) / n, 4)
            except Exception as e:
                out[f"{split}_tool"] = out[f"{split}_answer"] = ""
                print(f"  !! {split} 실패: {str(e)[:90]}")

    if "multi" in which:
        try:
            from evaluate_multiturn import load_conversations, one_round as mround, rate
            rows = [r for _ in range(n) for r in mround(load_conversations())]
            out["multi_tool"] = round(rate(rows, "tool_ok"), 4)
            out["multi_answer"] = round(rate(rows, "answer_ok"), 4)
        except Exception as e:
            out["multi_tool"] = out["multi_answer"] = ""
            print(f"  !! multiturn 실패: {str(e)[:90]}")

    if "route" in which:
        try:
            from report_routing import load_cases as rcases, metrics, one_round as rround
            pairs = [(c["route"], d["route"])
                     for _ in range(n) for c, d in rround(rcases())]
            acc, _, macro, _ = metrics(pairs)
            out["route_acc"] = round(acc, 4)
            out["route_macro_f1"] = round(macro, 4)
        except Exception as e:
            out["route_acc"] = out["route_macro_f1"] = ""
            print(f"  !! routing 실패: {str(e)[:90]}")

    return out


def append(row):
    HIST.parent.mkdir(exist_ok=True)
    new = not HIST.exists()
    with io.open(HIST, "a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new:
            w.writeheader()
        w.writerow({k: row.get(k, "") for k in FIELDS})


def show_trend(limit=8):
    if not HIST.exists():
        return
    rows = list(csv.DictReader(io.open(HIST, encoding="utf-8")))[-limit:]
    print(f"\n최근 {len(rows)}회 — {HIST.name}")
    print(f"  {'시각':17s} {'커밋':9s} {'eval도구':>8s} {'eval답변':>8s} "
          f"{'wild답변':>8s} {'멀티답변':>8s} {'분류':>7s}")
    for r in rows:
        def pct(k):
            v = r.get(k)
            return f"{100 * float(v):7.1f}%" if v else "      —"
        mark = "*" if r.get("dirty") == "True" else " "
        print(f"  {r['at'][:16]:17s} {r['commit']:7s}{mark} {pct('eval_tool')} "
              f"{pct('eval_answer')} {pct('wild_answer')} {pct('multi_answer')} "
              f"{(r.get('route_acc') or '—'):>7s}")
    if any(r.get("dirty") == "True" for r in rows):
        print("  * = 커밋하지 않은 변경이 있던 상태에서 잰 값")


def main(n, only, note):
    import os

    from config import MODEL
    from router import warmup

    which = [s.strip() for s in only.split(",")] if only else \
        ["eval", "wild", "multi", "route"]
    commit, dirty = git_state()
    print(f"측정 — {MODEL} · {commit}{' (미커밋 변경 있음)' if dirty else ''} · "
          f"{n}회 반복 · 대상 {', '.join(which)}")

    warmup()
    t0 = time.time()
    row = measure(which, n)
    row.update({
        "at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "commit": commit, "dirty": dirty,
        "model": f"{os.getenv('ISMSP_PROVIDER', 'openai')}/{MODEL}",
        "n": n, "took_s": round(time.time() - t0), "note": note,
    })
    append(row)
    show_trend()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", type=int, default=1, help="각 평가셋 반복 횟수 (기본 1)")
    ap.add_argument("--only", default="", help="eval,wild,multi,route 중 골라서")
    ap.add_argument("--note", default="", help="이 측정에 남길 메모")
    a = ap.parse_args()
    main(a.n, a.only, a.note)
