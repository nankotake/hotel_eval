"""online.py —— 在线层：全量确定性检查 + 行为反馈校准

两条职责：
  1. run_full_layer()：在 100% 线上流量上零成本跑的确定性检查（不问模型）。
  2. compute_calibration()：用真实行为（点击/预订/负反馈）校准 judge 分数，
     "judge 是代理真值，要向行为真值看齐"。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

from . import consistency, relevance, safety
from .schema import Claim, HotelFact, HotelInput, Issue, LLMOutput


@dataclass
class OnlineRecord:
    """一条线上样本的观测：judge 分数 + 用户真实行为。"""

    item_id: str
    judge_score: Optional[float]  # 某维度 judge 分
    clicked: int = 0  # 0/1
    booked: int = 0  # 0/1
    negative: int = 0  # 0/1 负反馈


def run_full_layer(
    inp: HotelInput,
    out: LLMOutput,
    fact_db: Dict[str, HotelFact],
    claims: List[Claim],
) -> List[Issue]:
    """全量层：确定性检查（一致性的三个子维度 + 安全规则 + 相关性规则）。"""
    issues: List[Issue] = []
    issues += consistency.check_input_output(inp, out)
    issues += consistency.check_context(inp, out)
    issues += consistency.check_factual(fact_db, claims)
    issues += safety.check_safety_rules(out.raw)
    issues += relevance.check_relevance_rules(inp, out)
    issues += relevance.check_audience_fit(inp, out)
    return issues


def compute_calibration(records: List[OnlineRecord]) -> Dict[str, Optional[float]]:
    """judge 分数 vs 真实行为的对齐度。

    - point-biserial 相关：judge 分(连续) 与 是否预订(二分) 的相关性。
      > 0 且显著 = judge 分数越高的样本，真实预订越多（judge 对齐了行为）。
      ≈ 0 = judge 分数与行为无关（judge 没对齐，需要诊断 rubric）。
    """
    from scipy import stats

    scored = [r for r in records if r.judge_score is not None]
    if len(scored) < 3:
        return {"n": len(scored), "note": "样本不足，无法计算相关性"}

    scores = [r.judge_score for r in scored]
    booked = [r.booked for r in scored]

    r_pb, p_pb = stats.pointbiserialr(booked, scores)
    r_s, p_s = stats.spearmanr(scores, booked)
    return {
        "n": len(scored),
        "point_biserial_r": round(float(r_pb), 4),
        "point_biserial_p": round(float(p_pb), 4),
        "spearman_r": round(float(r_s), 4),
        "spearman_p": round(float(p_s), 4),
        "aligned": bool(p_pb < 0.05 and r_pb > 0),
    }
