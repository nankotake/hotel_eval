"""semantics.py —— 维度 3：语义

两条路：
  - 有参考答案时：BERTScore（确定性、token 级语义对齐，复用 p1_metrics 的能力）。
  - 开放无参考时：judge 语义（流畅/通顺/表达质量），属质量层，抽样 + 引用依据。
"""

from __future__ import annotations

from typing import List, Optional

from .schema import Issue

DIM = "语义"


def bert_score(reference: str, candidate: str, model_type: str = "distilbert-base-uncased") -> Optional[float]:
    """确定性语义相似度（有参考时用）。"""
    try:
        from bert_score import score
        _P, _R, F1 = score(
            [candidate], [reference], lang="zh" if _is_cn(reference) else "en",
            model_type=model_type, rescale_with_baseline=False, verbose=False,
        )
        return float(F1.item())
    except Exception:
        return None


def judge_semantics(candidate: str, judge_fn=None) -> List[Issue]:
    """开放语义 judge 层：流畅/通顺/表达质量。"""
    if judge_fn is None:
        return []
    res = judge_fn(dimension="语义", payload={"text": candidate})
    if res is None:
        return []
    score = float(res.get("score", 0))
    return [Issue(
        dimension=DIM, check="语义·judge", layer="quality",
        passed=score >= 3, score=score,
        detail=res.get("evidence", ""), evidence=res.get("evidence", ""),
    )]


def _is_cn(s: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in s)
