# -*- coding: utf-8 -*-
"""전역 설정. 값을 바꾸고 싶으면 .env 를 쓰고 이 파일은 건드리지 않는다."""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).parent
DOCS = ROOT / "docs"
DATA = ROOT / "data"

load_dotenv(ROOT / ".env")

MODEL = os.getenv("ISMSP_MODEL", "gpt-4o-mini")
TEMPERATURE = 0.0

# 한 번의 문의에서 도구를 부를 수 있는 최대 횟수. 넘으면 강제로 답변 단계로 보낸다.
MAX_TOOL_TURNS = 3

# 검색이 한 번에 돌려주는 조각 수. 늘리면 근거는 넓어지고 토큰과 비용이 는다.
TOP_K = 4

# 안내서 한 조각이 3,000자까지 가므로 컨텍스트에 넣을 때 잘라 쓴다.
MAX_CHUNK_CHARS = 1200

# 라우터가 이 값보다 확신이 없으면 사람에게 넘긴다.
ROUTE_CONFIDENCE_FLOOR = 0.55


def check_env():
    """키가 없으면 실행 전에 알려준다. import 시점에 죽지는 않게 한다."""
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError(
            "OPENAI_API_KEY 가 없다. .env.example 을 .env 로 복사하고 키를 채워라."
        )
