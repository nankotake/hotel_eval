"""hotel_eval —— 酒店推荐评测框架（去 prompt 化 + 分层评测）

按用户既定维度组织，每个维度一个模块：
  - consistency  一致性（事实 / 上下文 / 输入输出）—— 确定性 floor 层
  - safety       安全性 —— 规则层 + judge
  - semantics    语义 —— BERTScore（有参考时）+ judge（开放时）
  - relevance    相关性 —— 规则层 + judge
  - judge        LLM-as-judge 引擎（多维度结构化打分 + 引用依据 + confidence）
  - online       在线层（全量确定性检查 + 行为反馈校准）
  - report       分层汇总报告

入口：python run_hotel_eval.py
"""

from .schema import (
    HotelInput,
    HotelFact,
    LLMOutput,
    RecommendedHotel,
    Claim,
    Issue,
    CheckResult,
)

__all__ = [
    "HotelInput",
    "HotelFact",
    "LLMOutput",
    "RecommendedHotel",
    "Claim",
    "Issue",
    "CheckResult",
]
