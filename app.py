# -*- coding: utf-8 -*-
"""ISMS-P 문의 응답 챗봇.  `streamlit run app.py`

대화형으로 바꾸면서 한 가지를 지켰다 — **답과 함께 근거를 늘 보여 준다.**
심사 문의는 근거를 대지 못하면 답이 맞아도 쓸 수 없다. 그래서 답변마다
어느 카테고리로 봤는지, 어느 문서를 열었는지, 검증에서 무엇이 걸렸는지를 접어서 붙인다.

멀티턴에서 이어받는 것은 **문의와 답변뿐**이다. 이전 턴의 조회 기록은 넘기지 않는다.
넘기면 다음 턴이 앞 근거를 그대로 받아쓴다.
"""
import streamlit as st

from context import ROUTE_LABELS
from corpus import SOURCE_NAMES, all_chunks

st.set_page_config(page_title="ISMS-P 인증 문의 응답", page_icon="📋", layout="wide")

st.markdown("""<style>
  header[data-testid="stHeader"] {display: none !important;}
  [data-testid="stToolbar"] {display: none !important;}
  .block-container {padding-top: 1rem !important; padding-bottom: 5rem !important;
                    max-width: 1100px !important;}
  [data-testid="stVerticalBlock"] {gap: .4rem !important;}
  hr {margin: .5rem 0 !important;}
  .stAlert {padding: .35rem .6rem !important;}
  .stAlert p {font-size: .84rem !important; margin: 0 !important;}
  [data-testid="stExpander"] summary p {font-size: .82rem !important;}
  section[data-testid="stSidebar"] {width: 250px !important; min-width: 250px !important;}
</style>""", unsafe_allow_html=True)

TOOL_LABELS = {
    "search_criteria": "인증기준",
    "search_guide": "안내서",
    "search_checklist": "세부점검항목",
    "search_law": "개인정보 보호법",
    "search_notice": "인증 고시",
    "escalate_to_expert": "담당자 이관",
}

PICK_HINT = "— 예시 선택 (직접 입력해도 됩니다) —"

STARTERS = [
    "인증서 유효기간이 얼마나 되나요? 인증을 계속 유지하려면 무엇을 해야 하나요?",
    "직원 비밀번호를 최소 몇 자리 이상으로 강제해야 하나요?",
    "개인정보 유출 사고가 발생했습니다. 언제까지 누구에게 알려야 하나요?",
    "저희는 ISO/IEC 27001 인증을 이미 받았습니다. ISMS-P 심사에서 생략되는 부분이 있나요?",
    "저희 회사는 방화벽 정책을 반기에 한 번만 검토하는데, 2.6.1 결함이 안 나올 거라고 확답해 주실 수 있나요?",
]


def head(text, size=".98rem", top=".35rem"):
    st.markdown(
        f'<div style="font-size:{size};font-weight:700;line-height:1.35;'
        f'margin:{top} 0 .35rem">{text}</div>', unsafe_allow_html=True)


@st.cache_resource(show_spinner=False)
def load_agent():
    from agent import run
    return run


@st.cache_data(show_spinner=False)
def corpus_stats():
    chunks = all_chunks()
    counts = {}
    for c in chunks:
        counts[c["source"]] = counts.get(c["source"], 0) + 1
    return len(chunks), counts


if "turns" not in st.session_state:
    st.session_state.turns = []          # [{question, answer, meta}, …]
if "pending" not in st.session_state:
    st.session_state.pending = None

# ── 사이드바 ──────────────────────────────────────────────────────
with st.sidebar:
    head("ISMS-P 상담", "1.05rem", "0")
    st.caption("① 카테고리 판정 → ② 근거 문서 조립 → ③ 읽은 내용만으로 답변 → ④ 검증")

    if st.button("대화 새로 시작", use_container_width=True):
        st.session_state.turns = []
        st.session_state.pending = None
        st.rerun()
    st.caption(f"현재 {len(st.session_state.turns)}턴")

    st.divider()
    head("근거 문서", "1rem", "0")
    total, counts = corpus_stats()
    for src, name in SOURCE_NAMES.items():
        st.caption(f"{name} · {counts.get(src, 0)}개")
    st.caption(f"**합계 {total}개 조각**")

    st.divider()
    head("카테고리", "1rem", "0")
    for route, label in ROUTE_LABELS.items():
        st.caption(f"`{route}` {label}")

    st.divider()
    st.caption("답변은 위 문서에서 찾은 내용만으로 만든다. "
               "근거를 못 찾으면 담당 심사원에게 넘긴다.")

# ── 대화 ─────────────────────────────────────────────────────────
head("ISMS-P 인증 문의 응답", "1.3rem", "0")

def pick_example():
    """예시를 고르면 문의로 넘기고 **드롭다운을 바로 되돌린다.**

    고른 값을 그대로 두면 두 가지가 어긋난다. 대화를 새로 시작해도 그 예시가 남아
    다시 제출되고, 같은 예시를 한 번 더 고를 수도 없다.
    위젯의 값은 이렇게 콜백 안에서만 되돌릴 수 있다 — 화면을 그린 뒤에 바꾸면
    Streamlit 이 막는다.
    """
    v = st.session_state.starter
    if v != PICK_HINT:
        st.session_state.pending = v
        st.session_state.starter = PICK_HINT


# 예시는 드롭다운으로 둔다. 버튼을 늘어놓으면 문장이 안 보여 무엇을 묻는지 알 수 없고,
# 대화가 길어져도 자리를 차지한다. 목록은 대화 중에도 그대로 남겨 이어 묻기 쉽게 한다.
st.selectbox("예시", [PICK_HINT] + STARTERS, label_visibility="collapsed",
             key="starter", on_change=pick_example)


def show_detail(meta):
    """답변 아래에 접어 두는 근거. 펼치면 판정·도구·검증·조항이 나온다."""
    v = meta["verification"]
    mark = "지적 있음" if not v.get("ok") else "검증 통과"
    with st.expander(f"{meta['route']} · 도구 {len(meta['tools'])}개 · "
                     f"근거 {len(meta['chunks'])}조각 · {mark}"):
        a, b = st.columns([1, 1])
        with a:
            st.markdown(f"**① 카테고리** `{meta['route']}` "
                        f"(확신도 {meta['confidence']:.2f})")
            st.caption(ROUTE_LABELS.get(meta["route"], ""))
            st.caption(f"판정 근거 — {meta['route_reason']}")
            st.markdown("**호출한 도구**")
            if meta["tools"]:
                st.markdown("\n".join(f"- `{t}` — {TOOL_LABELS.get(t, '')}"
                                      for t in meta["tools"]))
            else:
                st.caption("없음 — 판정 단계에서 범위 밖으로 보고 바로 이관했다.")
        with b:
            st.markdown("**④ 검증 결과**")
            if v.get("ok"):
                st.success("근거에 없는 숫자·조항·문자, 단정 표현이 없다")
            else:
                st.error("**지적 사항** — " + " · ".join(v.get("issues", [])))
            st.caption("답변의 숫자와 조항 번호를 실제로 읽은 조각에서 역추적한다.")

        st.markdown("**② 근거로 읽은 문서 조항**")
        if not meta["chunks"]:
            st.caption("읽은 조각이 없다.")
        for ch in meta["chunks"]:
            with st.expander(f"[{ch['id']}] {ch['section']}"):
                st.write(ch["text"])
                if ch.get("url"):
                    st.caption(f"출처 {ch['url']}")


for turn in st.session_state.turns:
    with st.chat_message("user"):
        st.write(turn["question"])
    with st.chat_message("assistant"):
        if turn["meta"].get("escalated"):
            st.warning("담당 심사원에게 이관했습니다")
        st.write(turn["answer"])
        show_detail(turn["meta"])

typed = st.chat_input("문의를 입력하세요")
question = typed or st.session_state.pending
st.session_state.pending = None

if question:
    with st.chat_message("user"):
        st.write(question)

    run = load_agent()
    # 이어받는 것은 문의와 답변뿐이다. 조회 기록은 턴마다 새로 만든다.
    history = [{"question": t["question"], "answer": t["answer"]}
               for t in st.session_state.turns]

    with st.chat_message("assistant"):
        with st.spinner("문서를 찾는 중…"):
            try:
                r = run(question, history)
            except Exception as e:
                st.error(f"실행에 실패했습니다: {e}")
                st.stop()
        if r["escalated"]:
            st.warning("담당 심사원에게 이관했습니다")
        st.write(r["answer"])
        meta = {k: r[k] for k in ("route", "confidence", "route_reason",
                                  "tools", "chunks", "escalated", "verification")}
        show_detail(meta)

    st.session_state.turns.append(
        {"question": question, "answer": r["answer"], "meta": meta})
