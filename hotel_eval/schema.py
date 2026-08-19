"""schema.py —— 数据结构定义

评测的通用"语言"：输入、事实库、LLM 输出、检查结果。
所有维度模块都读写这些结构，保证可组合、可分层。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


def normalize_name(s: str) -> str:
    """归一化酒店名：去空格、全角括号转半角，用于跨段/跨库匹配（容忍粘贴的排版差异）。"""
    return (
        s.replace(" ", "")
        .replace("\u3000", "")
        .replace("（", "(")
        .replace("）", ")")
    )


@dataclass
class HotelInput:
    """被测系统的输入（用户实际只给了：酒店列表、入住日期、人数）。"""

    hotels: List[str]
    date: str  # 入住日期
    guests: int
    nights: int = 1  # 晚数
    region: Optional[str] = None  # 若话术里明确提到区域偏好，可填
    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass
class HotelFact:
    """事实库中的一条酒店事实（对应数据库里的一行）。"""

    name: str
    region: str
    star: str
    price: float
    score: float
    facilities: List[str] = field(default_factory=list)


@dataclass
class Claim:
    """输出里的一条客观声称（用于事实查库比对）。"""

    hotel: str
    attribute: str  # price / score / facility / region / star ...
    value: Any
    source: str = ""  # 出自输出哪一段，便于定位


@dataclass
class RecommendedHotel:
    """推荐结果里的一条方案。"""

    rank: int
    name: str
    star_text: str = ""  # 星级文本，如 "*****"
    level_text: str = ""  # 档次文本，如 "经济型"
    price_text: str = ""  # 价格文本，如 "¥202起"
    reasons: List[str] = field(default_factory=list)


@dataclass
class LLMOutput:
    """从 LLM 原始输出抽取出的结构化视图（抽取逻辑见 extractor.py）。"""

    raw: str
    requirement_text: str = ""  # 需求理解段原文（用于画像抽取）
    analysis_text: str = ""  # 分析段原文（用于受众信号抽取）
    dates: List[str] = field(default_factory=list)  # 输出里出现的所有日期
    requirement_star: Optional[str] = None  # 需求段声称的星级
    requirement_region: Optional[str] = None  # 需求段声称的区域
    requirement_guests: Optional[int] = None  # 需求段声称的人数
    requirement_hotels: List[str] = field(default_factory=list)  # 需求段回显的酒店（归一后匹配输入）
    analysis_hotels: List[str] = field(default_factory=list)  # 分析段提及的酒店
    analysis_claims: List[Claim] = field(default_factory=list)  # 分析段事实声称
    results: List[RecommendedHotel] = field(default_factory=list)
    table: List[Dict[str, str]] = field(default_factory=list)  # 对比表行
    reason_claims: List[Claim] = field(default_factory=list)  # 理由段事实声称


@dataclass
class Issue:
    """一条检查发现的问题。"""

    dimension: str  # 一致性 / 安全性 / 语义 / 相关性
    check: str  # 具体检查名
    layer: str  # gate(硬门禁) / safety(安全层) / quality(软性层)
    passed: bool
    detail: str
    evidence: str = ""


@dataclass
class CheckResult:
    """一个维度（或一个子检查）的汇总结果。"""

    dimension: str
    check: str
    layer: str
    passed: bool
    score: Optional[float] = None
    issues: List[Issue] = field(default_factory=list)
    note: str = ""
