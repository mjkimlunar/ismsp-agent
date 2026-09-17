# -*- coding: utf-8 -*-
"""모델을 바꿔 끼우고 **어느 단계에서 먼저 깨지는지** 잰다.
`python report_model.py [--quick]`

이 파이프라인은 모델에게 네 가지를 요구한다. 모델 급이 내려가면 순서대로 깨진다.

  1단계 응답        — 말이 되는 한국어를 돌려주는가
  2단계 구조화 출력  — pydantic 스키마(카테고리·확신도·근거)를 지키는가
  3단계 도구 호출    — 도구를 부르는가, 한 번에 하나만 부르는가
  4단계 지시 따르기  — 분류·도구 선택·답변 규칙을 얼마나 지키는가

앞 단계가 깨지면 뒤 단계는 재도 의미가 없으므로 사다리처럼 올라가며 멈춘다.
이걸 재는 이유는 "무료·로컬 모델로 어디까지 갈 수 있나" 를 알기 위해서다.

  ISMSP_PROVIDER=openai  ISMSP_MODEL=gpt-4o-mini
  ISMSP_PROVIDER=google  ISMSP_MODEL=gemini-2.0-flash
  ISMSP_PROVIDER=ollama  ISMSP_MODEL=qwen2.5:3b
"""
import argparse
import json
import re
import time

from langchain_core.messages import HumanMessage, SystemMessage

import llm
from config import DATA

CJK = re.compile(r"[一-鿿぀-ヿ]")
PASS, FAIL, WARN, QUOTA = "통과", "실패", "미흡", "한도"

# "모델이 못 한다" 와 "제공자가 안 해준다" 는 다른 이야기다. 섞으면 능력을 잘못 판정한다.
# 무료 한도는 분당 요청 수와 일일 요청 수가 묶여 있고, 인기 모델은 과부하로 503 을 준다.
_QUOTA = re.compile(r"RESOURCE_EXHAUSTED|429|503|UNAVAILABLE|quota|rate limit|"
                    r"high demand|overloaded", re.I)


def why(e):
    """오류를 '한도·과부하' 와 '능력 부족' 으로 가른다."""
    s = str(e)
    return (QUOTA if _QUOTA.search(s) else FAIL), s


def step(n, title):
    print(f"\n{'─' * 66}\n  {n}단계 · {title}\n{'─' * 66}")


def one(label, verdict, detail=""):
    print(f"    {verdict}  {label}" + (f"  — {detail}" if detail else ""))


# ── 1단계 ─────────────────────────────────────────────────────────
def check_reply():
    step(1, "응답 — 말이 되는 한국어를 돌려주는가")
    m = llm.chat("진단")
    t0 = time.time()
    try:
        out = m.invoke([SystemMessage("한국어로만 답한다."),
                        HumanMessage("ISMS-P 인증이 무엇인지 한 문장으로 설명해라.")])
    except Exception as e:
        one("호출", FAIL, str(e)[:120])
        return False
    text = llm.text_of(out).strip()
    took = time.time() - t0
    one("호출", PASS, f"{took:.1f}초 · {len(text)}자")

    stray = sorted(set(CJK.findall(text)))
    if stray:
        one("한국어 유지", FAIL, f"한자·가나 혼입 {''.join(stray)[:20]}")
    else:
        one("한국어 유지", PASS)
    print(f"      → {text[:150]}")
    return bool(text)


# ── 2단계 ─────────────────────────────────────────────────────────
def check_structured(n=5):
    step(2, "구조화 출력 — 카테고리·확신도·근거 스키마를 지키는가")
    from router import classify

    qs = ["인증서 유효기간이 얼마나 되나요?",
          "개인정보 파기 기한이 어떻게 되나요?",
          "비밀번호를 몇 자리로 해야 하나요?",
          "위험평가는 얼마나 자주 하나요?",
          "컨설팅 업체를 추천해 주세요."][:n]
    ok = quota = 0
    for q in qs:
        d = classify(q)
        if d["reason"].startswith("분류 실패"):
            v, s = why(d["reason"])
            quota += (v == QUOTA)
            one(q[:24], v, s[:74])
        elif d["route"] in ("MGMT", "PROTECT", "PRIVACY", "CERT", "OTHER"):
            ok += 1
        else:
            one(q[:24], FAIL, f"스키마 밖의 값: {d['route']}")

    tried = len(qs) - quota
    if tried == 0:
        one("스키마 준수", QUOTA, "한도·과부하로 한 번도 재지 못했다")
        return False
    rate = ok / tried
    note = f"({quota}건은 한도·과부하로 제외)" if quota else ""
    one(f"스키마 준수 {ok}/{tried} {note}",
        PASS if rate == 1 else (WARN if rate >= .6 else FAIL))
    return rate >= .6


# ── 3단계 ─────────────────────────────────────────────────────────
def check_tools():
    step(3, "도구 호출 — 도구를 부르는가, 한 번에 하나만 부르는가")
    import tools as tool_mod

    m = llm.chat("진단")
    try:
        bound = llm.bind(m, tool_mod.make_tools("CERT"))
    except Exception as e:
        v, s = why(e)
        one("bind_tools", v, s[:110])
        return False
    one("bind_tools", PASS,
        "parallel_tool_calls 지원" if llm.supports_parallel_toggle()
        else "parallel_tool_calls 미지원 — 호출 뒤 잘라 낸다")

    try:
        out = bound.invoke([
            SystemMessage("근거를 찾으려면 반드시 도구를 불러야 한다."),
            HumanMessage("인증서 유효기간이 몇 년인지 고시에서 찾아라.")])
    except Exception as e:
        one("도구 호출", FAIL, str(e)[:110])
        return False

    calls = getattr(out, "tool_calls", None) or []
    if not calls:
        one("도구 호출", FAIL, f"도구를 부르지 않고 바로 답했다 — {llm.text_of(out)[:60]}")
        return False
    one("도구 호출", PASS, f"{[c['name'] for c in calls]}")
    trimmed, dropped = llm.first_tool_call_only(out)
    if dropped:
        one("한 번에 하나만", PASS, f"모델이 {len(calls)}개를 불러 {dropped}개를 잘라 냈다")
    else:
        one("한 번에 하나만", PASS, "모델이 하나만 불렀다")
    return True


# ── 4단계 ─────────────────────────────────────────────────────────
def check_routing(n):
    step(4, "지시 따르기 ① 분류 정확도")
    from report_routing import load_cases, metrics, one_round

    cases = load_cases()
    pairs = []
    for _ in range(n):
        pairs += [(c["route"], d["route"]) for c, d in one_round(cases)]
    acc, per, macro, mat = metrics(pairs)
    one(f"정확도 {acc:.3f} · macro F1 {macro:.3f}",
        PASS if acc >= .9 else (WARN if acc >= .7 else FAIL),
        f"{len(cases)}건 × {n}회")
    worst = sorted(per.items(), key=lambda kv: kv[1]["F1"])[:2]
    for r, v in worst:
        print(f"      가장 약한 카테고리 {r}: F1 {v['F1']:.3f} (정밀도 {v['P']:.3f} 재현율 {v['R']:.3f})")
    return acc


def check_answers(n):
    step(4, "지시 따르기 ② 도구 호출 적절성 · 답변 적절성")
    from evaluate import load_cases, one_round, summarize

    cases = load_cases("eval")
    runs = [summarize(one_round(cases)) for _ in range(n)]
    tool = sum(r["tool"] for r in runs) / n
    ans = sum(r["answer"] for r in runs) / n
    one(f"도구 호출 적절성 {100 * tool:.1f}%",
        PASS if tool >= .9 else (WARN if tool >= .6 else FAIL))
    one(f"답변 적절성 {100 * ans:.1f}%",
        PASS if ans >= .75 else (WARN if ans >= .5 else FAIL))
    return tool, ans


def check_language():
    step(4, "지시 따르기 ③ 한국어 유지 — 근거에 없는 문자가 섞이는가")
    from agent import run
    from verify import _FOREIGN

    qs = ["인증서 유효기간이 얼마나 되나요?",
          "개인정보 유출 사고가 발생했습니다. 언제까지 누구에게 알려야 하나요?",
          "직원 비밀번호를 최소 몇 자리 이상으로 강제해야 하나요?"]
    bad = 0
    for q in qs:
        try:
            r = run(q)
        except Exception as e:
            one(q[:26], FAIL, str(e)[:80])
            bad += 1
            continue
        hay = "\n".join(c["text"] for c in r["chunks"])
        stray = sorted({c for c in _FOREIGN.findall(r["answer"]) if c not in hay})
        if stray:
            bad += 1
            one(q[:26], FAIL, f"근거에 없는 문자 {''.join(stray)[:16]}")
        else:
            one(q[:26], PASS)
    one(f"한국어 유지 {len(qs) - bad}/{len(qs)}", PASS if bad == 0 else FAIL)
    return bad == 0


def main(quick):
    print(f"모델 진단 — {llm.label()}")
    n = 1 if quick else 3

    if not check_reply():
        print("\n1단계에서 멈췄다. 모델이 응답하지 않으므로 뒤 단계는 재지 않는다.")
        return
    if not check_structured():
        print("\n2단계에서 멈췄다. 구조화 출력이 안 되면 라우터가 동작하지 않는다.")
        print("이 경우 카테고리를 자유 텍스트로 받아 파싱하는 대체 경로가 필요하다.")
        return
    if not check_tools():
        print("\n3단계에서 멈췄다. 도구 호출이 안 되면 근거를 가져올 수 없다.")
        print("이 경우 ② 조립 단계에서 본문까지 프롬프트에 넣는 구조로 바꿔야 한다.")
        print("대신 '어느 문서를 근거로 삼았는지' 를 추적할 수 없게 되고 지표 ① 도 무의미해진다.")
        return

    acc = check_routing(n)
    tool, ans = check_answers(n)
    ko = check_language()

    print(f"\n{'═' * 66}")
    print(f"  {llm.label()} 요약")
    print(f"    분류 정확도            {acc:.3f}")
    print(f"    도구 호출 적절성        {100 * tool:.1f}%")
    print(f"    답변 적절성            {100 * ans:.1f}%")
    print(f"    한국어 유지            {'예' if ko else '아니오'}")
    print(f"{'═' * 66}")
    print("\n비용은 `python usage.py` 로 본다. 무료 모델이면 0원으로 잡힌다.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true", help="반복을 1회로 줄여 빨리 본다")
    main(ap.parse_args().quick)
