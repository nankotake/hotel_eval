"""relevance.py —— 维度 4：相关性

三层：
  1. check_relevance_rules  规则层：答非所问的硬判（gate）。
  2. check_audience_fit     受众匹配：需求画像 vs 推荐理由受众信号，软性信号（quality）。
  3. judge_relevance        judge 层：深度相关性（情境/受众/权衡）。

"独自出行却推亲子家庭"这类问题：确定性层负责"把画像和受众信号抽出来、发现错位并捞样本"，
深度判断交给 judge（见 judge_relevance / prompts 的相关性 rubric）。
"""

from __future__ import annotations

from typing import List

from .schema import HotelInput, Issue, LLMOutput

DIM = "相关性"

# 需求画像 / 推荐理由受众信号（确定性词典，可扩展）
USER_PROFILE = {
    "独自出行": ["独自", "单独", "一个人", "一人"],
    "亲子家庭": ["亲子", "带孩子", "孩子", "儿童", "家庭", "宝宝", "小朋友"],
    "情侣出行": ["情侣", "夫妻", "蜜月", "二人世界"],
    "商务出差": ["商务", "出差", "会议", "办公"],
}
AUDIENCE = {
    "亲子家庭": ["亲子", "家庭", "儿童", "宝宝", "小朋友", "带孩子", "孩子"],
    "商务出差": ["商务", "出差", "会议"],
    "情侣出行": ["情侣", "蜜月"],
    "独自出行": ["独自", "单人", "一个人"],
}


def extract_user_profile(text: str) -> List[str]:
    """从需求文本抽取用户画像标签。"""
    return [k for k, pats in USER_PROFILE.items() if any(p in text for p in pats)]


def extract_audience_signals(text: str) -> List[str]:
    """从推荐理由文本抽取受众标签。"""
    return [k for k, pats in AUDIENCE.items() if any(p in text for p in pats)]


def _audience_text(out: LLMOutput) -> str:
    """受众信号的来源 = 分析段 + 方案理由（LLM 对'酒店适合谁'的表述）。"""
    reasons = "\n".join(r for h in out.results for r in h.reasons)
    return (out.analysis_text or "") + "\n" + reasons


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


def check_audience_fit(inp: HotelInput, out: LLMOutput) -> List[Issue]:
    """受众匹配：需求画像 vs 推荐理由受众信号，错位时作为软性信号（quality）。"""
    profile = extract_user_profile(out.requirement_text)
    audience = extract_audience_signals(_audience_text(out))

    issues: List[Issue] = []
    if profile and audience:
        mismatch = [a for a in audience if a not in profile]
        if mismatch:
            issues.append(Issue(
                dimension=DIM, check="相关·受众匹配", layer="quality", passed=False,
                detail=f"需求画像={profile}，推荐理由主打受众={mismatch}（可能情境错位，建议 judge 深评）",
                evidence=f"profile={profile} audience={audience}",
            ))
    return issues


def judge_relevance(inp: HotelInput, out: LLMOutput, judge_fn=None) -> List[Issue]:
    """深度相关性 judge 层：情境/受众/权衡。judge_fn 由 judge.judge_structured 注入。"""
    if judge_fn is None:
        return []
    res = judge_fn(
        dimension="相关性",
        payload={
            "input": {"hotels": inp.hotels, "date": inp.date, "guests": inp.guests},
            "user_profile": extract_user_profile(out.requirement_text),
            "results": [r.name for r in out.results],
            "reasons_audience": extract_audience_signals(_audience_text(out)),
            "reasons": _audience_text(out),
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
