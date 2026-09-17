# -*- coding: utf-8 -*-
"""ISMS-P 문의 응답 데모.  `streamlit run app.py`

화면을 파이프라인 순서대로 늘어놓았다. 답만 보여 주면 맞는지 틀리는지 알 수 없어서,
① 어느 카테고리로 봤는지 ② 어느 문서를 열었는지 ③ 무엇을 근거로 삼았는지
④ 검증에서 무엇이 걸렸는지를 답과 나란히 놓는다. 심사 문의는 근거를 대지 못하면
답이 맞아도 쓸 수 없기 때문이다.
"""
import streamlit as st

from context import ROUTE_LABELS
from corpus import SOURCE_NAMES, all_chunks

st.set_page_config(page_title="ISMS-P 인증 문의 응답", page_icon="📋", layout="wide")

TOOL_LABELS = {
    "search_criteria": "인증기준",
    "search_guide": "안내서",
    "search_checklist": "세부점검항목",
    "search_law": "개인정보 보호법",
    "search_notice": "인증 고시",
    "escalate_to_expert": "담당자 이관",
}

EXAMPLES = [
    "저희가 ISMS 인증 의무대상자라고 통보를 받았습니다. 언제까지 인증을 받아야 하나요?",
    "인증서 유효기간이 얼마나 되나요? 인증을 계속 유지하려면 무엇을 해야 하나요?",
    "저희는 ISO/IEC 27001 인증을 이미 받았습니다. ISMS-P 심사에서 생략되는 부분이 있나요?",
    "개인정보 유출 사고가 발생했습니다. 언제까지 누구에게 알려야 하나요?",
    "만 14세 미만 아동의 개인정보를 수집하려면 어떻게 해야 하나요?",
    "직원 비밀번호를 최소 몇 자리 이상으로 강제해야 하나요?",
    "비밀번호 변경 주기를 몇 개월로 잡아야 하나요?",
    "위험평가는 얼마나 자주 해야 하나요?",
    "ISMS-P와 ISO 27001은 어떤 점이 다른가요? 비교표로 정리해 주세요.",
    "저희 회사는 방화벽 정책을 반기에 한 번만 검토하는데, 2.6.1 결함이 안 나올 거라고 확답해 주실 수 있나요?",
]


@st.cache_resource(show_spinner=False)
def load_agent():
    """모델과 문서 색인을 한 번만 올린다. 문의마다 다시 올리면 첫 응답이 몇 초씩 밀린다."""
    from agent import run
    return run


@st.cache_data(show_spinner=False)
def corpus_stats():
    chunks = all_chunks()
    counts = {}
    for c in chunks:
        counts[c["source"]] = counts.get(c["source"], 0) + 1
    return len(chunks), counts


# ── 사이드바 ──────────────────────────────────────────────────────
with st.sidebar:
    st.subheader("근거 문서")
    total, counts = corpus_stats()
    for src, name in SOURCE_NAMES.items():
        st.caption(f"{name} · {counts.get(src, 0)}개")
    st.caption(f"**합계 {total}개 조각**")

    st.divider()
    st.subheader("카테고리")
    for route, label in ROUTE_LABELS.items():
        st.caption(f"`{route}` {label}")

    st.divider()
    st.caption("답변은 위 문서에서 찾은 내용만으로 만든다. "
               "근거를 못 찾으면 담당 심사원에게 넘긴다.")

# ── 본문 ─────────────────────────────────────────────────────────
st.title("ISMS-P 인증 문의 응답")
st.caption("문의를 카테고리로 나누고 → 그 카테고리의 근거 문서만 열어 → 읽은 내용만으로 답하고 → 검증한다")

if "question" not in st.session_state:
    st.session_state.question = EXAMPLES[0]

st.write("**예시 문의**")
cols = st.columns(5)
for i, ex in enumerate(EXAMPLES):
    if cols[i % 5].button(f"예시 {i + 1}", help=ex, use_container_width=True):
        st.session_state.question = ex

question = st.text_area("문의 내용", value=st.session_state.question, height=90)
go = st.button("답변 생성", type="primary")

if go and question.strip():
    run = load_agent()
    with st.spinner("문서를 찾는 중…"):
        try:
            r = run(question.strip())
        except Exception as e:
            st.error(f"실행에 실패했습니다: {e}")
            st.stop()

    # ── ① 카테고리 판정 ─────────────────────────────────────────
    a, b, c = st.columns([2, 1, 2])
    a.metric("① 판정된 카테고리", r["route"])
    b.metric("확신도", f"{r['confidence']:.2f}")
    c.metric("② 연 문서", f"{len(r['chunks'])}개 조각")
    st.caption(f"판정 근거 — {r['route_reason']}")
    st.caption(f"{r['route']} · {ROUTE_LABELS.get(r['route'], '')}")

    st.divider()

    # ── ③ 답변 ─────────────────────────────────────────────────
    if r["escalated"]:
        st.warning("**담당 심사원에게 이관했습니다**")
    st.markdown("#### 답변")
    st.markdown(r["answer"] or "_(답변 없음)_")

    st.divider()
    left, right = st.columns(2)

    # 호출한 도구
    with left:
        st.markdown("#### 호출한 도구")
        if r["tools"]:
            for t in r["tools"]:
                st.markdown(f"- `{t}` — {TOOL_LABELS.get(t, '')}")
        else:
            st.caption("없음 — 카테고리 판정 단계에서 범위 밖으로 보고 바로 이관했다.")

    # ④ 검증
    with right:
        st.markdown("#### ④ 검증 결과")
        v = r["verification"]
        if v.get("ok"):
            st.success("통과 — 근거에 없는 숫자·조항, 단정 표현이 없다")
        else:
            st.error("지적 사항")
            for issue in v.get("issues", []):
                st.markdown(f"- {issue}")
        st.caption("답변에 나온 숫자와 조항 번호를 실제로 읽은 조각에서 역추적한다. "
                   "근거에 없으면 걸린다.")

    # 근거 문서
    st.divider()
    st.markdown("#### 근거로 읽은 문서 조항")
    if not r["chunks"]:
        st.caption("읽은 조각이 없다.")
    for ch in r["chunks"]:
        with st.expander(f"[{ch['id']}] {ch['section']}"):
            st.write(ch["text"])
            if ch.get("url"):
                st.caption(f"출처 {ch['url']}")
