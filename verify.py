# -*- coding: utf-8 -*-
"""④ 검증.

답변을 내보내기 전에 규칙 위반을 찾는다. 모델에게 다시 물어보는 대신 규칙으로 잡는다.
규칙 검사는 공짜고 결과가 매번 같아서, 답변 품질과 검증 품질이 같이 흔들리지 않는다.

잡는 것은 세 가지다.
  1. 근거에 없는 숫자   — 조회한 조각 어디에도 없는 기간·자릿수·금액을 지어낸 경우
  2. 근거에 없는 조항   — 읽지 않은 인증기준 번호·법 조문을 인용한 경우
  3. 단정 표현         — 심사원 판단이 필요한 사안을 확정으로 말한 경우
"""
import re

# 숫자를 뽑되 비교 대상이 되게 정규화한다. 1,000 과 1000 은 같은 값으로 본다.
_NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")
# 인증기준 번호(2.7.1) 와 법·고시 조문(제21조, 제22조의2)
_CLAUSE = re.compile(r"\b\d\.\d{1,2}\.\d{1,2}\b|제\s?\d+조(?:의\s?\d+)?")
# 확정적으로 말하면 안 되는 표현
_ABSOLUTE = re.compile(r"반드시 (?:통과|합격|인증)|무조건|100% |결함이 아닙니다|문제없습니다")

# 숫자처럼 보이지만 근거를 따질 필요가 없는 것들
_SKIP_NUM = {"1", "2", "3", "4", "5", "6", "7", "8", "9", "10"}


def _norm(s):
    return s.replace(",", "").rstrip(".0") or "0"


def _haystack(chunks):
    return "\n".join(c["section"] + " " + c["text"] for c in chunks)


def check(answer, chunks):
    """위반 목록을 돌려준다. 빈 목록이면 통과."""
    issues = []
    hay = _haystack(chunks)
    hay_nums = {_norm(m) for m in _NUM.findall(hay)}
    hay_clauses = {re.sub(r"\s", "", m) for m in _CLAUSE.findall(hay)}

    # 조항 번호로 쓰인 숫자는 숫자 검사에서 뺀다. 조항은 따로 본다.
    clause_spans = [m.span() for m in _CLAUSE.finditer(answer)]

    for m in _NUM.finditer(answer):
        if any(a <= m.start() and m.end() <= b for a, b in clause_spans):
            continue
        v = _norm(m.group())
        if v in _SKIP_NUM or v in hay_nums:
            continue
        issues.append(f"근거에 없는 숫자: {m.group()}")

    for m in _CLAUSE.finditer(answer):
        c = re.sub(r"\s", "", m.group())
        if c not in hay_clauses:
            issues.append(f"조회하지 않은 조항 인용: {m.group()}")

    if _ABSOLUTE.search(answer):
        issues.append(f"단정 표현: {_ABSOLUTE.search(answer).group()}")

    if not chunks and len(answer) > 120:
        issues.append("근거 없이 길게 답함")

    # 같은 지적이 여러 번 나오면 한 번만 남긴다
    return list(dict.fromkeys(issues))


def verdict(answer, chunks):
    issues = check(answer, chunks)
    return {"ok": not issues, "issues": issues}
