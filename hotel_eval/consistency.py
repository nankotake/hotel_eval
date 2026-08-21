"""consistency.py —— 维度 1：一致性（确定性 floor 层，不问模型）

四个子维度：
  1. check_input_output       输入输出一致性（回显）：输出是否忠于入参（选择的酒店/日期/人数）
  2. check_context            上下文一致性（内部自洽）：输出各段之间是否矛盾
  3. check_factual            事实一致性（查库）：客观声称是否与参考信息（事实库）一致
  4. check_selection_coverage 勾选覆盖：是否覆盖入参里选择的每家、有没有越界对比没选的

说明：
  - 酒店名比较一律用 normalize_name()，容忍粘贴的排版差异。
  - 日期检查区分"入住/离店"：离店 = 入住 + 晚数，是合法日期，不算违规。
  - "分析了 N 家、只推荐其中 2 家"是正常行为；只抓"推荐了但根本没分析过"的。
  - 入参（天数/日期/人数/选择酒店）≠ 参考信息（酒店详情/用户画像），别混。
  - 用户画像是开放式描述，不做关键词硬匹配（画像贴合交给 judge，见 relevance.py）。
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
    """输入输出一致性：输出是否忠于输入。输入 = 用户勾选的对比酒店集合
    （date/guests 是可选行程上下文，没提供就跳过对应检查）。"""
    issues: List[Issue] = []
    in_norm = {normalize_name(h) for h in inp.hotels}

    # 1) 推荐结果必须来自勾选集（推荐了勾选集外 = 幻觉）
    for r in out.results:
        if r.name and normalize_name(r.name) not in in_norm:
            issues.append(_issue(
                "输入输出·酒店回显", "gate", False,
                f"推荐了勾选集之外的酒店: {r.name}",
                evidence=f"方案{r.rank}",
            ))

    # 2) 需求段是否完整回显了勾选集
    req_norm = {normalize_name(h) for h in out.requirement_hotels}
    missing = [h for h in inp.hotels if normalize_name(h) not in req_norm]
    if missing:
        issues.append(_issue(
            "输入输出·需求酒店回显", "gate", False,
            f"需求段遗漏了勾选酒店: {missing}",
            evidence=str(out.requirement_hotels),
        ))

    # 3) 日期回显（仅当行程上下文提供了入住日期）
    if inp.date:
        allowed = _allowed_dates(inp)
        bad = [d for d in out.dates if d not in allowed]
        if bad:
            issues.append(_issue(
                "输入输出·日期回显", "gate", False,
                f"输出日期 {bad} 既非入住日也非离店日（入住 {inp.date}，{inp.nights} 晚）",
                evidence=str(out.dates),
            ))

    # 4) 人数回显（仅当行程上下文提供了人数）
    if inp.guests is not None and out.requirement_guests is not None \
            and out.requirement_guests != inp.guests:
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


# --------------------------------------------------------------------------- #
# 4. 勾选覆盖（输入 = 用户勾选的对比酒店集合）
# --------------------------------------------------------------------------- #

# 分析段里"形似酒店名"的实体（启发式：xxx酒店/饭店/宾馆），用于抓"对比了没勾选的酒店"
_HOTEL_NAME_RE = re.compile(r"[\u4e00-\u9fffA-Za-z0-9（）()·]{2,24}?(?:酒店|饭店|宾馆)")
# 泛指/类型词，避免把"这家酒店""经济型酒店"当成越界对比
_STRAY_SKIP_PREFIX = ("这家", "那家", "该", "本", "此", "全", "各", "某", "每", "一家", "两家")
_TYPE_HOTELS = {"经济型酒店", "舒适型酒店", "豪华型酒店", "商务型酒店",
                "快捷型酒店", "精品型酒店", "度假型酒店", "主题型酒店"}


def _core_name(name: str) -> str:
    """酒店短名（去掉括号后缀），如 '季朵酒店'；用于跨段/跨库匹配。"""
    return normalize_name(name).split("(")[0]


def _selection_mentions(out: LLMOutput, hotels: List[str]) -> set:
    """输出里实际"提到"了哪些勾选酒店（分析段/推荐结果/对比表表头）。

    容忍三种写法：全名（含括号后缀）、短名（去括号后缀）、截断名（表头 ...）。
    """
    mentioned = set()
    texts = [out.analysis_text or ""]
    texts += [r.name for r in out.results]
    # 对比表表头行（酒店名常被截断加 ...，用前缀匹配）
    for line in (out.raw or "").splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 2 and cells[0] in ("酒店", "酒店名"):
            texts.append(" ".join(cells[1:]))
    for h in hotels:
        hn = normalize_name(h)
        core = _core_name(h)
        for t in texts:
            tn = normalize_name(t)
            if not tn:
                continue
            if hn in tn or core in tn or (len(hn) >= 6 and hn[:6] in tn):
                mentioned.add(h)
                break
    return mentioned


def check_selection_coverage(inp: HotelInput, out: LLMOutput) -> List[Issue]:
    """勾选覆盖（gate）：用户勾选了 N 家做对比，输出必须覆盖每家，且不能对比没勾选的。"""
    issues: List[Issue] = []
    if not inp.hotels:
        return issues

    # 1) 覆盖：勾选了但输出（分析/推荐/表头）完全没提到的
    mentioned = _selection_mentions(out, inp.hotels)
    missing = [h for h in inp.hotels if h not in mentioned]
    if missing:
        issues.append(_issue(
            "勾选·覆盖", "gate", False,
            f"用户勾选 {len(inp.hotels)} 家做对比，输出未覆盖: {missing}",
            evidence=f"mentioned={sorted(mentioned)}",
        ))

    # 2) 越界：分析段出现了勾选集之外的酒店（对比了用户没选的 = 幻觉）
    #    启发式抽取 + 泛指/类型词过滤；命中即捞样本，误报由人工复核。
    seg = re.sub(r"\s+", "", out.analysis_text or "")  # 去空白，容忍粘贴换行
    seg = re.sub(r"^酒店分析(完成)?", "", seg)  # 剥掉段首标题（"酒店分析完成"）
    stray: List[str] = []
    for m in _HOTEL_NAME_RE.finditer(seg):
        cand = m.group(0)
        if cand.startswith(_STRAY_SKIP_PREFIX):
            continue
        cn = normalize_name(cand)
        if any(t in cn for t in _TYPE_HOTELS):  # "新开业经济型酒店" 只是类型描述，不是酒店名
            continue
        # 命中勾选集（全名或短名，容忍前面带"不如/是"等动词前缀）
        if any(_core_name(h) in cn or cn in _core_name(h) for h in inp.hotels):
            continue
        if cn not in [normalize_name(s) for s in stray]:
            stray.append(cand)
    if stray:
        issues.append(_issue(
            "勾选·越界对比", "gate", False,
            f"分析段对比了用户未勾选的酒店: {stray}",
            evidence="酒店分析段",
        ))

    return issues

