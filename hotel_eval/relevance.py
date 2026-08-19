"""relevance.py —— 维度 4：相关性

两条路：
  - 规则层（check_relevance_rules）：输出是否完全脱离输入（答非所问的硬判）。
  - judge 层（judge_relevance）：深度相关性（是否贴合用户情境/意图，含"权衡质量"）。
"""

from __future__ import annotations

from typing import List

from .schema import HotelInput, Issue, LLMOutput

DIM = "相关性"


def check_relevance_rules(inp: HotelInput, out: LLMOutput) -> List[Issue]:
    """答非所问硬判：输出是否一个输入酒店都没提、或没给出任何推荐。"""
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
            passed=False, detail="输出内容与输入候选酒店无交集",
            evidence=str(mentioned),
        ))
    return issues


def judge_relevance(inp: HotelInput, out: LLMOutput, judge_fn=None) -> List[Issue]:
    """深度相关性 judge 层：是否捕捉到用户情境、偏好偏移、权衡呈现。"""
    if judge_fn is None:
        return []
    res = judge_fn(
        dimension="相关性",
        payload={"input": _fmt_input(inp), "results": [r.name for r in out.results]},
    )
    if res is None:
        return []
    score = float(res.get("score", 0))
    return [Issue(
        dimension=DIM, check="相关·judge", layer="quality",
        passed=score >= 3, score=score,
        detail=res.get("evidence", ""), evidence=res.get("evidence", ""),
    )]


def _fmt_input(inp: HotelInput) -> str:
    return f"酒店列表={inp.hotels}, 日期={inp.date}, 人数={inp.guests}"
