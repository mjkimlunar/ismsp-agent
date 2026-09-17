# -*- coding: utf-8 -*-
"""토큰 사용량을 직접 센다.  `python usage.py` 로 지금까지 쓴 양을 본다.

OpenAI 대시보드는 조직 관리자만 볼 수 있으므로, 우리 쪽에서 호출할 때마다 응답에
같이 오는 token_usage 를 파일에 쌓아 두고 우리가 센다. 로그는 runs/usage.jsonl 이고
.gitignore 에 들어 있어 저장소에는 올라가지 않는다.
"""
import json
import os
import time
from pathlib import Path
from threading import Lock

from langchain_core.callbacks import BaseCallbackHandler

LOG = Path(__file__).parent / "runs" / "usage.jsonl"

# 1M 토큰당 달러 (입력, 출력). 모델을 바꾸면 여기도 채운다.
# 무료 한도 안에서 쓰는 모델과 로컬 모델은 0 으로 둔다 — 토큰은 세고 돈은 세지 않는다.
PRICES = {
    "gpt-4o-mini": (0.150, 0.600),
    "gpt-4o": (2.50, 10.00),
    "gpt-4.1-mini": (0.400, 1.600),
    # Google AI Studio 무료 한도 · 분당 요청 수 제한만 있고 과금은 없다
    "gemini-2.0-flash": (0.0, 0.0),
    "gemini-2.5-flash": (0.0, 0.0),
    "gemini-1.5-flash": (0.0, 0.0),
    # 로컬 실행 — 전기 말고는 안 든다
    "qwen2.5:3b": (0.0, 0.0),
    "qwen2.5:7b": (0.0, 0.0),
    "llama3.1:8b": (0.0, 0.0),
    "gemma2:9b": (0.0, 0.0),
}
USD_KRW = 1380

_lock = Lock()


class Meter(BaseCallbackHandler):
    """LLM 이 응답할 때마다 토큰 수를 한 줄씩 적는다."""

    def __init__(self, tag=""):
        self.tag = tag

    def on_llm_end(self, response, **kwargs):
        out = response.llm_output or {}
        usage = out.get("token_usage") or {}
        model = out.get("model_name", "")

        # 제공자마다 사용량을 다른 자리에 넣는다. OpenAI 는 llm_output.token_usage 에,
        # Gemini·Ollama 는 메시지의 usage_metadata 에 담아 준다. 둘 다 본다.
        if not usage:
            for gen in (response.generations or [[]])[0]:
                msg = getattr(gen, "message", None)
                meta = getattr(msg, "usage_metadata", None) or {}
                if meta:
                    usage = {"prompt_tokens": meta.get("input_tokens", 0),
                             "completion_tokens": meta.get("output_tokens", 0)}
                    model = model or (getattr(msg, "response_metadata", {}) or {}).get(
                        "model_name", "")
                    break
        if not usage:
            return

        row = {
            "t": round(time.time()),
            "tag": "/".join(x for x in (os.getenv("ISMSP_RUN_TAG", ""), self.tag) if x),
            "model": model,
            "in": usage.get("prompt_tokens", 0),
            "out": usage.get("completion_tokens", 0),
        }
        with _lock:
            LOG.parent.mkdir(exist_ok=True)
            with LOG.open("a", encoding="utf-8") as f:
                f.write(json.dumps(row) + "\n")


def rows():
    if not LOG.exists():
        return []
    return [json.loads(l) for l in LOG.read_text(encoding="utf-8").splitlines() if l]


def cost(model, tin, tout):
    pin, pout = PRICES.get(model, PRICES["gpt-4o-mini"])
    return (tin * pin + tout * pout) / 1_000_000


def report():
    rs = rows()
    if not rs:
        print("아직 기록이 없다. 에이전트를 한 번이라도 돌리면 쌓인다.")
        return

    by = {}
    for r in rs:
        d = by.setdefault((r["tag"] or "(태그 없음)", r["model"]),
                          {"calls": 0, "in": 0, "out": 0})
        d["calls"] += 1
        d["in"] += r["in"]
        d["out"] += r["out"]

    print(f"{'구간':22s} {'모델':14s} {'호출':>5s} {'입력':>10s} {'출력':>8s} {'원':>8s}")
    print("─" * 74)
    total = 0.0
    for (tag, model), d in sorted(by.items()):
        won = cost(model, d["in"], d["out"]) * USD_KRW
        total += won
        print(f"{tag[:22]:22s} {model[:14]:14s} {d['calls']:5d} "
              f"{d['in']:10,d} {d['out']:8,d} {won:8,.0f}")
    print("─" * 74)
    print(f"{'합계':22s} {'':14s} {len(rs):5d} "
          f"{sum(r['in'] for r in rs):10,d} {sum(r['out'] for r in rs):8,d} "
          f"{total:8,.0f}")
    print(f"\n환율 {USD_KRW}원/$ 로 환산. 문의 1건당 평균 "
          f"{total / max(1, len({(r['t'], r['tag']) for r in rs})):.1f}원 언저리다.")


if __name__ == "__main__":
    report()
