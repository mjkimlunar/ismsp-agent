# -*- coding: utf-8 -*-
"""LangGraph 파이프라인.

    classify ──(gate)──> assemble ──> retrieve ⇄ tools ──> compose ──> verify ──> END
        │                                ↑                    │
        │                                └── 근거 부족 ────────┘
        └───────────> escalate <──────────────────────────────┘

단계를 노드로 분리한 이유는 각 단계를 따로 재고 따로 고치기 위해서다. 한 덩어리
프롬프트로 만들면 답이 틀렸을 때 분류가 틀린 건지 근거가 부족한 건지 알 수 없다.

retrieve 와 compose 를 나눈 것은 측정해 보고 내린 결정이다. 한 호출에서 조회와 작성을
같이 시키면 모델이 조회 결과를 조항 순서대로 받아쓰기만 하고 작성 규칙은 무시한다.
또 근거가 모자란 것을 스스로 알아차리고도("명시되어 있지 않지만") 더 찾지 않고 답해 버린다.
작성을 따로 떼어 내면 짧은 규칙만 주게 되어 형식이 지켜지고, 근거가 모자랄 때
NEED_MORE 를 내보내 조회로 되돌릴 수 있다.
"""
import json
from typing import Annotated, TypedDict

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

import tools as tool_mod
import verify
from config import MAX_TOOL_TURNS, MODEL, TEMPERATURE
from context import ROUTE_LABELS, search_in_route
from corpus import SOURCE_NAMES, render
from prompts import ANSWER_RULES, COMPOSE_RULES, ESCALATE_TEMPLATE
from router import classify, should_escalate

from usage import Meter

_llm = ChatOpenAI(model=MODEL, temperature=TEMPERATURE, callbacks=[Meter("답변")])


class State(TypedDict):
    question: str
    route: str
    confidence: float
    route_reason: str
    shelf: str                                  # ② 에서 조립한 근거 목차
    messages: Annotated[list, add_messages]
    answer: str
    missing: str                                # 근거에 없다고 작성 단계가 짚은 것
    retries: int
    escalated: bool
    escalate_reason: str
    verification: dict


# ── ① 카테고리 판정 ────────────────────────────────────────────────
def node_classify(state):
    d = classify(state["question"])
    return {"route": d["route"], "confidence": d["confidence"],
            "route_reason": d["reason"]}


def gate(state):
    """확신도와 카테고리를 보고 다음 노드를 고른다."""
    esc, why = should_escalate(state)
    return "escalate" if esc else "assemble"


# ── ② 카테고리별 근거 조립 ─────────────────────────────────────────
def node_assemble(state):
    """그 카테고리에서 열 수 있는 문서와, 문의에 가까운 조항의 **제목**을 모은다.

    본문은 넣지 않는다. 본문까지 넣으면 모델이 도구를 부르지 않고 답해 버려서
    어느 문서를 근거로 삼았는지 추적할 수 없게 된다. 목차만 주면 모델은
    "2.7.1 에 있겠구나" 를 알고 정확한 도구를 부른다.
    """
    from context import ROUTE_DOCS

    route = state["route"]
    sources, _ = ROUTE_DOCS[route]
    lines = []
    for src in sources:
        hits = search_in_route(state["question"], route, source=src, top_k=4)
        if not hits:
            continue
        titles = "\n".join(f"    - [{c['id']}] {c['section'].split(' > ')[-1]}"
                           for c in hits)
        lines.append(f"  {SOURCE_NAMES[src]} — {tool_of(src)}\n{titles}")

    shelf = "\n".join(lines) or "  (문의와 가까운 조항을 찾지 못했다)"
    return {"shelf": shelf}


def tool_of(source):
    return {"criteria": "search_criteria", "guide": "search_guide",
            "checklist": "search_checklist", "law": "search_law",
            "notice": "search_notice"}[source]


# ── ③-1 조회 ──────────────────────────────────────────────────────
def node_retrieve(state):
    route = state["route"]
    msgs = state.get("messages") or []

    if not msgs:
        system = (
            f"{ANSWER_RULES}\n\n"
            f"[판정된 카테고리] {route} — {ROUTE_LABELS[route]}\n"
            f"판정 근거: {state['route_reason']}\n\n"
            f"[열람 가능한 문서와 문의에 가까운 조항]\n{state['shelf']}\n\n"
            "위 목록은 제목뿐이다. 실제 내용은 해당 도구를 불러서 읽어야 한다.\n"
            "목록에 없는 조항이 필요하면 검색어를 바꿔 도구를 불러라."
        )
        msgs = [SystemMessage(system), HumanMessage(state["question"])]

    # 도구를 너무 많이 부르면 끊고 지금 가진 근거로 답하게 한다
    turns = sum(1 for m in msgs if isinstance(m, AIMessage) and m.tool_calls)
    # parallel_tool_calls=False — 한 번에 한 문서만 열게 한다. 동시에 부를 수 있게 두면
    # 모델이 고르지 않고 열람 가능한 문서를 전부 열어 버린다. 하나씩 열게 하면
    # 첫 문서에서 답이 나왔을 때 스스로 멈춘다.
    bound = _llm if turns >= MAX_TOOL_TURNS else _llm.bind_tools(
        tool_mod.make_tools(route), parallel_tool_calls=False)

    reply = bound.invoke(msgs)
    return {"messages": [reply]}


def route_after_retrieve(state):
    """조회를 더 할지, 작성으로 넘어갈지, 사람에게 넘길지."""
    last = state["messages"][-1]
    if not getattr(last, "tool_calls", None):
        return "compose"                       # 도구를 안 불렀으면 조회 끝
    if any(c["name"] == "escalate_to_expert" for c in last.tool_calls):
        return "escalate"
    return "tools"


# ── ③-2 작성 ──────────────────────────────────────────────────────
def node_compose(state):
    """읽은 조각만 놓고 답을 쓴다. 도구는 주지 않는다.

    조회 기록(messages)을 통째로 넘기지 않고 조각만 다시 정리해서 준다.
    대화 기록에는 검색 실패나 중복 조각이 섞여 있어서 그대로 주면 그걸 또 받아쓴다.
    """
    chunks = tool_mod.seen_chunks()
    body = "\n\n".join(render(c) for c in chunks) or "(근거 없음)"

    rules = COMPOSE_RULES
    if state.get("retries", 0) >= 2:
        # 조회 예산을 다 썼다. 여기서 또 NEED_MORE 를 받으면 답이 영영 안 나온다.
        # 넘기는 대신 지금 있는 근거로 쓰게 하되, 없는 것은 없다고 밝히게 한다.
        rules += ("\n\n조회는 여기까지다. 이제 NEED_MORE 를 쓰지 말고 지금 있는 근거로 답한다.\n"
                  "근거에 없는 값은 지어내지 말고 '문서가 구체적인 수치를 정해 두고 있지는 "
                  "않습니다' 처럼 없다는 사실을 그대로 밝힌다.")

    msgs = [
        SystemMessage(f"{rules}\n\n[근거]\n{body}"),
        HumanMessage(f"[문의]\n{state['question']}"),
    ]
    text = _llm.invoke(msgs).content.strip()

    if text.startswith("NEED_MORE"):
        return {"answer": "", "missing": text.split(":", 1)[-1].strip(),
                "retries": state.get("retries", 0) + 1}
    return {"answer": text, "missing": ""}


def route_after_compose(state):
    """근거가 모자라면 조회로 되돌린다.

    조회 예산을 다 쓰면 넘기지 않고 다시 작성으로 보낸다. 이때 node_compose 가
    규칙을 바꿔 '있는 것으로 쓰되 없는 건 없다고 밝혀라' 로 지시한다.
    근거가 **아예** 없을 때만 사람에게 넘긴다. 넘기기는 최후 수단이어야 한다.
    """
    if not state.get("missing"):
        return "verify"
    if not tool_mod.seen_chunks():
        return "escalate"
    r = state.get("retries", 0)
    if r < 2:
        return "hint"
    return "compose" if r < 3 else "escalate"


def node_hint(state):
    """무엇이 없었는지 알려 주고 다시 찾게 한다. 같은 검색을 되풀이하지 않게."""
    return {"messages": [HumanMessage(
        f"방금 읽은 근거에 '{state['missing']}' 이(가) 없다. "
        f"다른 문서를 열거나 검색어를 바꿔 그 값이 적힌 조각을 찾아라. "
        f"인증기준 본문에 수치가 없으면 안내서에 작성규칙 예시가 있는 경우가 많다.")]}


def make_tool_node(route):
    return ToolNode(tool_mod.make_tools(route))


def node_tools(state):
    """카테고리마다 도구가 다르므로 ToolNode 를 그때그때 만든다."""
    return make_tool_node(state["route"]).invoke(state)


# ── ④ 검증 ────────────────────────────────────────────────────────
def node_verify(state):
    chunks = tool_mod.seen_chunks()
    return {"verification": verify.verdict(state.get("answer", ""), chunks)}


# ── 넘기기 ────────────────────────────────────────────────────────
def node_escalate(state):
    why = state.get("escalate_reason", "")
    if not why and state.get("missing"):
        why = f"문서에서 '{state['missing']}' 에 해당하는 근거를 찾지 못했습니다."
    if not why:
        last = state["messages"][-1] if state.get("messages") else None
        calls = getattr(last, "tool_calls", None) or []
        for c in calls:
            if c["name"] == "escalate_to_expert":
                why = c["args"].get("reason", "")
        if not why:
            why = should_escalate(state)[1]

    text = ESCALATE_TEMPLATE.format(reason=why)
    return {"answer": text, "escalated": True, "escalate_reason": why,
            "verification": {"ok": True, "issues": []}}


def build():
    g = StateGraph(State)
    g.add_node("classify", node_classify)
    g.add_node("assemble", node_assemble)
    g.add_node("retrieve", node_retrieve)
    g.add_node("tools", node_tools)
    g.add_node("compose", node_compose)
    g.add_node("hint", node_hint)
    g.add_node("verify", node_verify)
    g.add_node("escalate", node_escalate)

    g.set_entry_point("classify")
    g.add_conditional_edges("classify", gate,
                            {"assemble": "assemble", "escalate": "escalate"})
    g.add_edge("assemble", "retrieve")
    g.add_conditional_edges("retrieve", route_after_retrieve,
                            {"tools": "tools", "compose": "compose",
                             "escalate": "escalate"})
    g.add_edge("tools", "retrieve")
    g.add_conditional_edges("compose", route_after_compose,
                            {"verify": "verify", "hint": "hint",
                             "compose": "compose", "escalate": "escalate"})
    g.add_edge("hint", "retrieve")
    g.add_edge("verify", END)
    g.add_edge("escalate", END)
    return g.compile()


_graph = None


def graph():
    global _graph
    if _graph is None:
        _graph = build()
    return _graph


def called_tools(messages):
    """대화 기록에서 실제로 부른 도구 이름을 모은다. 중복은 뺀다."""
    names = []
    for m in messages:
        for c in getattr(m, "tool_calls", None) or []:
            if c["name"] not in names:
                names.append(c["name"])
    return names


def run(question):
    """문의 하나를 처음부터 끝까지 돌린다. 화면과 평가가 같이 쓴다."""
    tool_mod.reset()
    final = graph().invoke({"question": question, "messages": [], "retries": 0,
                            "missing": ""}, {"recursion_limit": 30})
    return {
        "question": question,
        "route": final["route"],
        "confidence": final["confidence"],
        "route_reason": final["route_reason"],
        "answer": final.get("answer", ""),
        "tools": called_tools(final.get("messages", [])),
        "chunks": tool_mod.seen_chunks(),
        "escalated": final.get("escalated", False),
        "verification": final.get("verification", {"ok": True, "issues": []}),
    }


if __name__ == "__main__":
    import sys

    q = " ".join(sys.argv[1:]) or "개인정보 수집 동의를 받을 때 꼭 알려야 하는 것이 무엇인가요?"
    r = run(q)
    print(json.dumps({k: v for k, v in r.items() if k != "chunks"},
                     ensure_ascii=False, indent=2))
    print("\n읽은 조각:", [c["id"] for c in r["chunks"]])
