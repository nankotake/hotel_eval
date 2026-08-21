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


def _to_dict(dc) -> dict:
    """dataclass -> dict，跳过值为 None / 空串 / 空列表 的字段，保持 JSON 文件干净。"""
    from dataclasses import fields, asdict

    out = {}
    for f in fields(dc):
        v = getattr(dc, f.name)
        if v is None or v == "" or v == [] or v == {}:
            continue
        out[f.name] = asdict(v) if hasattr(v, "__dataclass_fields__") else v
    return out


@dataclass
class HotelInput:
    """用户输入（入参）—— 被测 LLM 收到的请求。

    产品交互：用户在酒店列表里勾选若干酒店用于对比，没有自由文本输入。
    入参 = 选择的酒店 + 入住条件（天数/日期/人数），可选区域/预算。
    date/guests 未提供时置空/None，相关回显检查自动跳过。
    """

    hotels: List[str]  # 用户选择的酒店
    date: str = ""  # 入住日期（可选；空则跳过日期回显检查）
    guests: Optional[int] = None  # 人数（可选；None 则跳过人数回显检查）
    nights: int = 1  # 入住天数（晚数）
    region: Optional[str] = None  # 用户要求的区域偏好（可选，无则 None）
    budget: Optional[float] = None  # 用户预算（可选，无则 None）
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = _to_dict(self)
        d.pop("extra", None)  # extra 只存 case_id 关联，不入 input 序列化
        return d


@dataclass
class EvalReference:
    """参考信息（真值/基准）—— 评测方提供，用于比对 LLM 输出，与 LLM 输出无关。

    两类：酒店信息详情（事实库）+ 用户画像。
    用户画像是开放式描述（不是枚举值），评测时交给 judge 做语义匹配，
    不做关键词词典硬匹配。
    注意：这不是被测 LLM 的入参，别把它当输入；也不要从 LLM 输出里反推。
    """

    fact_db: Dict[str, HotelFact] = field(default_factory=dict)  # 酒店信息详情
    profile: List[str] = field(default_factory=list)  # 用户画像标签（结构化，可选）
    profile_text: str = ""  # 用户画像自由描述（开放式，judge 语义匹配用）
    profile_note: str = ""  # 用户画像说明（可选，数据文件里的 user_profile.note，保留用）

    def to_dict(self) -> dict:
        fact_db = {name: f.to_dict() for name, f in self.fact_db.items()}
        user_profile = {}
        if self.profile:
            user_profile["tags"] = self.profile
        if self.profile_text:
            user_profile["description"] = self.profile_text
        if self.profile_note:
            user_profile["note"] = self.profile_note
        d = {}
        if fact_db:
            d["fact_db"] = fact_db
        if user_profile:
            d["user_profile"] = user_profile
        return d


@dataclass
class HotelFact:
    """事实库中的一条酒店事实（对应数据库里的一行）。"""

    name: str
    region: str
    star: str
    price: float
    score: float
    facilities: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = _to_dict(self)
        d.pop("name", None)  # name 是 fact_db 的 map key，不重复写入字段
        return d


@dataclass
class Claim:
    """输出里的一条客观声称（用于事实查库比对）。"""

    hotel: str
    attribute: str  # price / score / facility / region / star ...
    value: Any
    source: str = ""  # 出自输出哪一段，便于定位

    def to_dict(self) -> dict:
        return _to_dict(self)


@dataclass
class RecommendedHotel:
    """推荐结果里的一条方案。"""

    rank: int
    name: str
    star_text: str = ""  # 星级文本，如 "*****"
    level_text: str = ""  # 档次文本，如 "经济型"
    price_text: str = ""  # 价格文本，如 "¥202起"
    reasons: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return _to_dict(self)


@dataclass
class LLMOutput:
    """从 LLM 原始输出抽取出的结构化视图（抽取逻辑见 extractor.py）。"""

    raw: str
    requirement_text: str = ""  # 需求理解段原文（用于回显/覆盖检查）
    analysis_text: str = ""  # 分析段原文（用于勾选覆盖/越界检查）
    dates: List[str] = field(default_factory=list)  # 输出里出现的所有日期
    requirement_star: Optional[str] = None  # 需求段声称的星级
    requirement_region: Optional[str] = None  # 需求段声称的区域
    requirement_guests: Optional[int] = None  # 需求段声称的人数
    requirement_hotels: List[str] = field(default_factory=list)  # 需求段回显的酒店（归一后匹配输入）
    analysis_hotels: List[str] = field(default_factory=list)  # 分析段提及的酒店
    analysis_claims: List[Claim] = field(default_factory=list)  # 分析段自动抽取的事实声称（价格等）
    results: List[RecommendedHotel] = field(default_factory=list)
    table: List[List[str]] = field(default_factory=list)  # 对比表行（每行是单元格列表）
    table_claims: List[Claim] = field(default_factory=list)  # 对比表自动抽取的声称（价格/评分）
    reason_claims: List[Claim] = field(default_factory=list)  # 方案块自动抽取的声称（价格/档次）


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
