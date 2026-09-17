# -*- coding: utf-8 -*-
"""① 카테고리 판정.

구조화 출력으로 카테고리·확신도·근거를 한 번에 받는다. 확신도를 같이 받는 이유는
분류가 애매한 문의를 조용히 틀리는 대신 사람에게 넘기기 위해서다.
"""
from typing import Literal

from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from config import MODEL, ROUTE_CONFIDENCE_FLOOR, TEMPERATURE
from prompts import ROUTE_GUIDE

Route = Literal["MGMT", "PROTECT", "PRIVACY", "CERT", "OTHER"]


class Decision(BaseModel):
    route: Route = Field(description="다섯 카테고리 중 하나")
    confidence: float = Field(description="0.0~1.0 사이의 확신도", ge=0.0, le=1.0)
    reason: str = Field(description="어느 조항·조문 때문에 그렇게 보았는지 한 문장")


from usage import Meter

_llm = ChatOpenAI(model=MODEL, temperature=TEMPERATURE,
                  callbacks=[Meter("분류")]).with_structured_output(Decision)


def classify(question):
    """문의 하나를 분류한다. 실패하면 OTHER 로 떨어뜨려 사람에게 넘어가게 한다."""
    try:
        d = _llm.invoke([("system", ROUTE_GUIDE), ("human", question)])
    except Exception as e:
        return {"route": "OTHER", "confidence": 0.0, "reason": f"분류 실패: {e}"}
    return {"route": d.route, "confidence": d.confidence, "reason": d.reason}


def should_escalate(decision):
    """확신이 없으면 넘긴다.

    OTHER 자체는 '범위 밖' 이라는 판단이 선 것이므로 확신도가 높아도 넘기는 게 맞다.
    나머지 넷은 확신도가 바닥 아래일 때만 넘긴다.
    """
    if decision["route"] == "OTHER":
        return True, "우리 문서에 근거가 없는 주제"
    if decision["confidence"] < ROUTE_CONFIDENCE_FLOOR:
        return True, f"카테고리 판단이 불확실함(확신도 {decision['confidence']:.2f})"
    return False, ""


def warmup():
    """스레드로 병렬 실행하기 전에 모델 내부 캐시를 메인 스레드에서 채운다.

    langchain 이 지연 계산하는 속성을 여러 스레드가 동시에 건드리면
    dictionary changed size during iteration 으로 죽는다.
    """
    try:
        _ = _llm.steps[0].bound._serialized
    except Exception:
        pass
