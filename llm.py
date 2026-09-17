# -*- coding: utf-8 -*-
"""모델을 갈아 끼우는 층.

이 파이프라인은 모델에게 세 가지를 요구한다 — 구조화 출력(분류), 도구 호출(조회),
긴 지시 따르기(작성). 모델 급이 내려가면 이 셋이 **순서대로** 깨진다.
어디서 깨지는지 재려면 모델만 바꿔 돌릴 수 있어야 하므로 생성을 한곳에 모았다.

  ISMSP_PROVIDER=openai  ISMSP_MODEL=gpt-4o-mini        (기본)
  ISMSP_PROVIDER=google  ISMSP_MODEL=gemini-2.0-flash   GOOGLE_API_KEY 필요 · 무료 한도 있음
  ISMSP_PROVIDER=ollama  ISMSP_MODEL=qwen2.5:3b         키 불필요 · 완전 무료 · 로컬
"""
import os

from config import MODEL, TEMPERATURE
from usage import Meter


def provider():
    return os.getenv("ISMSP_PROVIDER", "openai").lower()


def chat(tag=""):
    """제공자에 맞는 채팅 모델을 만든다. 토큰 계측기는 어느 쪽이든 붙인다."""
    p, cb = provider(), [Meter(tag)]

    if p == "google":
        from langchain_google_genai import ChatGoogleGenerativeAI
        # 무료 한도는 분당 요청 수가 묶여 있어 429 가 흔하다. 재시도를 넉넉히 준다.
        # 동시 실행 수는 ISMSP_WORKERS 로 따로 낮춘다.
        return ChatGoogleGenerativeAI(model=MODEL, temperature=TEMPERATURE,
                                      max_retries=6, callbacks=cb)
    if p == "ollama":
        from langchain_ollama import ChatOllama
        # num_ctx 를 올려 두지 않으면 기본 2048 토큰에서 근거가 잘린다.
        # 조각 4개에 발췌 1,200자씩이면 그 안에 못 들어간다.
        return ChatOllama(model=MODEL, temperature=TEMPERATURE,
                          num_ctx=int(os.getenv("ISMSP_NUM_CTX", "8192")),
                          callbacks=cb)

    from langchain_openai import ChatOpenAI
    return ChatOpenAI(model=MODEL, temperature=TEMPERATURE, callbacks=cb)


def supports_parallel_toggle():
    """`parallel_tool_calls` 를 받아 주는 제공자인가.

    OpenAI 고유 파라미터다. Gemini 에 넘기면
    "1 validation error … Extra inputs are not permitted" 로 죽는다.
    """
    return provider() == "openai"


def bind(model, tools):
    """도구를 붙이되, 제공자가 지원할 때만 '한 번에 하나' 옵션을 넘긴다."""
    if supports_parallel_toggle():
        return model.bind_tools(tools, parallel_tool_calls=False)
    return model.bind_tools(tools)


def first_tool_call_only(reply):
    """도구를 여러 개 부르면 첫 번째만 남긴다.

    '한 번에 한 문서만 연다' 는 이 파이프라인의 핵심 규칙이다. 도구를 동시에 부를 수
    있게 두면 모델이 고르지 않고 열람 가능한 문서를 전부 열어, 도구 호출 적절성이
    47.9% 로 주저앉는다. OpenAI 는 parallel_tool_calls=False 로 막을 수 있지만
    그건 그 제공자만의 기능이다. 모델을 바꿔 끼우려면 규칙을 **구조로** 지켜야 한다.
    받아 놓고 잘라 내면 어느 제공자에서든 같게 동작한다.
    """
    calls = getattr(reply, "tool_calls", None) or []
    if len(calls) <= 1:
        return reply, 0
    keep = calls[:1]
    update = {"tool_calls": keep}

    # tool_calls 만 자르면 안 된다. Gemini 는 함수 호출을 content 블록으로도 싣기 때문에,
    # 거기에 호출 2개가 남아 있으면 응답은 1개뿐이라 대화 기록이 어긋난다. 그러면
    # "function call turn comes immediately after a user turn" 400 으로 죽는다.
    # 남길 호출의 id 만 통과시켜 블록도 같이 자른다.
    ids = {c.get("id") for c in keep}
    content = getattr(reply, "content", None)
    if isinstance(content, list):
        kept = []
        for b in content:
            if isinstance(b, dict) and b.get("type") in ("tool_use", "function_call"):
                if b.get("id") in ids or b.get("name") == keep[0].get("name"):
                    kept.append(b)
            else:
                kept.append(b)
        update["content"] = kept

    trimmed = reply.model_copy(update=update)
    if getattr(trimmed, "additional_kwargs", None):
        trimmed.additional_kwargs.pop("tool_calls", None)
        trimmed.additional_kwargs.pop("function_call", None)
    return trimmed, len(calls) - 1


def text_of(msg):
    """응답 본문을 문자열로 만든다.

    제공자마다 `content` 타입이 다르다. OpenAI 는 문자열을 주는데 Gemini 는
    블록 리스트(`[{"type":"text","text":...}, …]`)를 준다. 모델을 바꿔 끼우려면
    이 차이를 여기서 흡수해야 한다. 그러지 않으면 작성 노드가
    `.content.strip()` 에서 AttributeError 로 죽는다 — 실제로 그렇게 죽었다.
    """
    c = getattr(msg, "content", msg)
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        out = []
        for b in c:
            if isinstance(b, str):
                out.append(b)
            elif isinstance(b, dict):
                out.append(b.get("text") or b.get("content") or "")
        return "".join(out)
    return str(c or "")


def label():
    return f"{provider()} · {MODEL}"
