# -*- coding: utf-8 -*-
"""조회 도구.

도구를 문서 갈래마다 하나씩 따로 둔 이유는 측정 때문이다. 도구가 하나뿐이면
"검색했다/안 했다" 밖에 재지 못한다. 갈래별로 나누면 **법 조문을 봐야 할 문의에
점검항목을 뒤졌다** 같은 잘못을 지표가 잡아낸다.
"""
from langchain_core.tools import tool

from config import TOP_K
from context import search_in_route

# 도구가 부를 때마다 어느 조각을 봤는지 여기에 쌓는다. 답변 뒤 검증과 화면 표시에 쓴다.
# 문의 한 건마다 reset() 으로 비운다.
_seen = {}


def reset():
    _seen.clear()


def seen_chunks():
    """이번 문의에서 실제로 읽은 조각들. 호출 순서를 유지한다."""
    return list(_seen.values())


def _run(query, route, source):
    hits = search_in_route(query, route, source=source, top_k=TOP_K)
    if not hits:
        return "검색 결과 없음. 다른 검색어로 한 번 더 찾아보거나 escalate_to_expert 로 넘겨라."
    out = []
    for c in hits:
        _seen[c["id"]] = c
        text = c["text"][:1200]
        out.append(f"[{c['id']}] {c['section']}\n{text}")
    return "\n\n".join(out)


def make_tools(route):
    """카테고리에 허용된 도구만 만들어 준다.

    허용되지 않은 도구는 아예 모델에게 주지 않는다. 프롬프트로 "쓰지 마라" 고 적는 것보다
    안 주는 쪽이 확실하다.
    """
    from context import ROUTE_DOCS

    @tool
    def search_criteria(query: str) -> str:
        """ISMS-P 인증기준(고시 별표 7) 본문에서 찾는다. 인증기준이 무엇을 요구하는지 알 때 쓴다."""
        return _run(query, route, "criteria")

    @tool
    def search_guide(query: str) -> str:
        """ISMS-P 인증기준 안내서에서 찾는다. 기준을 어떻게 이행하는지, 결함 사례가 무엇인지 알 때 쓴다."""
        return _run(query, route, "guide")

    @tool
    def search_checklist(query: str) -> str:
        """ISMS-P 세부점검항목에서 찾는다. 심사에서 무엇을 확인하고 어떤 증적을 내는지 알 때 쓴다."""
        return _run(query, route, "checklist")

    @tool
    def search_law(query: str) -> str:
        """개인정보 보호법 조문에서 찾는다. 법적 의무·기한·과태료를 알 때 쓴다."""
        return _run(query, route, "law")

    @tool
    def search_notice(query: str) -> str:
        """인증 고시 본문(제17조~제36조)에서 찾는다. 의무대상·신청·심사·수수료·사후관리·갱신·취소를 알 때 쓴다."""
        return _run(query, route, "notice")

    @tool
    def escalate_to_expert(reason: str) -> str:
        """문서만으로 답할 수 없을 때 담당 심사원에게 넘긴다. reason 에 넘기는 까닭을 한 문장으로 적는다."""
        return f"담당자에게 전달했다: {reason}"

    registry = {
        "search_criteria": search_criteria,
        "search_guide": search_guide,
        "search_checklist": search_checklist,
        "search_law": search_law,
        "search_notice": search_notice,
        "escalate_to_expert": escalate_to_expert,
    }
    sources, _ = ROUTE_DOCS.get(route, ([], []))
    names = [
        {"criteria": "search_criteria", "guide": "search_guide",
         "checklist": "search_checklist", "law": "search_law",
         "notice": "search_notice"}[s]
        for s in sources
    ] + ["escalate_to_expert"]
    return [registry[n] for n in names]
