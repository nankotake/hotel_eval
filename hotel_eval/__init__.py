"""hotel_eval —— 酒店推荐评测框架（去 prompt 化 + 分层评测）

数据三分类（见 data/eval_case.json）：
  - 入参（用户输入）：入住天数/日期/人数/选择的酒店 —— 被测 LLM 收到的请求
  - 参考信息（基准） ：酒店信息详情（事实库）+ 用户画像 —— 评测方提供，用于比对
  - 评测对象         ：LLM 输出

按维度组织，每个维度一个模块：
  - casefile     评测数据加载（入参 + 参考信息，来自数据文件）
  - consistency  一致性（输入输出回显 / 上下文自洽 / 事实查库 / 勾选覆盖 / 画像回显）—— 确定性 floor 层
  - safety       安全性 —— 规则层 + judge
  - semantics    语义 —— BERTScore（有参考时）+ judge（开放时）
  - relevance    相关性 —— 规则层 + 受众匹配 + judge
  - judge        LLM-as-judge 引擎（多维度结构化打分 + 引用依据 + confidence）
  - online       在线层（全量确定性检查 + 行为反馈校准）
  - report       分层汇总报告

入口：python run_hotel_eval.py
"""

from .casefile import EvalCase, LLMOutputRecord, load_cases, load_llm_outputs
from .schema import (
    EvalReference,
    HotelInput,
    HotelFact,
    LLMOutput,
    RecommendedHotel,
    Claim,
    Issue,
    CheckResult,
)

__all__ = [
    "EvalCase",
    "LLMOutputRecord",
    "load_cases",
    "load_llm_outputs",
    "EvalReference",
    "HotelInput",
    "HotelFact",
    "LLMOutput",
    "RecommendedHotel",
    "Claim",
    "Issue",
    "CheckResult",
]
