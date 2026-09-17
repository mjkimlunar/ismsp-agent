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
import re
from typing import Annotated, TypedDict

from langchain_core.messages import (AIMessage, HumanMessage, SystemMessage,
                                     ToolMessage)
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

import tools as tool_mod
import verify
from config import MAX_TOOL_TURNS
from context import ROUTE_LABELS, search_in_route
from corpus import SOURCE_NAMES, get_chunk, render
from llm import bind, chat, first_tool_call_only, text_of
from prompts import (ANSWER_RULES, COMPOSE_FINAL, COMPOSE_GATE, COMPOSE_HEAD,
                     COMPOSE_RULES, ESCALATE_TEMPLATE, with_history)
from router import classify, should_escalate

_llm = chat("답변")

# 문의가 수치를 묻는가 / 조각에 수치가 적혀 있는가
_ASKS_NUMBER = re.compile(r"몇|얼마|며칠|어느 정도|자릿수|주기|기한|비용|수수료")
_HAS_NUMBER = re.compile(r"\d+\s*(?:자리|개월|일|년|회|원|시간|분|%|배|명)")

# 앞 대화를 **가리키는** 말. 이런 게 있으면 그 문장만으로는 검색이 안 된다.
#
# "그럼" 은 넣으면 안 된다. 지시어가 아니라 접속사라서 새 주제를 꺼낼 때도 붙는다.
# "그럼 인증은 언제까지 받아야 하나요?" 에 앞 주제(비밀번호)를 섞었더니
# 검색이 엉뚱한 조항으로 끌려갔다.
_REFERS_BACK = re.compile(r"그건|그거|그게|그것|거기|해당|이건|이거|위에|앞에서|말씀하신")


def search_query(question, history):
    """검색에 쓸 질의를 만든다.

    "그건 언제까지예요?" 로는 BM25 가 아무것도 못 찾는다. 앞을 가리키는 말이 있거나
    문장이 너무 짧으면 직전 문의를 앞에 붙여 준다. 늘 붙이지는 않는다 —
    새 주제를 꺼낸 문의에까지 앞 문장을 섞으면 엉뚱한 조각이 올라온다.
    """
    if not history:
        return question
    if not (_REFERS_BACK.search(question) or len(question) < 18):
        return question
    return f"{history[-1]['question']} {question}"


# 같은 수치가 여러 문서에 있으면 원문을 먼저 본다. 안내서와 점검항목은 원문의 해설이다.
# 검색 점수로 고르면 안 된다. 안내서 조각이 길고 말이 많아 점수가 늘 더 높게 나와서,
# 인증기준 본문에 답이 적혀 있는 경우에도 해설서로 끌려간다.
_DOC_RANK = ["criteria", "law", "notice", "guide", "checklist"]


class State(TypedDict):
    question: str
    history: list                               # 이전 턴들 [{question, answer}, …]
    route: str
    confidence: float
    route_reason: str
    shelf: str                                  # ② 에서 조립한 근거 목차
    messages: Annotated[list, add_messages]
    answer: str
    missing: str                                # 근거에 없다고 작성 단계가 짚은 것
    retries: int
    nudged: bool                                # 도구를 부르라고 한 번 되돌렸는가
    escalated: bool
    escalate_reason: str
    verification: dict


# ── ① 카테고리 판정 ────────────────────────────────────────────────
def node_classify(state):
    d = classify(state["question"], state.get("history"))
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
    query = search_query(state["question"], state.get("history"))
    asks_number = bool(_ASKS_NUMBER.search(state["question"]))
    lines, best = [], []
    for src in sources:
        hits = search_in_route(query, route, source=src, top_k=4)
        if not hits:
            continue
        titles = "\n".join(f"    - [{c['id']}] {c['section'].split(' > ')[-1]}"
                           for c in hits)
        lines.append(f"  {SOURCE_NAMES[src]} — {tool_of(src)}\n{titles}")
        # 문의와 **가장 잘 맞는** 조각에 수치가 적혀 있는 문서만 후보로 둔다.
        # 조각마다 표시를 달면 문의와 무관한 조각의 숫자까지 걸려서 엉뚱한 문서를 연다.
        if _HAS_NUMBER.search(hits[0]["text"]):
            best.append((_DOC_RANK.index(src), src))

    shelf = "\n".join(lines) or "  (문의와 가까운 조항을 찾지 못했다)"

    # 앞 대화를 이어받은 문의라면 무엇을 이어받았는지 못 박는다.
    # 선반은 합성된 질의로 만들어 옳은 조항이 올라오는데, 정작 모델은 도구를 부를 때
    # 자기 검색어를 쓴다. "그건 심사 때 뭘 확인하나요?" 에 "심사 확인 절차" 로 검색해
    # 비밀번호가 아니라 퇴직·직무변경 조항을 읽은 적이 있다. 검색어를 지정해 줘야 한다.
    if query != state["question"]:
        top = next((c for src in sources
                    for c in search_in_route(query, route, source=src, top_k=1)), None)
        topic = top["section"].split(" > ")[-1] if top else ""
        shelf += (f"\n\n  이 문의는 앞 대화를 이어받은 것이다. 주제는 그대로 "
                  f"**{topic}** 다.\n"
                  f"  도구를 부를 때 검색어에 그 주제의 낱말을 반드시 넣어라. "
                  f"\"심사 확인\" 처럼 이번 턴에 새로 나온 말만으로 검색하면 주제를 잃는다.")

    if asks_number and best:
        # 어느 문서에 숫자가 있는지는 항목마다 다르다. 인증기준 2.5.4 에는 자릿수가
        # 없어 안내서를 봐야 하지만, 1.2.3 에는 "연 1회 이상" 이 있어 인증기준으로 족하다.
        # 규칙으로 못 박으면 한쪽이 반드시 틀리므로 문서를 실제로 보고 고른다.
        pick = tool_of(min(best)[1])
        shelf += (f"\n\n  문의가 수치를 묻고 있다. 문의에 가장 가까운 조항에 실제로 숫자가 "
                  f"적힌 문서는 하나뿐이다. {pick} 를 써라. 다른 문서에는 그 숫자가 없다.")
    return {"shelf": shelf}


# 도구 출력에 찍힌 조각 id. IC-1.1.1 / GD-2.5.4 / AR-19 / PIPA-22-2 를 모두 잡는다.
_CHUNK_ID = re.compile(r"\[([A-Z]{2,5}-[\d.]+(?:-\d+)?)\]")


def read_chunks(messages):
    """대화 기록에서 이번 문의가 실제로 읽은 조각을 되찾는다.

    도구가 무엇을 돌려줬는지는 ToolMessage 에 남아 있으므로 여기가 유일한 출처다.
    모듈 변수에 따로 쌓으면 스레드마다 어긋나고, 그러면 작성 단계가 남의 근거로 답을 쓴다.
    """
    ids = []
    for m in messages:
        if isinstance(m, ToolMessage):
            for cid in _CHUNK_ID.findall(m.content or ""):
                if cid not in ids:
                    ids.append(cid)
    return [c for c in (get_chunk(i) for i in ids) if c]


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
        msgs = [SystemMessage(system),
                HumanMessage(with_history(state["question"], state.get("history")))]

    # 도구를 너무 많이 부르면 끊고 지금 가진 근거로 답하게 한다
    turns = sum(1 for m in msgs if isinstance(m, AIMessage) and m.tool_calls)
    bound = _llm if turns >= MAX_TOOL_TURNS else bind(_llm,
                                                      tool_mod.make_tools(route))

    reply = bound.invoke(msgs)
    # 한 번에 한 문서만 연다. 제공자가 옵션으로 막아 주지 못하면 여기서 잘라 낸다.
    reply, dropped = first_tool_call_only(reply)
    return {"messages": [reply]}


def route_after_retrieve(state):
    """조회를 더 할지, 작성으로 넘어갈지, 사람에게 넘길지."""
    last = state["messages"][-1]
    if getattr(last, "tool_calls", None):
        if any(c["name"] == "escalate_to_expert" for c in last.tool_calls):
            return "escalate"
        return "tools"

    # 도구를 한 번도 부르지 않고 조회를 끝내려는 경우가 있다.
    # "비번 몇자리요?" 처럼 짧고 거친 문의에서 그랬다. 그러면 근거가 비어 있으니
    # 작성 단계가 NEED_MORE 를 내고 결국 사람에게 넘어간다 — 답할 수 있는데 넘기는 것이다.
    # 프롬프트에 "반드시 열어라" 를 적어 두는 것으로는 막히지 않아서 구조로 되돌린다.
    if not read_chunks(state["messages"]) and not state.get("nudged"):
        return "nudge"
    return "compose"


# ── ③-2 작성 ──────────────────────────────────────────────────────
def node_compose(state):
    """읽은 조각만 놓고 답을 쓴다. 도구는 주지 않는다.

    조회 기록(messages)을 통째로 넘기지 않고 조각만 다시 정리해서 준다.
    대화 기록에는 검색 실패나 중복 조각이 섞여 있어서 그대로 주면 그걸 또 받아쓴다.
    """
    chunks = read_chunks(state["messages"])
    body = "\n\n".join(render(c, state["question"]) for c in chunks) or "(근거 없음)"

    # 조회를 되돌릴 수 있을 때만 NEED_MORE 를 가르친다. 마지막 시도에는 그 말을 아예
    # 꺼내지 않는다. 가르쳐 놓고 쓰지 말라고 하면 모델은 가르친 쪽을 따른다.
    gate = COMPOSE_GATE if state.get("retries", 0) < 1 else COMPOSE_FINAL
    rules = COMPOSE_HEAD + gate + COMPOSE_RULES

    msgs = [
        SystemMessage(f"{rules}\n\n[근거]\n{body}"),
        HumanMessage(f"[문의]\n{state['question']}"),
    ]
    text = text_of(_llm.invoke(msgs)).strip()

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
    if not read_chunks(state["messages"]):
        return "escalate"
    # 되돌리기는 한 번만 한다. 두 번 세 번 돌려 보내면, 문서가 "자체적으로 결정한다" 고
    # 적어 둔 항목에서 모델이 끝내 숫자를 찾으려 다른 문서까지 열고도 못 찾아 넘겨 버린다.
    # 없다는 사실 자체가 답인 경우가 있으므로, 한 번 더 찾아보고 안 나오면 쓰게 한다.
    r = state.get("retries", 0)
    if r < 1:
        return "hint"
    return "compose" if r < 2 else "escalate"


def node_nudge(state):
    """문서를 한 번도 열지 않았을 때 되돌려 보낸다.

    목차에 이미 후보 조항이 올라와 있으므로, 검색어까지 짚어 주면 거의 확실히 부른다.
    한 번만 한다(nudged). 두 번 되돌려도 안 부르면 그때는 근거 없이 갈 수밖에 없다.
    """
    return {"nudged": True, "messages": [HumanMessage(
        "아직 문서를 하나도 열지 않았다. 네가 아는 지식으로 답하거나 넘기지 마라.\n"
        "위 목차에 올라온 조항 중 문의에 가장 가까운 것을 골라, 그 조항 제목에 나온 "
        "낱말을 검색어로 삼아 도구를 **반드시 한 번** 불러라.")]}


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
    chunks = read_chunks(state["messages"])
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
    g.add_node("nudge", node_nudge)
    g.add_node("hint", node_hint)
    g.add_node("verify", node_verify)
    g.add_node("escalate", node_escalate)

    g.set_entry_point("classify")
    g.add_conditional_edges("classify", gate,
                            {"assemble": "assemble", "escalate": "escalate"})
    g.add_edge("assemble", "retrieve")
    g.add_conditional_edges("retrieve", route_after_retrieve,
                            {"tools": "tools", "compose": "compose",
                             "nudge": "nudge", "escalate": "escalate"})
    g.add_edge("nudge", "retrieve")
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


def run(question, history=None):
    """문의 하나를 처음부터 끝까지 돌린다. 화면과 평가가 같이 쓴다.

    history 는 이전 턴들의 [{question, answer}, …] 다. 이전 턴의 **조회 기록은
    물려주지 않는다.** 물려주면 2번째 턴이 1번째 근거를 그대로 받아쓴다.
    이어받는 것은 문의와 답변뿐이고, 근거는 턴마다 새로 찾는다.
    """
    final = graph().invoke({"question": question, "history": history or [],
                            "messages": [], "retries": 0, "nudged": False,
                            "missing": ""}, {"recursion_limit": 30})
    msgs = final.get("messages", [])
    return {
        "question": question,
        "route": final["route"],
        "confidence": final["confidence"],
        "route_reason": final["route_reason"],
        "answer": final.get("answer", ""),
        "tools": called_tools(msgs),
        "chunks": read_chunks(msgs),
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
