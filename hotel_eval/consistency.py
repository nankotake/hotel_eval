"""consistency.py —— 维度 1：一致性（确定性 floor 层，不问模型）

三个子维度：
  1. check_input_output  输入输出一致性（回显）：输出是否忠于输入
  2. check_context       上下文一致性（内部自洽）：输出各段之间是否矛盾
  3. check_factual       事实一致性（查库）：客观声称是否与事实库一致

这一层是"硬门禁"，发现违规即整单 fail，不需要 LLM。
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional

from .schema import Claim, HotelFact, HotelInput, Issue, LLMOutput

DIM = "一致性"


def _issue(check: str, layer: str, passed: bool, detail: str, evidence: str = "") -> Issue:
    return Issue(dimension=DIM, check=check, layer=layer, passed=passed, detail=detail, evidence=evidence)


# --------------------------------------------------------------------------- #
# 1. 输入输出一致性（回显）
# --------------------------------------------------------------------------- #

def check_input_output(inp: HotelInput, out: LLMOutput) -> List[Issue]:
    issues: List[Issue] = []
    in_set = set(inp.hotels)

    # 1) 推荐结果必须来自输入候选列表（推荐了列表外 = 幻觉）
    for r in out.results:
        if r.name and r.name not in in_set:
            issues.append(_issue(
                "输入输出·酒店回显", "gate", False,
                f"推荐了输入列表之外的酒店: {r.name}",
                evidence=f"方案{r.rank}",
            ))

    # 2) 输出里的日期都必须等于输入日期
    if out.dates:
        bad = [d for d in out.dates if d != inp.date]
        if bad:
            issues.append(_issue(
                "输入输出·日期回显", "gate", False,
                f"输出日期 {bad} 与输入日期 {inp.date} 不一致",
                evidence=str(out.dates),
            ))

    # 3) 人数回显
    if out.requirement_guests is not None and out.requirement_guests != inp.guests:
        issues.append(_issue(
            "输入输出·人数回显", "gate", False,
            f"需求段人数 {out.requirement_guests} 与输入人数 {inp.guests} 不一致",
        ))

    return issues


# --------------------------------------------------------------------------- #
# 2. 上下文一致性（内部自洽）
# --------------------------------------------------------------------------- #

def check_context(inp: HotelInput, out: LLMOutput) -> List[Issue]:
    issues: List[Issue] = []

    # 1) 输出内部日期自相矛盾
    distinct = list(dict.fromkeys(out.dates))
    if len(distinct) > 1:
        issues.append(_issue(
            "上下文·日期自洽", "gate", False,
            f"输出内出现多个不一致日期: {distinct}",
            evidence=str(distinct),
        ))

    # 2) 需求段星级 vs 结果段档次
    if out.requirement_star == "五星":
        for r in out.results:
            if r.level_text and "经济" in r.level_text:
                issues.append(_issue(
                    "上下文·星级自洽", "gate", False,
                    f"需求段声称'五星'，但推荐了'经济型'酒店: {r.name}",
                    evidence=r.level_text,
                ))

    # 3) 分析段 vs 结果段：分析讲的酒店 ≠ 结果推荐的酒店
    result_names = {r.name for r in out.results}
    if out.analysis_hotels and result_names:
        analyzed_not_recommended = [h for h in out.analysis_hotels if h not in result_names]
        recommended_not_analyzed = [n for n in result_names if n not in out.analysis_hotels]
        if analyzed_not_recommended:
            issues.append(_issue(
                "上下文·过程结果一致", "gate", False,
                f"分析段详述但最终未推荐: {analyzed_not_recommended}",
                evidence=str(out.analysis_hotels),
            ))
        if recommended_not_analyzed:
            issues.append(_issue(
                "上下文·过程结果一致", "gate", False,
                f"推荐了但分析段未提及: {recommended_not_analyzed}",
                evidence=str(recommended_not_analyzed),
            ))

    # 4) 星标 vs 数值评分：多家酒店都标五星，但数值评分不同
    five_star = out.raw.count("★★★★★")
    scores = re.findall(r"(\d\.\d)\s*(?:超棒|好|棒|差)?", out.raw)
    if five_star >= 2 and len(set(scores)) > 1:
        issues.append(_issue(
            "上下文·星标数值一致", "gate", False,
            f"{five_star} 处标五星，但数值评分出现 {sorted(set(scores))} 不同值",
            evidence="对比表/推荐指数",
        ))

    return issues


# --------------------------------------------------------------------------- #
# 3. 事实一致性（查库）
# --------------------------------------------------------------------------- #

def check_factual(fact_db: Dict[str, HotelFact], claims: List[Claim]) -> List[Issue]:
    """把输出里的客观声称逐条与事实库比对。fact_db key 为酒店名。"""
    issues: List[Issue] = []
    for c in claims:
        fact = _find_fact(fact_db, c.hotel)
        if fact is None:
            issues.append(_issue(
                "事实·酒店存在性", "gate", False,
                f"声称涉及的酒店不在事实库: {c.hotel}",
                evidence=c.source,
            ))
            continue
        ok, detail = _verify(fact, c)
        if not ok:
            issues.append(_issue(
                "事实·声称核对", "gate", False,
                detail,
                evidence=c.source,
            ))
    return issues


def _find_fact(fact_db: Dict[str, HotelFact], name: str) -> Optional[HotelFact]:
    if name in fact_db:
        return fact_db[name]
    for k, v in fact_db.items():
        if name[:6] in k or k[:6] in name:
            return v
    return None


def _verify(fact: HotelFact, c: Claim):
    attr = c.attribute
    if attr == "price":
        ok = isinstance(c.value, (int, float)) and abs(float(c.value) - fact.price) < 1e-6
        return ok, f"{c.hotel} 价格声称 {c.value}，事实库为 {fact.price}"
    if attr == "score":
        ok = isinstance(c.value, (int, float)) and abs(float(c.value) - fact.score) < 1e-6
        return ok, f"{c.hotel} 评分声称 {c.value}，事实库为 {fact.score}"
    if attr == "region":
        ok = c.value == fact.region
        return ok, f"{c.hotel} 区域声称 {c.value}，事实库为 {fact.region}"
    if attr == "star":
        ok = c.value == fact.star
        return ok, f"{c.hotel} 档次声称 {c.value}，事实库为 {fact.star}"
    if attr == "facility":
        ok = c.value in fact.facilities
        return ok, f"{c.hotel} 设施声称 '{c.value}'，事实库设施为 {fact.facilities}"
    return True, f"未支持的属性 {attr}，跳过核对"
