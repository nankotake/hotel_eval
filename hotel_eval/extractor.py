"""extractor.py —— 把 LLM 原始输出拆成结构化字段（LLMOutput）。

说明：
  - 生产系统里，最好让被测系统直接输出结构化 JSON，本模块的 parse 只做"校验 + 归一化"。
  - 这里提供一套针对"文本渲染输出"的正则解析，作为 demo 级实现，用于跑通评测链路。
  - 所有跨段/跨库的酒店名匹配都用 normalize_name()，容忍粘贴时的空格/全半角括号差异。

声称（claim）自动抽取（方式 2：确定性规则）：
  - 结构化部分可靠抽取：对比表 → 价格/评分；方案块 → 价格/档次；分析段 → 价格（N元起）
  - 自由文本里的其他声称（如"3公里内有300家餐厅"）不做启发式，留给 NLI 模型 / LLM
    抽取（方式 3/4），或由调用方手工补充（llm_outputs.json 的 claims 字段）
"""

from __future__ import annotations

import re
from typing import List

from .schema import Claim, HotelInput, LLMOutput, RecommendedHotel, normalize_name

_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}|\d{1,2}月\d{1,2}日")
_GUESTS_RE = re.compile(r"(\d+)\s*(?:人|位|名)(?!晚|星|元|家|间)")
_STAR_RE = re.compile(r"(五星|四星|三星|经济型|舒适型|豪华型)")
_LEVEL_RE = re.compile(r"(舒适型|经济型|豪华型|五星|四星|三星)\s*$")
_REGION_RE = re.compile(r"(徐汇区|浦东新区|宝山区|静安区|黄浦区|长宁区|杨浦区|虹口区|闵行区|松江区|嘉定区|青浦区|奉贤区|金山区)")
_PRICE_RE = re.compile(r"[¥￥]?\s*(\d+)\s*元?起")
_CN_NUM = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}


def extract_dates(text: str) -> List[str]:
    return list(dict.fromkeys(_DATE_RE.findall(text)))


def extract_requirement(text: str) -> dict:
    """从需求理解段抽取 星级/区域/人数（尽力而为）。"""
    seg = _segment(text, "需求理解")
    guests = _int(_match_first(_GUESTS_RE, seg))
    if guests is None and re.search(r"独自|单独|一人|1人", seg):
        guests = 1
    return {
        "requirement_star": _match_first(_STAR_RE, seg) or None,
        "requirement_region": _match_first(_REGION_RE, seg) or None,
        "requirement_guests": guests,
    }


def extract_requirement_hotels(text: str, input_hotels: List[str]) -> List[str]:
    """需求段回显了哪些输入酒店（归一化子串匹配）。"""
    seg_norm = normalize_name(_segment(text, "需求理解"))
    return [h for h in input_hotels if normalize_name(h) in seg_norm]


def extract_analysis_hotels(text: str, input_hotels: List[str]) -> List[str]:
    """分析段里提及的、且能匹配到候选列表的酒店名。"""
    seg_norm = normalize_name(_segment(text, "酒店分析"))
    return [h for h in input_hotels if normalize_name(h) in seg_norm]


def extract_results(text: str) -> List[RecommendedHotel]:
    """抽取 方案一/二 块：酒店名、档次、价格、星级、理由。"""
    results: List[RecommendedHotel] = []
    blocks = re.split(r"方案\s*([一二三四五六七八九十\d]+)\s*[·|｜]?\s*[^\n]*", text)
    for i in range(1, len(blocks), 2):
        rank = _cn_num(blocks[i])
        body = blocks[i + 1] if i + 1 < len(blocks) else ""
        name = _first_hotel_name(body)
        if not name:
            continue
        results.append(
            RecommendedHotel(
                rank=rank,
                name=name,
                star_text=_match_first(r"[★☆*]{3,}", body),
                level_text=_match_first(_STAR_RE, body) or "",
                price_text=_match_first(_PRICE_RE, body) or "",
                reasons=_extract_reasons(body),
            )
        )
    return results


def extract_table(text: str) -> List[list]:
    """抽取 markdown 对比表行（尽力而为）。"""
    rows: List[list] = []
    for line in text.splitlines():
        if "|" not in line:
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if not cells or set("".join(cells)) <= set("-| "):
            continue
        rows.append(cells)
    return rows


# --------------------------------------------------------------------------- #
# 声称自动抽取（确定性规则，方式 2）
# --------------------------------------------------------------------------- #

def extract_analysis_claims(text: str, input_hotels: List[str]) -> List[Claim]:
    """分析段 → 价格声称（N元起）。

    按行定位到对应酒店后再抽，避免跨段误抽；分析段自由文本的其他声称
    （设施/评分等）不做启发式，留给 NLI/LLM 抽取或手工补充。
    """
    claims: List[Claim] = []
    seg = _segment(text, "酒店分析")
    lines = [re.sub(r"\s+", "", ln) for ln in seg.splitlines()]
    for h in input_hotels:
        core = _core_name(h)
        for ln in lines:
            if core in ln:
                m = re.search(r"(\d+)\s*元起", ln)
                if m:
                    claims.append(Claim(hotel=h, attribute="price", value=int(m.group(1)), source="分析段"))
                break
    return claims


def extract_result_claims(results: List[RecommendedHotel]) -> List[Claim]:
    """方案块 → 价格/档次声称（price_text 已抽成纯数字，level_text 如 经济型/舒适型）。"""
    claims: List[Claim] = []
    for r in results:
        if r.price_text and r.price_text.isdigit():
            claims.append(Claim(hotel=r.name, attribute="price", value=int(r.price_text), source=f"方案{r.rank}"))
        if r.level_text in ("舒适型", "经济型", "豪华型"):
            claims.append(Claim(hotel=r.name, attribute="star", value=r.level_text, source=f"方案{r.rank}"))
    return claims


def extract_table_claims(table: List[list], input_hotels: List[str]) -> List[Claim]:
    """对比表 → 价格/评分声称。表头酒店名可能截断（"季朵酒店（上海国际旅游度假..."），
    用全名/短名/前缀匹配回输入酒店。"""
    claims: List[Claim] = []
    if not table:
        return claims
    header = table[0]
    if not header or header[0].strip() != "酒店":
        return claims
    col_hotels = [_match_input_hotel(cell, input_hotels) for cell in header[1:]]
    for row in table[1:]:
        if len(row) < 2:
            continue
        field = row[0].strip()
        for ci, cell in enumerate(row[1:], start=1):
            hotel = col_hotels[ci - 1] if ci - 1 < len(col_hotels) else None
            if not hotel or not cell:
                continue
            if field == "价格":
                m = _PRICE_RE.search(cell)
                if m:
                    claims.append(Claim(hotel=hotel, attribute="price", value=int(m.group(1)), source="对比表"))
            elif field == "评分":
                m = re.search(r"(\d(?:\.\d)?)", cell)
                if m:
                    claims.append(Claim(hotel=hotel, attribute="score", value=float(m.group(1)), source="对比表"))
    return claims


def parse_llm_output(raw: str, input_hotels: List[str]) -> LLMOutput:
    out = LLMOutput(raw=raw)
    out.requirement_text = _segment(raw, "需求理解")
    out.analysis_text = _segment(raw, "酒店分析")
    out.dates = extract_dates(raw)
    req = extract_requirement(raw)
    out.requirement_star = req["requirement_star"]
    out.requirement_region = req["requirement_region"]
    out.requirement_guests = req["requirement_guests"]
    out.requirement_hotels = extract_requirement_hotels(raw, input_hotels)
    out.analysis_hotels = extract_analysis_hotels(raw, input_hotels)
    out.results = extract_results(raw)
    out.table = extract_table(raw)
    # 声称自动抽取：对比表（价格/评分）+ 方案块（价格/档次）+ 分析段（价格）
    out.table_claims = extract_table_claims(out.table, input_hotels)
    out.reason_claims = extract_result_claims(out.results)
    out.analysis_claims = extract_analysis_claims(raw, input_hotels)
    return out


# --------------------------------------------------------------------------- #
# 内部工具
# --------------------------------------------------------------------------- #

def _core_name(name: str) -> str:
    """酒店短名（去掉括号后缀），如 '季朵酒店'；用于跨段/跨库匹配。"""
    return normalize_name(name).split("(")[0]


def _match_input_hotel(cell: str, input_hotels: List[str]):
    """表头单元格（可能截断成前缀 / 只写短名）匹配到哪个输入酒店；匹配不到返回 None。"""
    cn = normalize_name(cell)
    if not cn:
        return None
    for h in input_hotels:
        hn = normalize_name(h)
        core = hn.split("(")[0]
        if hn in cn or cn in hn or (len(hn) >= 6 and hn[:6] in cn) or (len(core) >= 4 and core in cn):
            return h
    return None


def _segment(text: str, keyword: str) -> str:
    """截取从 keyword 到下一个已知段落标题之间的文本。"""
    headers = ["需求理解", "酒店分析", "根据你的偏好", "全部酒店对比", "方案"]
    idx = text.find(keyword)
    if idx < 0:
        return ""
    rest = text[idx:]
    end = len(rest)
    for h in headers:
        j = rest.find(h, len(keyword))
        if 0 < j < end:
            end = j
    return rest[:end]


def _match_first(pattern, text: str) -> str:
    m = re.search(pattern, text) if text else None
    if not m:
        return ""
    try:
        return m.group(1)
    except IndexError:
        return m.group(0)


def _int(s: str):
    return int(s) if s else None


def _cn_num(s: str) -> int:
    s = s.strip()
    if s in _CN_NUM:
        return _CN_NUM[s]
    return int(s) if s.isdigit() else 0


def _first_hotel_name(body: str) -> str:
    """从方案块里取酒店名（去掉行尾档次词）。"""
    for line in body.splitlines():
        line = line.strip()
        if "酒店" in line and "综合推荐指数" not in line:
            line = _LEVEL_RE.sub("", line).strip()
            if line and len(line) < 40:
                return line
    return ""


def _extract_reasons(body: str) -> List[str]:
    """方案块里含'：'的理由行。"""
    reasons: List[str] = []
    for line in body.splitlines():
        s = line.strip().strip("-•·　 ")
        if "：" in s and "综合推荐指数" not in s and "方案" not in s:
            reasons.append(s)
    return reasons
