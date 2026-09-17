# -*- coding: utf-8 -*-
"""채점기가 제대로 재고 있는지 검사한다.  `python check_scorer.py`

지표를 믿으려면 지표부터 검사해야 한다. 평가셋의 모든 문항에는 두 개의 답이 붙어 있다.

  reference — 문서 내용만으로 쓴 모범답안. 채점기는 **반드시 통과**시켜야 한다.
              여기서 떨어지면 필수 사실을 너무 좁게 적었다는 뜻이다(거짓 실패).
  trap      — 그럴듯하지만 문서에 근거가 없는 답. 채점기는 **반드시 잡아**야 한다.
              여기서 통과하면 금지 표현이 허술하다는 뜻이다(거짓 통과).

모델을 부르지 않으므로 공짜고 결과가 항상 같다.
"""
from evaluate import load_cases, score_answer, score_tools


def main():
    cases = load_cases(None)
    false_fail, false_pass, tool_bad = [], [], []

    for c in cases:
        ok, why = score_answer(c, c["reference"], escalated=c["escalate"])
        if not ok:
            false_fail.append((c["id"], why))

        ok, _ = score_answer(c, c["trap"], escalated=False)
        if ok:
            false_pass.append(c["id"])

        # 기대 도구 집합이 그 카테고리에서 부를 수 있는 도구인지
        from context import allowed_tools
        allowed = set(allowed_tools(c["route"]))
        bad = [t for t in c["expect_tools"] if t not in allowed]
        if bad:
            tool_bad.append((c["id"], bad, c["route"]))

    print(f"평가셋 {len(cases)}건 검사\n")

    print(f"거짓 실패 (모범답안을 떨어뜨림)  {len(false_fail)}건")
    for cid, why in false_fail:
        print(f"    {cid}  {why}")

    print(f"\n거짓 통과 (함정답안을 통과시킴)  {len(false_pass)}건")
    for cid in false_pass:
        print(f"    {cid}")

    print(f"\n기대 도구가 카테고리에 없는 문항  {len(tool_bad)}건")
    for cid, bad, route in tool_bad:
        print(f"    {cid}  {bad} 는 {route} 에서 부를 수 없다")

    bad_total = len(false_fail) + len(false_pass) + len(tool_bad)
    print(f"\n{'채점기 이상 없음' if not bad_total else f'고칠 곳 {bad_total}군데'}")
    return bad_total


if __name__ == "__main__":
    raise SystemExit(1 if main() else 0)
