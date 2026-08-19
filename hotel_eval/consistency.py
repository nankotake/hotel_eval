"""consistency.py —— 维度 1：一致性（确定性 floor 层，不问模型）

三个子维度：
  1. check_input_output  输入输出一致性（回显）：输出是否忠于输入
  2. check_context       上下文一致性（内部自洽）：输出各段之间是否矛盾
  3. check_factual       事实一致性（查库）：客观声称是否与事实库一致

说明：
  - 酒店名比较一律用 normalize_name()，容忍粘贴的排版差异。
  - 日期检查区分"入住/离店"：离店 = 入住 + 晚数，是合法日期，不算违规。
  - "分析了 N 家、只推荐其中 2 家"是正常行为；只抓"推荐了但根本没分析过"的。
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from .schema import Claim, HotelFact, HotelInput, Issue, LLMOutput, normalize_name

DIM = "一致性"


def _issue(check: str, layer: str, passed: bool, detail: str, evidence: str = "") -> Issue:
    return Issue(dimension=DIM, check=check, layer=layer, passed=passed, detail=detail, evidence=evidence)


def _allowed_dates(inp: HotelInput) -> set:
    """一次行程的合法日期 = {入住日, 离店日}。"""
    try:
        d = datetime.strptime(inp.date, "%Y-%m-%d")
        checkout = (d + timedelta(days=inp.nights)).strftime("%Y-%m-%d")
        return {inp.date, checkout}
    except ValueError:
        return {inp.date}


# --------------------------------------------------------------------------- #
# 1. 输入输出一致性（回显）
# --------------------------------------------------------------------------- #

def check_input_output(inp: HotelInput, out: LLMOutput) -> List[Issue]:
    issues: List[Issue] = []
    in_norm = {normalize_name(h) for h in inp.hotels}

    # 1) 推荐结果必须来自输入候选列表（推荐了列表外 = 幻觉）
    for r in out.results:
        if r.name and normalize_name(r.name) not in in_norm:
            issues.append(_issue(
                "输入输出·酒店回显", "gate", False,
                f"推荐了输入列表之外的酒店: {r.name}",
                evidence=f"方案{r.rank}",
            ))

    # 2) 需求段是否完整回显了输入酒店列表
    req_norm = {normalize_name(h) for h in out.requirement_hotels}
    missing = [h for h in inp.hotels if normalize_name(h) not in req_norm]
    if missing:
        issues.append(_issue(
            "输入输出·需求酒店回显", "gate", False,
            f"需求段遗漏了输入酒店: {missing}",
            evidence=str(out.requirement_hotels),
        ))

    # 3) 输出里的日期必须是入住日或离店日（离店 = 入住 + 晚数）
    allowed = _allowed_dates(inp)
    bad = [d for d in out.dates if d not in allowed]
    if bad:
        issues.append(_issue(
            "输入输出·日期回显", "gate", False,
            f"输出日期 {bad} 既非入住日也非离店日（入住 {inp.date}，{inp.nights} 晚）",
            evidence=str(out.dates),
        ))

    # 4) 人数回显
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

    # 1) 需求段星级 vs 结果段档次（需求说五星，却推经济型）
    if out.requirement_star == "五星":
        for r in out.results:
            if r.level_text and "经济" in r.level_text:
                issues.append(_issue(
                    "上下文·星级自洽", "gate", False,
                    f"需求段声称'五星'，但推荐了'经济型'酒店: {r.name}",
                    evidence=r.level_text,
                ))

    # 2) 结果段 vs 分析段：推荐了但分析段根本没分析过
    analyzed_norm = {normalize_name(h) for h in out.analysis_hotels}
    if analyzed_norm:
        for r in out.results:
            if normalize_name(r.name) not in analyzed_norm:
                issues.append(_issue(
                    "上下文·过程结果一致", "gate", False,
                    f"推荐了但分析段未分析过的酒店: {r.name}",
                    evidence=str(out.analysis_hotels),
                ))

    # 3) 星标 vs 数值评分（软性信号，不做硬门禁）：多家同星级但数值评分差大
    five_star = out.raw.count("★★★★★") + out.raw.count("*****")
    scores = sorted(set(re.findall(r"(\d\.\d)\s*(?:超棒|好|棒|差)?", out.raw)))
    if five_star >= 2 and len(scores) > 1:
        issues.append(_issue(
            "上下文·星标数值一致", "quality", False,
            f"{five_star} 处标五星，但数值评分出现 {scores} 不同值（推荐指数与评分可能需人工确认）",
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
    n = normalize_name(name)
    for k, v in fact_db.items():
        if normalize_name(k) == n:
            return v
    for k, v in fact_db.items():
        if normalize_name(k)[:6] in n or n[:6] in normalize_name(k):
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
