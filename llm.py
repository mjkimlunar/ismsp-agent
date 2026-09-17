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
        return ChatGoogleGenerativeAI(model=MODEL, temperature=TEMPERATURE,
                                      callbacks=cb)
    if p == "ollama":
        from langchain_ollama import ChatOllama
        # num_ctx 를 올려 두지 않으면 기본 2048 토큰에서 근거가 잘린다.
        # 조각 4개에 발췌 1,200자씩이면 그 안에 못 들어간다.
        return ChatOllama(model=MODEL, temperature=TEMPERATURE,
                          num_ctx=int(os.getenv("ISMSP_NUM_CTX", "8192")),
                          callbacks=cb)

    from langchain_openai import ChatOpenAI
    return ChatOpenAI(model=MODEL, temperature=TEMPERATURE, callbacks=cb)


def label():
    return f"{provider()} · {MODEL}"
