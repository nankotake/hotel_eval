"""relevance.py —— 维度 4：相关性

数据三分类：用户输入（入参：天数/日期/人数/选择的酒店）、参考信息
（基准：酒店信息详情 + 用户画像）、评测对象（LLM 输出）。

画像匹配是开放式语义判断：
  - 用户画像是自由描述（"单身""偏好四星""带娃"…），不是枚举值，
    关键词词典永远覆盖不全，所以不做确定性硬匹配。
  - 画像贴合与否交给 judge（LLM）语义判断：judge_relevance 的 payload
    带上参考画像（标签 + 自由描述），由 rubric 评估推荐理由是否贴合。

检查：
  1. check_relevance_rules  规则层硬判（gate）：答非所问——没给任何推荐、
                             或输出与勾选集毫无交集。（确定性部分）
  2. judge_relevance        judge 层（quality）：紧扣勾选集 / 覆盖 / 对比依据 /
                             取舍 / 画像贴合。（语义部分，含画像匹配）

注意：不要用 LLM 自己复述的"需求理解"当用户画像基准——那是被测对象的
一面之词，不是真值；真值只有参考信息（参考画像 + 事实库）。
"""

from __future__ import annotations

from typing import List

from .schema import HotelInput, Issue, LLMOutput

DIM = "相关性"


def check_relevance_rules(inp: HotelInput, out: LLMOutput) -> List[Issue]:
    """答非所问硬判：没给出任何推荐，或输出与勾选集毫无交集。"""
    issues: List[Issue] = []
    if not out.results:
        issues.append(Issue(
            dimension=DIM, check="相关·有无结果", layer="gate",
            passed=False, detail="输出未给出任何推荐结果",
        ))
        return issues

    in_set = set(inp.hotels)
    mentioned = set(out.analysis_hotels) | {r.name for r in out.results}
    if not (mentioned & in_set):
        issues.append(Issue(
            dimension=DIM, check="相关·答非所问", layer="gate",
            passed=False, detail="输出内容与勾选集无交集",
            evidence=str(mentioned),
        ))
    return issues


def judge_relevance(
    inp: HotelInput,
    out: LLMOutput,
    profile: List[str],
    profile_text: str,
    judge_fn=None,
) -> List[Issue]:
    """深度相关性 judge 层：紧扣勾选集 / 覆盖 / 对比依据 / 取舍 / 画像贴合。

    画像匹配是开放式语义判断：把参考画像（标签 + 自由描述）传给 judge，
    judge 判断推荐理由是否贴合，不做关键词词典硬匹配。
    """
    if judge_fn is None:
        return []
    reasons = "\n".join(r for h in out.results for r in h.reasons)
    res = judge_fn(
        dimension="相关性",
        payload={
            "input": {"selected_hotels": inp.hotels, "date": inp.date, "guests": inp.guests},
            # 参考画像（基准，开放式）：标签 + 自由描述，不是从 LLM 输出里抽的
            "user_profile": {"tags": profile, "description": profile_text},
            "results": [r.name for r in out.results],
            "reasons": reasons,
        },
    )
    if res is None:
        return []
    score = float(res.get("score", 0))
    return [Issue(
        dimension=DIM, check="相关·judge", layer="quality",
        passed=score >= 3, score=score,
        detail=res.get("evidence", ""), evidence=res.get("evidence", ""),
    )]
