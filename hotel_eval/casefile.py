"""casefile.py —— 评测数据加载（入参 + 参考信息，均独立于 LLM 输出）

三类数据要分清：

  - 用户输入（入参）    ：入住天数/日期/人数/选择的酒店 —— 被测 LLM 收到的请求
  - 参考信息（真值/基准）：酒店信息详情（事实库）+ 用户画像 —— 评测方提供，用于比对
  - 评测对象            ：LLM 输出（不在此文件里，单独传入评测链路）

本模块从 JSON 数据文件加载"入参 + 参考信息"。文件与 LLM 输出完全无关——
不要从 LLM 输出里抄值进来当基准，否则事实核对就变成了同义反复。

文件位置：hotel_eval/data/eval_case.json（可传自定义路径）
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Dict, List

from .schema import EvalReference, HotelFact, HotelInput

DEFAULT_CASE_PATH = os.path.join(os.path.dirname(__file__), "data", "eval_case.json")


@dataclass
class EvalCase:
    """一份评测用例：入参（input）+ 参考信息（reference）。评测对象是 LLM 输出。"""

    case_id: str
    input: HotelInput  # 用户输入（入参）：天数/日期/人数/选择的酒店
    reference: EvalReference  # 参考信息（基准）：酒店信息详情 + 用户画像


def load_case(path: str = DEFAULT_CASE_PATH) -> EvalCase:
    """从 JSON 加载评测数据 → EvalCase（入参 + 参考信息）。"""
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)

    # ---- 入参：用户输入 ----
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

    # ---- 参考信息：酒店信息详情 + 用户画像 ----
    ref_raw = raw.get("reference", {})
    fact_db = {
        name: HotelFact(name=name, **fields)
        for name, fields in ref_raw.get("fact_db", {}).items()
    }
    profile = list(ref_raw.get("user_profile", {}).get("tags", []))

    return EvalCase(
        case_id=raw.get("case_id", ""),
        input=inp,
        reference=EvalReference(fact_db=fact_db, profile=profile),
    )
