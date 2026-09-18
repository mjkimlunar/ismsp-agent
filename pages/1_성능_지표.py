# -*- coding: utf-8 -*-
"""성능 지표 화면 — 발표·시연용.

**이 화면은 LLM 을 부르지 않는다.** `track.py` 가 재서 남긴 기록만 읽어 그린다.
볼 때마다 다시 재면 볼 때마다 돈이 들고, 발표 중에 수치가 바뀌어 버린다.
수치를 새로 뽑고 싶으면 터미널에서 `python track.py -n 3` 을 돌린다.

읽는 것
  runs/metrics_history.csv  회차별 지표 (track.py 가 한 줄씩 쌓는다)
  runs/last_routing.json    마지막 분류 측정의 혼동 행렬·오분류
  runs/usage.jsonl          토큰 사용량
  data/*.json               평가셋 구성 (문항 수·분할)
"""
import csv
import io
import json
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).parent.parent
RUNS = ROOT / "runs"
DATA = ROOT / "data"

st.set_page_config(page_title="ISMS-P 에이전트 — 성능 지표", page_icon="📊",
                   layout="wide")

st.markdown("""<style>
  header[data-testid="stHeader"] {display: none !important;}
  .block-container {padding-top: 1rem !important; max-width: 1500px !important;}
  [data-testid="stMetricValue"] {font-size: 1.35rem !important;}
  [data-testid="stMetricLabel"] {font-size: .76rem !important;}
  [data-testid="stVerticalBlock"] {gap: .4rem !important;}
  hr {margin: .5rem 0 !important;}
</style>""", unsafe_allow_html=True)


def head(text, size=".98rem", top=".4rem"):
    st.markdown(f'<div style="font-size:{size};font-weight:700;'
                f'margin:{top} 0 .35rem">{text}</div>', unsafe_allow_html=True)


@st.cache_data(show_spinner=False)
def history():
    p = RUNS / "metrics_history.csv"
    if not p.exists():
        return []
    return list(csv.DictReader(io.open(p, encoding="utf-8")))


@st.cache_data(show_spinner=False)
def routing():
    p = RUNS / "last_routing.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


@st.cache_data(show_spinner=False)
def evalsets():
    """평가셋 구성을 파일에서 직접 센다. 문서에 적어 둔 숫자와 어긋나지 않게."""
    out = {}
    g = json.loads((DATA / "goldenset.json").read_text(encoding="utf-8"))["cases"]
    for split in ("eval", "fewshot", "wild"):
        out[f"답변 · {split}"] = sum(1 for c in g if c["split"] == split)
    r = json.loads((DATA / "routing_set.json").read_text(encoding="utf-8"))["cases"]
    out["분류 · 경계 문항"] = len(r)
    m = json.loads((DATA / "multiturn_set.json").read_text(encoding="utf-8"))
    out["멀티턴 · 대화"] = len(m["conversations"])
    out["멀티턴 · 턴"] = sum(len(c["turns"]) for c in m["conversations"])
    return out


@st.cache_data(show_spinner=False)
def cost():
    p = RUNS / "usage.jsonl"
    if not p.exists():
        return None
    rows = [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l]
    tin = sum(r["in"] for r in rows)
    tout = sum(r["out"] for r in rows)
    won = (tin * 0.150 + tout * 0.600) / 1_000_000 * 1380   # gpt-4o-mini
    return {"calls": len(rows), "in": tin, "out": tout, "won": won}


def pct(v):
    return f"{100 * float(v):.1f}%" if v not in ("", None) else "—"


# ── 머리 ─────────────────────────────────────────────────────────
head("성능 지표", "1.3rem", "0")
st.caption("`track.py` 가 재서 남긴 기록을 읽어 그린다 — 이 화면은 모델을 부르지 않는다")

h = history()
if not h:
    st.warning("아직 기록이 없습니다. 터미널에서 `python track.py -n 3` 을 먼저 돌리세요.")
    st.stop()

last = h[-1]
st.caption(f"마지막 측정 {last['at']} · 커밋 `{last['commit']}`"
           + (" · **커밋하지 않은 변경이 있던 상태**" if last.get("dirty") == "True" else "")
           + f" · {last['model']} · {last['n']}회 반복 · {last['took_s']}초"
           + (f" · 메모: {last['note']}" if last.get("note") else ""))

# ── 최신 수치 ────────────────────────────────────────────────────
st.divider()
head("평가셋별 최신 수치")
st.caption("수치를 한 벌로 적지 않는 이유 — `eval` 은 개선의 대상이 된 집합이고, "
           "`wild`(구어체·축약)와 멀티턴은 나중에 따로 붙인 집합이다. "
           "**세 벌을 같이 봐야 실제 성능이 보인다.**")

c = st.columns(4)
c[0].metric("분류 정확도", pct(last["route_acc"]), help="경계 문항 평가셋")
c[1].metric("macro F1", pct(last["route_macro_f1"]))
c[2].metric("도구 호출 적절성 · eval", pct(last["eval_tool"]))
c[3].metric("답변 적절성 · eval", pct(last["eval_answer"]))

c = st.columns(4)
c[0].metric("도구 · wild", pct(last["wild_tool"]), help="짧고 거친 구어체 문의")
c[1].metric("답변 · wild", pct(last["wild_answer"]))
c[2].metric("도구 · 멀티턴", pct(last["multi_tool"]))
c[3].metric("답변 · 멀티턴", pct(last["multi_answer"]))

# ── 추이 ─────────────────────────────────────────────────────────
if len(h) > 1:
    st.divider()
    head("회차별 추이")
    st.caption("같은 입력에도 수치가 흔들린다. 한 번 재고 좋아졌다고 말할 수 없어서 쌓아 둔다.")
    keys = [("eval_answer", "답변 · eval"), ("wild_answer", "답변 · wild"),
            ("multi_answer", "답변 · 멀티턴"), ("route_acc", "분류 정확도")]
    chart = {label: [float(r[k]) * 100 if r.get(k) else None for r in h]
             for k, label in keys}
    st.line_chart(chart, height=260)
    st.caption("가로축은 측정 회차(오래된 것 → 최신). 값은 %.")

# ── 혼동 행렬 ────────────────────────────────────────────────────
r = routing()
if r:
    st.divider()
    left, right = st.columns([1.15, 1])
    with left:
        head("혼동 행렬 — 행이 정답, 열이 예측")
        st.caption(f"{r['cases']}건 × {r['n']}회 = {r['cases'] * r['n']}개 판정 · "
                   f"정확도 {r['acc']:.3f} · macro F1 {r['macro_f1']:.3f}")
        routes = r["routes"]
        rows = []
        for t in routes:
            row = {"정답 \\ 예측": t}
            row.update({p: r["matrix"][t][p] or "·" for p in routes})
            row["합계"] = sum(r["matrix"][t].values())
            rows.append(row)
        st.dataframe(rows, hide_index=True, use_container_width=True)
        st.caption("대각선이 맞힌 것. 대각선을 벗어난 칸이 오분류이고, "
                   "**어느 칸에 몰리는지가 곧 고칠 자리**다.")
    with right:
        head("카테고리별")
        st.dataframe([{"카테고리": k, "정밀도": f"{v['P']:.3f}",
                       "재현율": f"{v['R']:.3f}", "F1": f"{v['F1']:.3f}",
                       "문항": int(v["support"] / r["n"])}
                      for k, v in r["per_class"].items()],
                     hide_index=True, use_container_width=True)
        st.caption("정확도만 보면 문항이 많은 카테고리를 잘 맞히는 것으로 수치가 오른다. "
                   "macro F1 은 카테고리마다 F1 을 따로 내고 평균해서 "
                   "문항이 적은 쪽도 같은 무게로 센다.")

    if r["wrong"]:
        head("오분류 — 라우터가 스스로 댄 근거를 같이 본다")
        st.caption("점수만 보면 '괜찮네' 로 끝난다. 무엇을 왜 틀렸는지는 이유를 읽어야 보인다.")
        for w in r["wrong"]:
            with st.expander(f"[{w['id']}] {w['want']} → **{w['got']}** "
                             f"(확신도 {w['conf']:.2f}) · {w['q'][:44]}"):
                st.write(w["q"])
                st.caption(f"라우터가 댄 근거 — {w['why']}")
    else:
        st.success("마지막 측정에서 오분류 없음")

# ── 평가셋 구성 · 비용 ───────────────────────────────────────────
st.divider()
left, right = st.columns(2)
with left:
    head("평가셋 구성")
    st.caption("파일에서 직접 세어 그린다 — 문서에 적어 둔 숫자와 어긋나지 않게.")
    st.dataframe([{"평가셋": k, "건수": v} for k, v in evalsets().items()],
                 hide_index=True, use_container_width=True)
with right:
    head("비용")
    u = cost()
    if not u:
        st.caption("사용량 기록이 없습니다.")
    else:
        a, b = st.columns(2)
        a.metric("누적 호출", f"{u['calls']:,}회")
        b.metric("누적 비용", f"{u['won']:,.0f}원")
        st.caption(f"입력 {u['in']:,} · 출력 {u['out']:,} 토큰 · gpt-4o-mini · 1,380원/$ 기준")
        st.caption("문의 1건당 약 1.7원(호출 3.6회). OpenAI 대시보드는 조직 관리자만 "
                   "볼 수 있어서, 호출마다 응답에 딸려 오는 `token_usage` 를 직접 쌓아 센다.")

st.divider()
st.caption("수치를 새로 뽑으려면 터미널에서 `python track.py -n 3 --note \"무엇을 고쳤는지\"`. "
           "이 화면은 그 결과를 읽기만 한다.")
