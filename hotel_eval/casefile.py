"""casefile.py —— 评测数据加载（入参 + 参考信息 + 评测对象，JSON 数组）

三类数据要分清：

  - 用户输入（入参）    ：入住天数/日期/人数/选择的酒店 —— 被测 LLM 收到的请求
  - 参考信息（真值/基准）：酒店信息详情（事实库）+ 用户画像 —— 评测方提供，用于比对
  - 评测对象            ：LLM 原始输出（被测系统的回答）

文件都是 JSON 数组，加 case 就往里加一项：
  - data/eval_cases.json    入参 + 参考信息（一项 = 一个 case）
  - data/llm_outputs.json   评测对象（一项 = 一份 LLM 输出，按 case_id 挂到 case）

case_id 是关联键：llm_outputs 的 case_id 必须能对上 eval_cases 的 case_id；
同一个 case 可以挂多份输出（不同模型/不同时间）做对比评测。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Dict, List

from .schema import Claim, EvalReference, HotelFact, HotelInput

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
DEFAULT_CASES_PATH = os.path.join(DATA_DIR, "eval_cases.json")
DEFAULT_OUTPUTS_PATH = os.path.join(DATA_DIR, "llm_outputs.json")


@dataclass
class EvalCase:
    """一份评测用例：入参（input）+ 参考信息（reference）。评测对象是 LLM 输出。"""

    case_id: str
    input: HotelInput  # 用户输入（入参）：天数/日期/人数/选择的酒店
    reference: EvalReference  # 参考信息（基准）：酒店信息详情 + 用户画像
    note: str = ""  # 说明/备注（可选，数据文件里的顶层 note，保留用）

    def to_dict(self) -> dict:
        d = {"case_id": self.case_id}
        if self.note:
            d["note"] = self.note
        inp = self.input.to_dict()
        if inp:
            d["input"] = inp
        ref = self.reference.to_dict()
        if ref:
            d["reference"] = ref
        return d


@dataclass
class LLMOutputRecord:
    """一份评测对象：LLM 原始输出 + 从输出抽取的客观声称（claims）。"""

    case_id: str  # 关联到 eval_cases 里的 case
    raw: str
    source: str = ""  # 来源标注（可选）
    note: str = ""  # 备注（可选）
    claims: List[Claim] = field(default_factory=list)
    output_id: str = ""  # Web 端用：同一 case 多份输出的唯一标识（缺省时按索引管理）

    def to_dict(self) -> dict:
        d = {
            "case_id": self.case_id,
            "raw": self.raw,
        }
        if self.source:
            d["source"] = self.source
        if self.note:
            d["note"] = self.note
        if self.output_id:
            d["output_id"] = self.output_id
        if self.claims:
            d["claims"] = [c.to_dict() for c in self.claims]
        return d


def load_cases(path: str = DEFAULT_CASES_PATH) -> List[EvalCase]:
    """加载全部评测用例（入参 + 参考信息）。"""
    with open(path, encoding="utf-8") as f:
        items = json.load(f)
    return [_parse_case(it) for it in items]


def build_case(data: dict) -> EvalCase:
    """从 dict 构建 EvalCase（与 eval_cases.json 里一项同构），供 Web 端新建/编辑。"""
    return _parse_case(data)


def _parse_case(raw: dict) -> EvalCase:
    inp_raw = raw.get("input", {})
    inp = HotelInput(
        hotels=list(inp_raw.get("hotels", [])),  # 选择的酒店
        date=inp_raw.get("date") or "",  # 日期（可选）
        guests=inp_raw.get("guests"),  # 人数（可选，None 则跳过人数回显检查）
        nights=int(inp_raw.get("nights", 1)),  # 入住天数
        region=inp_raw.get("region") or None,
        budget=inp_raw.get("budget"),
        extra={"case_id": raw.get("case_id", "")},
    )
    ref_raw = raw.get("reference", {})
    fact_db = {
        name: HotelFact(name=name, **{k: v for k, v in fields.items() if k != "name"})
        for name, fields in ref_raw.get("fact_db", {}).items()
    }
    profile_raw = ref_raw.get("user_profile", {})
    profile = list(profile_raw.get("tags", []))
    profile_text = profile_raw.get("description", "")
    profile_note = profile_raw.get("note", "")
    return EvalCase(
        case_id=raw.get("case_id", ""),
        input=inp,
        reference=EvalReference(
            fact_db=fact_db,
            profile=profile,
            profile_text=profile_text,
            profile_note=profile_note,
        ),
        note=raw.get("note", ""),
    )


def load_llm_outputs(path: str = DEFAULT_OUTPUTS_PATH) -> List[LLMOutputRecord]:
    """加载全部评测对象（LLM 输出）。"""
    with open(path, encoding="utf-8") as f:
        items = json.load(f)
    return [_parse_output(it) for it in items]


def build_output(data: dict) -> LLMOutputRecord:
    """从 dict 构建 LLMOutputRecord（与 llm_outputs.json 里一项同构），供 Web 端新建/编辑。"""
    return _parse_output(data)


def _parse_output(raw: dict) -> LLMOutputRecord:
    claims = [
        Claim(
            hotel=c.get("hotel", ""),
            attribute=c.get("attribute", ""),
            value=c.get("value"),
            source=c.get("source", ""),
        )
        for c in raw.get("claims", [])
    ]
    return LLMOutputRecord(
        case_id=raw.get("case_id", ""),
        raw=raw.get("raw", ""),
        source=raw.get("source", ""),
        note=raw.get("note", ""),
        claims=claims,
        output_id=raw.get("output_id", ""),
    )
