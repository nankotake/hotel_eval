"""relevance.py —— 维度 4：相关性

数据分三类：用户输入（入参：天数/日期/人数/选择的酒店）、参考信息
（基准：酒店信息详情 + 用户画像）、评测对象（LLM 输出）。

相关性的两个来源：
  - 入参侧：输出是否紧扣用户选择的酒店集合（勾选集）
  - 参考侧：输出是否贴合参考画像（用户画像来自参考信息，不是 LLM 复述）

检查：
  1. check_relevance_rules  规则层硬判（gate）：答非所问——没给任何推荐、
                             或输出与勾选集毫无交集。
  2. check_audience_fit     受众匹配（quality）：参考画像 vs 推荐理由受众信号，
                             错位时捞样本（如"独自出行却推亲子家庭"）。
  3. judge_relevance        judge 层（quality）：紧扣勾选集 / 覆盖 / 对比依据 / 取舍。

注意：不要用 LLM 自己复述的"需求理解"当用户画像基准——那是被测对象的
一面之词，不是真值；真值只有参考信息（参考画像 + 事实库）。
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
    """从文本抽取用户画像标签（用于 LLM 复述/自检；参考画像以数据文件为准）。"""
    return [k for k, pats in USER_PROFILE.items() if any(p in text for p in pats)]


def extract_audience_signals(text: str) -> List[str]:
    """从推荐理由文本抽取受众标签。"""
    return [k for k, pats in AUDIENCE.items() if any(p in text for p in pats)]


def audience_mismatch(profile: List[str], audience: List[str]) -> List[str]:
    """受众信号里与画像不匹配的标签；画像为空时不判（返回空）。"""
    if not profile:
        return []
    return [a for a in audience if a not in profile]


def _audience_text(out: LLMOutput) -> str:
    """受众信号的来源 = 分析段 + 方案理由（LLM 对'酒店适合谁'的表述）。"""
    reasons = "\n".join(r for h in out.results for r in h.reasons)
    return (out.analysis_text or "") + "\n" + reasons


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


def check_audience_fit(profile: List[str], out: LLMOutput) -> List[Issue]:
    """受众匹配：参考画像（基准）vs 推荐理由受众信号，错位时作为软性信号（quality）。"""
    audience = extract_audience_signals(_audience_text(out))
    mismatch = audience_mismatch(profile, audience)

    issues: List[Issue] = []
    if mismatch:
        issues.append(Issue(
            dimension=DIM, check="相关·受众匹配", layer="quality", passed=False,
            detail=f"参考画像={profile}，推荐理由主打受众={mismatch}（可能情境错位，建议 judge 深评）",
            evidence=f"profile={profile} audience={audience}",
        ))
    return issues


def judge_relevance(inp: HotelInput, out: LLMOutput, profile: List[str], judge_fn=None) -> List[Issue]:
    """深度相关性 judge 层：紧扣勾选集 / 覆盖 / 对比依据 / 取舍 / 画像贴合。judge_fn 注入。"""
    if judge_fn is None:
        return []
    reasons = "\n".join(r for h in out.results for r in h.reasons)
    res = judge_fn(
        dimension="相关性",
        payload={
            "input": {"selected_hotels": inp.hotels, "date": inp.date, "guests": inp.guests},
            "user_profile": profile,  # 参考画像（基准），不是 LLM 复述
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
