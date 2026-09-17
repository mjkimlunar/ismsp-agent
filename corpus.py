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


def get(chunk_id):
    return next((c for c in all_chunks() if c["id"] == chunk_id), None)


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
    for term, qf in Counter(_bigrams(query)).items():
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


def render(chunk, limit=MAX_CHUNK_CHARS):
    """조각 하나를 프롬프트에 넣을 형태로 만든다. 출처를 항상 앞에 붙인다."""
    text = chunk["text"]
    if len(text) > limit:
        text = text[:limit] + " …(이하 생략)"
    return f"[{chunk['id']}] {chunk['section']}\n{text}"


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
