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

# 화면 전체가 스크롤 없이 한 장에 담기게 여백과 글자 크기를 줄인다.
# 결과를 설명하려면 답변·도구·검증·근거를 **같이** 보여 줘야 하는데, 기본 여백으로는
# 근거 목록이 화면 밖으로 밀려서 캡처 한 장에 안 들어갔다.
st.markdown("""<style>
  /* Streamlit 은 화면 위에 고정 헤더(Deploy 버튼)를 띄우고, .block-container 의
     기본 padding-top 6rem 으로 그 아래를 피한다. 여백을 줄이려고 padding 만 깎으면
     제목이 헤더 뒤로 들어가 사라진다. 그래서 헤더를 아예 없애고 여백을 줄인다. */
  header[data-testid="stHeader"] {display: none !important;}
  [data-testid="stToolbar"] {display: none !important;}
  .block-container {padding-top: 1.1rem !important; padding-bottom: 1rem !important;
                    max-width: 1680px !important;}
  [data-testid="stMetricValue"] {font-size: 1.3rem !important; font-weight: 600 !important;}
  [data-testid="stMetricLabel"] {font-size: .76rem !important;}
  [data-testid="stVerticalBlock"] {gap: .38rem !important;}
  hr {margin: .55rem 0 !important;}
  .stAlert {padding: .4rem .65rem !important;}
  .stAlert p {font-size: .85rem !important; margin: 0 !important;}
  [data-testid="stExpander"] summary p {font-size: .82rem !important;}
  [data-testid="stExpander"] details {border-radius: 4px !important;}
  section[data-testid="stSidebar"] {width: 250px !important; min-width: 250px !important;}
  section[data-testid="stSidebar"] .block-container {padding-top: 1rem !important;}
  section[data-testid="stSidebar"] h3 {font-size: .92rem !important;}
</style>""", unsafe_allow_html=True)

TOOL_LABELS = {
    "search_criteria": "인증기준",
    "search_guide": "안내서",
    "search_checklist": "세부점검항목",
    "search_law": "개인정보 보호법",
    "search_notice": "인증 고시",
    "escalate_to_expert": "담당자 이관",
}

PICK_HINT = "— 예시 선택 —"

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


def head(text, size=".98rem", top=".35rem"):
    """제목을 인라인 스타일로 직접 그린다.

    st.title / st.markdown("#### …") 은 Streamlit 이 제 CSS 로 크기를 잡는데,
    그 선택자가 더 구체적이어서 바깥에서 줄이려 들면 먹지 않거나 통째로 어그러진다.
    화면 한 장에 담는 게 목적이므로 크기를 직접 지정하는 쪽이 확실하다.
    """
    st.markdown(
        f'<div style="font-size:{size};font-weight:700;line-height:1.35;'
        f'letter-spacing:-.005em;margin:{top} 0 .35rem">{text}</div>',
        unsafe_allow_html=True)


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

# ── 본문 ─────────────────────────────────────────────────────────
head("ISMS-P 인증 문의 응답", "1.35rem", "0")
st.caption("① 카테고리 판정 → ② 그 카테고리의 근거 문서만 조립 → "
           "③ 읽은 내용만으로 답변 → ④ 검증 · 근거를 못 찾으면 담당 심사원에게 넘긴다")

pick, _, act = st.columns([6, 0.2, 1.2])
# 예시를 버튼 10개로 늘어놓으면 두 줄을 먹어서 결과가 화면 밖으로 밀린다.
# 맨 위에 안내 항목을 두어, 처음 열었을 때 예시가 고른 것처럼 보이지 않게 한다.
example = pick.selectbox("예시", [PICK_HINT] + EXAMPLES, label_visibility="collapsed")
question = st.text_area("문의 내용", height=72, label_visibility="collapsed",
                        placeholder="문의를 직접 적거나 위에서 예시를 고르세요",
                        value="" if example == PICK_HINT else example)
go = act.button("답변 생성", type="primary", use_container_width=True)

if go and question.strip():
    run = load_agent()
    with st.spinner("문서를 찾는 중…"):
        try:
            r = run(question.strip())
        except Exception as e:
            st.error(f"실행에 실패했습니다: {e}")
            st.stop()

    # ── ① 카테고리 판정 ─────────────────────────────────────────
    a, b, c = st.columns([2.2, 1, 2])
    a.metric("① 판정된 카테고리", r["route"])
    b.metric("확신도", f"{r['confidence']:.2f}")
    c.metric("읽은 근거", f"{len(r['chunks'])}개 조각")
    st.caption(f"**{ROUTE_LABELS.get(r['route'], '')}** — 판정 근거: {r['route_reason']}")

    st.divider()

    # 답변을 넓게, 도구·검증을 옆에 붙인다. 위아래로 쌓으면 근거 목록이 화면 밖으로 밀린다.
    ans, side = st.columns([1.6, 1])

    with ans:
        if r["escalated"]:
            st.warning("**담당 심사원에게 이관했습니다**")
        head("③ 답변")
        st.markdown(r["answer"] or "_(답변 없음)_")

    with side:
        head("호출한 도구")
        if r["tools"]:
            st.markdown("\n".join(f"- `{t}` — {TOOL_LABELS.get(t, '')}"
                                  for t in r["tools"]))
        else:
            st.caption("없음 — 판정 단계에서 범위 밖으로 보고 바로 이관했다.")

        head("④ 검증 결과")
        v = r["verification"]
        if v.get("ok"):
            st.success("통과 — 근거에 없는 숫자·조항, 단정 표현이 없다")
        else:
            st.error("**지적 사항** — " + " · ".join(v.get("issues", [])))
        st.caption("답변의 숫자와 조항 번호를 실제로 읽은 조각에서 역추적한다.")

    # 근거 문서
    st.divider()
    head("② 근거로 읽은 문서 조항")
    if not r["chunks"]:
        st.caption("읽은 조각이 없다.")
    for ch in r["chunks"]:
        with st.expander(f"[{ch['id']}] {ch['section']}"):
            st.write(ch["text"])
            if ch.get("url"):
                st.caption(f"출처 {ch['url']}")
