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
# 한자와 일본어 가나. 한국어 답변에 섞이면 근거에서 왔는지 확인해야 한다.
_FOREIGN = re.compile(r"[一-鿿぀-ヿ]")

# 숫자처럼 보이지만 근거를 따질 필요가 없는 것들
_SKIP_NUM = {"1", "2", "3", "4", "5", "6", "7", "8", "9", "10"}


def _norm(s):
    return s.replace(",", "").rstrip(".0") or "0"


def _haystack(chunks):
    return "\n".join(c["section"] + " " + c["text"] for c in chunks)


# "제32조제3항" 처럼 항까지 짚은 인용
_PARA = re.compile(r"제\s?(\d+)조(?:의\s?\d+)?\s?제\s?(\d+)항")
_CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮"


def _paragraph_text(article_text, para):
    """조문 본문에서 ①②③ 기호를 경계로 그 항만 떼어 낸다. 못 찾으면 None."""
    mark = _CIRCLED[para - 1]
    start = article_text.find(mark)
    if start < 0:
        return None
    rest = article_text[start + 1:]
    ends = [rest.find(c) for c in _CIRCLED if c in rest]
    cut = min([e for e in ends if e >= 0], default=len(rest))
    return rest[:cut]


def _check_paragraphs(answer, chunks):
    """항까지 짚은 인용이 정말 그 항의 내용인지 본다.

    조문 원문은 항을 ①②③ 기호로 적으므로 "제3항" 을 ③ 으로 바꿔 대조한다.
    항이 **있는지**만 보면 안 된다. 실제로 이런 오류가 나왔다 — 인증서 유효기간 3년은
    고시 제32조**제3항**인데 답변이 "제32조제1항" 이라고 적었다. ① 자체는 조문에 있으니
    존재 검사로는 통과한다. 그래서 답변이 그 문장에서 말한 **숫자가 그 항 안에 있는지**까지 본다.
    항이 틀리면 내용이 맞아도 담당자가 원문을 확인할 때 엉뚱한 자리를 본다.
    """
    out = []
    for m in _PARA.finditer(answer):
        art, para = m.group(1), int(m.group(2))
        if not 1 <= para <= len(_CIRCLED):
            continue

        # 그 조문을 **담고 있는** 조각을 찾는다. 본문에 그 번호가 나오는 것만으로는 안 된다.
        # 고시 제19조는 본문에서 "정보통신망법 제47조제2항" 을 인용하는데, 본문 검색으로
        # 찾으면 제19조 조각을 제47조인 줄 알고 그 ② 와 대조해 엉뚱한 지적을 냈다.
        # 우리 문서에 없는 외부 법률(정보통신망법 등) 인용은 항을 확인할 방법이 없으므로 건너뛴다.
        holders = [c for c in chunks
                   if re.search(rf"제\s?{art}조(?:의\s?\d+)?\s*\(", c["section"])]
        if not holders:
            continue

        holder = next((c for c in holders
                       if _paragraph_text(c["text"], para) is not None), None)
        if holder is None:
            out.append(f"근거에 없는 항 인용: {m.group()}")
            continue
        body = _paragraph_text(holder["text"], para)

        # 인용이 들어간 문장에서 숫자를 뽑는다. 여기서는 작은 숫자를 빼지 않는다.
        # 항을 짚는 인용에서는 3년·10일·연 1회 처럼 작은 수가 바로 핵심이다.
        s = answer.rfind(".", 0, m.start()) + 1
        e = answer.find(".", m.end())
        sentence = answer[s:e if e > 0 else len(answer)]
        # 한 문장에 인용이 여럿 섞이는 일이 흔하다. 다른 인용의 번호까지 끌어와 비교하면
        # 엉뚱한 지적이 나오므로, 조·항·별표·서식 번호는 모두 지우고 남은 숫자만 본다.
        stripped = _CLAUSE.sub(" ", _PARA.sub(" ", sentence))
        stripped = re.sub(r"(?:별표|별지|제)\s?\d+(?:호|조)?(?:서식)?", " ", stripped)
        cited = {_norm(x) for x in _NUM.findall(stripped)}

        # 그 조문에는 있는데 **짚은 항에는 없는** 숫자만 지적한다.
        # 조문 어디에도 없는 숫자는 위쪽 환각 검사가 이미 잡으므로 두 번 적지 않는다.
        in_article = {_norm(x) for x in _NUM.findall(holder["text"])}
        in_para = {_norm(x) for x in _NUM.findall(body)}
        astray = sorted((cited & in_article) - in_para)
        if astray:
            out.append(f"항을 잘못 짚음: {m.group()} 에 {', '.join(astray)} 은 없다")
    return out


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

    issues += _check_paragraphs(answer, chunks)

    # 근거에 없는 한자·가나. 작은 모델은 한국어를 생성하다 중국어로 새는 일이 있다.
    # 그런데 법령 원문이 「刑事訴訟法」·公衆·事實審 처럼 한자를 쓰므로 통째로 막을 수 없다
    # (근거 문서 410개 조각 중 16개에 한자 33종이 있다).
    # 그래서 다른 검사와 같은 기준을 쓴다 — 읽은 근거에 없는 글자면 모델이 만들어 낸 것이다.
    stray = sorted({c for c in _FOREIGN.findall(answer) if c not in hay})
    if stray:
        issues.append(f"근거에 없는 문자: {''.join(stray)[:16]}")

    if _ABSOLUTE.search(answer):
        issues.append(f"단정 표현: {_ABSOLUTE.search(answer).group()}")

    if not chunks and len(answer) > 120:
        issues.append("근거 없이 길게 답함")

    # 같은 지적이 여러 번 나오면 한 번만 남긴다
    return list(dict.fromkeys(issues))


def verdict(answer, chunks):
    issues = check(answer, chunks)
    return {"ok": not issues, "issues": issues}
