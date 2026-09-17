# -*- coding: utf-8 -*-
"""카테고리 → 근거 문서 매핑표.

이 표가 이 프로젝트의 중심이다. 카테고리를 정하는 이유는 문의를 예쁘게 묶으려는 게
아니라, **어느 문서를 펼칠지 정하기 위해서**다. 그래서 다섯 카테고리는 각각 다른
문서 집합을 가리키고, 겹치는 곳에는 이유가 있다.

  MGMT/PROTECT/PRIVACY 는 인증기준 1.x/2.x/3.x 를 나눈 것이므로 같은 세 문서
  (인증기준·안내서·점검항목)를 쓰되 **번호대(domain)로 잘라** 서로 다른 조각을 본다.
  PRIVACY 만 개인정보 보호법이 더 붙는데, 3.x 요구사항이 법 조문을 근거로 하기
  때문이다. CERT 는 인증기준과 무관하고 고시 본문만 본다.
"""
from corpus import SOURCE_NAMES, search

# 카테고리 → (그 카테고리에서 쓸 수 있는 문서 갈래, 검색을 가둘 번호대)
ROUTE_DOCS = {
    "MGMT":    (["criteria", "guide", "checklist"], ["MGMT"]),
    "PROTECT": (["criteria", "guide", "checklist"], ["PROTECT"]),
    "PRIVACY": (["criteria", "guide", "checklist", "law"], ["PRIVACY"]),
    "CERT":    (["notice"], ["CERT"]),
    "OTHER":   ([], []),
}

# 카테고리 → 그 카테고리에서 쓸 수 있는 도구 이름. 라우팅 결과에 따라 도구를 갈아 끼운다.
SOURCE_TOOL = {
    "criteria": "search_criteria",
    "guide": "search_guide",
    "checklist": "search_checklist",
    "law": "search_law",
    "notice": "search_notice",
}

ROUTE_LABELS = {
    "MGMT": "관리체계 수립 및 운영 (1.x)",
    "PROTECT": "보호대책 요구사항 (2.x)",
    "PRIVACY": "개인정보 처리 단계별 요구사항 (3.x) · 개인정보 보호법",
    "CERT": "인증 제도 및 심사 절차 (고시 본문)",
    "OTHER": "범위 밖",
}


def allowed_tools(route):
    """그 카테고리에서 부를 수 있는 도구 이름들. 넘기기는 어디서나 부를 수 있다."""
    sources, _ = ROUTE_DOCS.get(route, ([], []))
    return [SOURCE_TOOL[s] for s in sources] + ["escalate_to_expert"]


def search_in_route(query, route, source=None, top_k=4):
    """카테고리 범위 안에서만 검색한다. 범위를 벗어난 문서는 애초에 후보가 아니다."""
    sources, domains = ROUTE_DOCS.get(route, ([], []))
    if not sources:
        return []
    if source:
        if source not in sources:
            return []
        sources = [source]
    return search(query, sources=sources, domains=domains, top_k=top_k)


def mapping_table():
    """REPORT.md 에 넣을 매핑표를 코드에서 뽑는다. 문서와 코드가 어긋나지 않게."""
    rows = []
    for route, (sources, domains) in ROUTE_DOCS.items():
        docs = " · ".join(SOURCE_NAMES[s] for s in sources) or "—"
        tools = " · ".join(allowed_tools(route))
        rows.append((route, ROUTE_LABELS[route], docs, tools))
    return rows


if __name__ == "__main__":
    for route, label, docs, tools in mapping_table():
        print(f"| {route} | {label} | {docs} | {tools} |")
