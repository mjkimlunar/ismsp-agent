# -*- coding: utf-8 -*-
"""근거 문서를 적재하고 검색한다.

문서는 docs/ 에 내려받은 원본 그대로 두고, 어느 문서가 어느 카테고리에 속하는지는
코드로 표시한다. 원본을 고치지 않아야 출처를 나중에 검증할 수 있다.

검색은 문자 바이그램 BM25 다. 한국어는 조사가 붙어 "동의를 / 동의는 / 동의" 가 전부
다른 낱말이 되므로 띄어쓰기 단위로 자르면 놓친다. 두 글자씩 겹쳐 자르면 "동의" 가
어느 형태로 나타나도 걸린다. 형태소 분석기를 쓰면 더 낫지만 설치가 무거워서 뺐다.
"""
import json
import math
import re
from collections import Counter, defaultdict
from functools import lru_cache

from config import DOCS, MAX_CHUNK_CHARS

# 문서 갈래 → 사람이 읽는 이름. 답변에 출처로 찍힌다.
SOURCE_NAMES = {
    "criteria": "ISMS-P 인증기준(고시 별표 7)",
    "guide": "ISMS-P 인증기준 안내서",
    "checklist": "ISMS-P 세부점검항목",
    "law": "개인정보 보호법",
    "notice": "정보보호 및 개인정보보호 관리체계 인증 등에 관한 고시",
}

# 인증기준 번호 앞자리 → 카테고리. 안내서·점검항목도 같은 번호 체계를 쓴다.
_DOMAIN_BY_PREFIX = {"1": "MGMT", "2": "PROTECT", "3": "PRIVACY"}


def _domain_of(chunk_id):
    """IC-2.7.1 / GD-2.7.1 / EX-2.7.1 → PROTECT"""
    m = re.match(r"[A-Z]+-(\d)\.", chunk_id)
    return _DOMAIN_BY_PREFIX.get(m.group(1)) if m else None


def _bigrams(text):
    """한글·영숫자만 남기고 두 글자씩 겹쳐 자른다."""
    s = re.sub(r"[^가-힣a-zA-Z0-9]", "", text.lower())
    return [s[i:i + 2] for i in range(len(s) - 1)]


def _load():
    """세 파일을 읽어 조각 목록 하나로 합친다. id 충돌은 여기서 푼다."""
    items, seen = [], Counter()

    def add(raw, source, domain):
        cid = raw["id"]
        seen[cid] += 1
        if seen[cid] > 1:                      # PIPA-22 가 제22조와 제22조의2 로 겹친다
            cid = f"{cid}-{seen[cid]}"
        items.append({
            "id": cid,
            "text": raw["text"],
            "url": raw.get("url", ""),
            "section": raw.get("section", ""),
            "source": source,
            "domain": domain,
        })

    for raw in json.loads((DOCS / "chunks.json").read_text(encoding="utf-8")):
        sec = raw.get("section", "")
        if sec.startswith("개인정보 보호법"):
            add(raw, "law", "PRIVACY")
        elif sec.startswith("고시 본문"):
            add(raw, "notice", "CERT")
        else:
            add(raw, "criteria", _domain_of(raw["id"]))

    for raw in json.loads((DOCS / "chunks-guide.json").read_text(encoding="utf-8")):
        add(raw, "guide", _domain_of(raw["id"]))

    for raw in json.loads((DOCS / "chunks-excel.json").read_text(encoding="utf-8")):
        add(raw, "checklist", _domain_of(raw["id"]))

    return items


@lru_cache(maxsize=1)
def _index():
    """BM25 에 필요한 통계를 한 번만 계산해 둔다."""
    items = _load()
    docs = [Counter(_bigrams(c["section"] + " " + c["text"])) for c in items]
    lens = [sum(d.values()) or 1 for d in docs]
    avg = sum(lens) / len(lens)

    postings = defaultdict(list)               # 바이그램 → 그 낱말이 나온 조각 번호들
    for i, d in enumerate(docs):
        for term in d:
            postings[term].append(i)

    n = len(items)
    idf = {t: math.log(1 + (n - len(ps) + 0.5) / (len(ps) + 0.5))
           for t, ps in postings.items()}
    return items, docs, lens, avg, postings, idf


def all_chunks():
    return _index()[0]


@lru_cache(maxsize=1)
def _by_id():
    return {c["id"]: c for c in all_chunks()}


def get_chunk(chunk_id):
    return _by_id().get(chunk_id)


# 고객이 쓰는 말 → 문서가 쓰는 말.
#
# BM25 는 글자가 겹쳐야 찾는다. "비번 몇자리요?" 로는 안내서의 "비밀번호 작성규칙" 이
# 1위로 올라오지 않고, "동의 안받고 쓸수있는" 으로는 보호법 제15조가 아예 안 걸린다.
# 문의는 구어체와 축약으로 오는데 문서는 법령 문투라서 어휘가 만나지 않는다.
# 이 사전은 그 틈을 메운다. 문의를 고치는 게 아니라 **검색어에만** 보탠다.
_ABBREV = {
    "비번": "비밀번호",
    "ISMS-P": "정보보호 및 개인정보보호 관리체계 인증",
    "ISMS": "정보보호 관리체계 인증",
    "CISO": "정보보호 최고책임자",
    "CPO": "개인정보보호 책임자",
    "안받고": "동의 없이",
    "안 받고": "동의 없이",
    "쓸수있": "수집 이용할 수 있",
    "쓸 수 있": "수집 이용할 수 있",
    "개인정보처리방침": "개인정보 처리방침",
    "과태료": "과태료 벌칙",
    "유출사고": "개인정보 유출 통지 신고",
}
# "결함" 은 일부러 넣지 않는다. 근거가 있어서 넣은 게 아니라 있을 법해서 넣었다가,
# "우리 회사가 결함 안 나온다고 확답해 달라" 는 **넘겨야 할** 문의에까지 그럴듯한 조항을
# 올려 주어 모델이 답하도록 유인했다. 검색을 도우려던 항목이 이관 판단을 망가뜨린 것이다.

# 문의에 적힌 인증기준 번호(3.1.1)와 조문 번호(제15조)
_NUM_IN_Q = re.compile(r"(?<!\d)\d\.\d{1,2}(?:\.\d{1,2})?(?!\d)|제\s?\d+조(?:의\s?\d+)?")


def normalize_query(query):
    """검색어를 문서 어휘로 편다.

    두 가지를 한다.
      1. 축약어·구어체를 문서 표현으로 바꿔 **덧붙인다**(지우지 않는다).
      2. 조항 번호가 적혀 있으면 그 조항의 제목을 덧붙인다.
         번호를 대고 묻는 문의는 검색할 필요가 없다 — 어느 조항인지 이미 알려 준 것이다.
    """
    extra = [v for k, v in _ABBREV.items() if k in query]

    for num in _NUM_IN_Q.findall(query):
        key = re.sub(r"\s", "", num)
        for c in all_chunks():
            if key in c["section"].replace(" ", ""):
                extra.append(c["section"].split(" > ")[-1])
                break

    return (query + " " + " ".join(extra)).strip() if extra else query


def search(query, sources=None, domains=None, top_k=4):
    """BM25 로 조각을 찾는다.

    sources/domains 를 주면 그 범위 안에서만 찾는다. 카테고리가 정해진 뒤에는
    범위를 좁혀야 엉뚱한 문서에서 근거를 끌어오지 않는다.
    """
    items, docs, lens, avg, postings, idf = _index()
    k1, b = 1.5, 0.75

    allowed = None
    if sources or domains:
        allowed = {i for i, c in enumerate(items)
                   if (not sources or c["source"] in sources)
                   and (not domains or c["domain"] in domains)}
        if not allowed:
            return []

    scores = defaultdict(float)
    for term, qf in Counter(_bigrams(normalize_query(query))).items():
        if term not in postings:
            continue
        w = idf[term]
        for i in postings[term]:
            if allowed is not None and i not in allowed:
                continue
            f = docs[i][term]
            scores[i] += w * f * (k1 + 1) / (f + k1 * (1 - b + b * lens[i] / avg))

    ranked = sorted(scores.items(), key=lambda kv: -kv[1])[:top_k]
    return [dict(items[i], score=round(s, 2)) for i, s in ranked if s > 0]


def excerpt(chunk, query, limit=MAX_CHUNK_CHARS):
    """긴 조각에서 질의와 가장 많이 겹치는 구간을 잘라 준다.

    앞에서부터 자르면 안 된다. 안내서 3.5.2 는 3,001자인데 정작 답인 "10일" 은
    2,614자 지점에 있다. 앞 1,200자만 주면 모델은 문서에 답이 없다고 판단하고
    엉뚱한 문서를 더 열거나, 근거가 있는데도 못 찾았다고 답한다.
    실제로 그렇게 틀리는 것을 보고 넣은 함수다.
    """
    text = chunk["text"]
    if len(text) <= limit:
        return text

    q = set(_bigrams(query))
    step = max(1, limit // 8)
    best_at, best_hit = 0, -1
    for start in range(0, len(text) - limit + step, step):
        hit = sum(1 for b in set(_bigrams(text[start:start + limit])) if b in q)
        if hit > best_hit:
            best_at, best_hit = start, hit

    head = "…(앞부분 생략) " if best_at > 0 else ""
    tail = " …(이하 생략)" if best_at + limit < len(text) else ""
    return head + text[best_at:best_at + limit] + tail


def render(chunk, query="", limit=MAX_CHUNK_CHARS):
    """조각 하나를 프롬프트에 넣을 형태로 만든다. 출처를 항상 앞에 붙인다."""
    return f"[{chunk['id']}] {chunk['section']}\n{excerpt(chunk, query, limit)}"


if __name__ == "__main__":
    items = all_chunks()
    print(f"조각 {len(items)}개")
    for src in SOURCE_NAMES:
        sub = [c for c in items if c["source"] == src]
        by = Counter(c["domain"] for c in sub)
        print(f"  {src:10s} {len(sub):4d}  {dict(by)}")
    print()
    for q in ["개인정보 수집 동의를 어떻게 받아야 하나요",
              "인증 심사 수수료",
              "비밀번호 관리 기준"]:
        print(f"\nQ: {q}")
        for c in search(q, top_k=3):
            print(f"   {c['score']:6.2f} [{c['id']}] {c['section'][:70]}")
