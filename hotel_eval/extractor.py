"""extractor.py —— 把 LLM 原始输出拆成结构化字段（LLMOutput）。

说明：
  - 生产系统里，最好让被测系统直接输出结构化 JSON，本模块的 parse 只做"校验 + 归一化"。
  - 这里提供一套针对"文本渲染输出"的正则解析，作为 demo 级实现，用于跑通评测链路。
  - 从自由文本里抽取"任意事实声称"本身是 NLP 问题，此处对结构化部分（方案/对比表/日期）可靠抽取，
    自由文本里的声称由调用方补充（见 demo.py 的 analysis_claims）。
"""

from __future__ import annotations

import re
from typing import List

from .schema import HotelInput, LLMOutput, RecommendedHotel

_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}|\d{1,2}月\d{1,2}日")
_GUESTS_RE = re.compile(r"(\d+)\s*(?:人|位|名)(?!晚|星|元|家|间)")
_STAR_RE = re.compile(r"(五星|四星|三星|经济型|舒适型|豪华型)")
_REGION_RE = re.compile(r"(徐汇区|浦东新区|宝山区|静安区|黄浦区|长宁区|杨浦区|虹口区|闵行区|松江区|嘉定区|青浦区|奉贤区|金山区)")
_PRICE_RE = re.compile(r"¥?(\d+)\s*元起")


def extract_dates(text: str) -> List[str]:
    return list(dict.fromkeys(_DATE_RE.findall(text)))


def extract_requirement(text: str) -> dict:
    """从需求理解段抽取 星级/区域/人数（尽力而为）。"""
    seg = _segment(text, "需求理解")
    return {
        "requirement_star": (_match_first(_STAR_RE, seg)),
        "requirement_region": (_match_first(_REGION_RE, seg)),
        "requirement_guests": (_int(_match_first(_GUESTS_RE, seg))),
    }


def extract_analysis_hotels(text: str, input_hotels: List[str]) -> List[str]:
    """分析段里提及的、且能匹配到候选列表的酒店名。"""
    seg = _segment(text, "酒店分析定位")
    return [h for h in input_hotels if h[:6] in seg or h in seg]


def extract_results(text: str) -> List[RecommendedHotel]:
    """抽取 方案1/方案2 块：酒店名、档次、价格、理由。"""
    results: List[RecommendedHotel] = []
    blocks = re.split(r"方案(\d+)\s*[·|｜]?\s*[^\n]*", text)
    # 上面 split 会交替产出 [前置, 序号1, 内容1, 序号2, 内容2, ...]
    for i in range(1, len(blocks), 2):
        rank = int(blocks[i])
        body = blocks[i + 1] if i + 1 < len(blocks) else ""
        name = _first_hotel_name(body)
        if not name:
            continue
        results.append(
            RecommendedHotel(
                rank=rank,
                name=name,
                star_text=_match_first(r"[★☆]{3,}", body) or "",
                level_text=_match_first(_STAR_RE, body) or "",
                price_text=_match_first(_PRICE_RE, body) or "",
                reasons=[ln.strip("- •　") for ln in body.splitlines() if ln.strip().startswith(("-", "•"))],
            )
        )
    return results


def extract_table(text: str) -> List[dict]:
    """抽取 markdown 对比表行（酒店/评分/价格/星级）。"""
    rows: List[dict] = []
    in_table = False
    for line in text.splitlines():
        if "|" not in line:
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if not cells or cells[0] in ("酒店",) or set("".join(cells)) <= set("-| "):
            continue
        # 第一列是"酒店"或"推荐指数"等标签行跳过；数据行第一列是酒店名或指标名
        if cells[0] in ("推荐指数", "价格", "位置", "评分", "亮点"):
            continue
        rows.append(cells)
    return rows


def parse_llm_output(raw: str, input_hotels: List[str]) -> LLMOutput:
    out = LLMOutput(raw=raw)
    out.dates = extract_dates(raw)
    req = extract_requirement(raw)
    out.requirement_star = req["requirement_star"]
    out.requirement_region = req["requirement_region"]
    out.requirement_guests = req["requirement_guests"]
    out.analysis_hotels = extract_analysis_hotels(raw, input_hotels)
    out.results = extract_results(raw)
    out.table = extract_table(raw)
    return out


# --------------------------------------------------------------------------- #
# 内部工具
# --------------------------------------------------------------------------- #

def _segment(text: str, keyword: str) -> str:
    """截取从 keyword 到下一个已知段落标题之间的文本。"""
    headers = ["需求理解", "酒店分析定位", "根据你的偏好", "全部酒店对比", "方案"]
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


def _first_hotel_name(body: str) -> str:
    """从方案块里取第一行含"酒店"的名字。"""
    for line in body.splitlines():
        line = line.strip()
        if "酒店" in line and len(line) < 40:
            return line
    return ""
