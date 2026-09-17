# -*- coding: utf-8 -*-
"""조회 도구.

도구를 문서 갈래마다 하나씩 따로 둔 이유는 측정 때문이다. 도구가 하나뿐이면
"검색했다/안 했다" 밖에 재지 못한다. 갈래별로 나누면 **법 조문을 봐야 할 문의에
점검항목을 뒤졌다** 같은 잘못을 지표가 잡아낸다.
"""
from langchain_core.tools import tool

from config import TOP_K
from context import search_in_route
from corpus import render


def _run(query, route, source):
    """검색 결과를 조각 id 를 붙여 돌려준다.

    어느 조각을 읽었는지는 **따로 저장하지 않는다.** 여기에 모듈 변수로 쌓아 두면
    평가처럼 여러 문의를 동시에 돌릴 때 서로 섞이고, LangGraph 가 노드를 다른
    스레드에서 실행하기도 해서 스레드 지역 변수로도 해결되지 않는다.
    대신 출력에 [조각id] 를 찍어 두고, 필요한 쪽에서 대화 기록을 읽어 되찾는다.
    근거의 출처가 대화 기록 하나로 일원화되어 추적도 쉬워진다.
    """
    hits = search_in_route(query, route, source=source, top_k=TOP_K)
    if not hits:
        return "검색 결과 없음. 다른 검색어로 한 번 더 찾아보거나 escalate_to_expert 로 넘겨라."
    return "\n\n".join(render(c, query) for c in hits)


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
