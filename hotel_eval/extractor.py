"""extractor.py —— 把 LLM 原始输出拆成结构化字段（LLMOutput）。

说明：
  - 生产系统里，最好让被测系统直接输出结构化 JSON，本模块的 parse 只做"校验 + 归一化"。
  - 这里提供一套针对"文本渲染输出"的正则解析，作为 demo 级实现，用于跑通评测链路。
  - 所有跨段/跨库的酒店名匹配都用 normalize_name()，容忍粘贴时的空格/全半角括号差异。
"""

from __future__ import annotations

import re
from typing import List

from .schema import HotelInput, LLMOutput, RecommendedHotel, normalize_name

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


def extract_table(text: str) -> List[dict]:
    """抽取 markdown 对比表行（尽力而为）。"""
    rows: List[dict] = []
    for line in text.splitlines():
        if "|" not in line:
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if not cells or set("".join(cells)) <= set("-| "):
            continue
        rows.append(cells)
    return rows


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
    return out


# --------------------------------------------------------------------------- #
# 内部工具
# --------------------------------------------------------------------------- #

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
