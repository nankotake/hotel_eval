"""engine.py —— 结构化评测引擎（返回可序列化结果，供 Web 界面 / CLI 复用）

把 demo.run_one 的"抽取 → 全量确定性层 → judge → 结论"改造成返回结构化数据，
不直接 print，这样界面能自己渲染，CLI 也能复用同一份逻辑。
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional

from . import judge, online
from .casefile import EvalCase, LLMOutputRecord
from .extractor import parse_llm_output
from .schema import Claim, EvalReference, HotelInput, Issue, LLMOutput, normalize_name


# --------------------------------------------------------------------------- #
# judge client 构建
# --------------------------------------------------------------------------- #

def _env_key() -> str:
    return (
        os.environ.get("JUDGE_API_KEY")
        or os.environ.get("OPENAI_API_KEY")
        or os.environ.get("DEEPSEEK_API_KEY")
        or ""
    )


def build_judge_client(config: Optional[dict] = None):
    """构建 (client, model)。config 来自界面配置（config.json），否则回退环境变量。

    无 key 时返回 (None, None)，调用方据此跳过 judge 层。
    """
    if config:
        key = config.get("judge_api_key") or _env_key()
        model = config.get("judge_model") or os.environ.get("JUDGE_MODEL", "gpt-4o-mini")
        base_url = config.get("judge_base_url") or os.environ.get("JUDGE_BASE_URL") or None
    else:
        key = _env_key()
        model = os.environ.get("JUDGE_MODEL", "gpt-4o-mini")
        base_url = os.environ.get("JUDGE_BASE_URL") or None

    if not key:
        return None, None
    try:
        from openai import OpenAI
    except ImportError:
        return None, None
    kwargs = {"api_key": key}
    if base_url:
        kwargs["base_url"] = base_url
    return OpenAI(**kwargs), model


# --------------------------------------------------------------------------- #
# 共享辅助（从 demo 迁移过来，避免重复）
# --------------------------------------------------------------------------- #

def _judge_payloads(inp: HotelInput, ref: EvalReference, out: LLMOutput) -> dict:
    reasons = "\n".join(r for h in out.results for r in h.reasons)
    return {
        "语义": {"text": reasons or out.raw},
        "相关性": {
            "input": {"selected_hotels": inp.hotels, "date": inp.date, "guests": inp.guests},
            "user_profile": {"tags": ref.profile, "description": ref.profile_text},
            "results": [r.name for r in out.results],
            "reasons": reasons,
        },
        "安全性": {"text": out.raw},
        "权衡质量": {"input": inp.hotels, "results": [r.name for r in out.results],
                      "reasons": reasons},
    }


def _dedup_claims(claims: List[Claim]) -> List[Claim]:
    """同酒店 + 属性 + 值的声称只留一条（自动抽取的对比表/方案块/分析段可能重复）。"""
    seen, out = set(), []
    for c in claims:
        key = (normalize_name(c.hotel), c.attribute, repr(c.value))
        if key in seen:
            continue
        seen.add(key)
        out.append(c)
    return out


# --------------------------------------------------------------------------- #
# 运行结果
# --------------------------------------------------------------------------- #

@dataclass
class RunResult:
    """一次评测（一个 case + 一份 LLM 输出）的完整结构化结果。"""

    case_id: str
    source: str
    note: str
    input: HotelInput
    reference: EvalReference
    output: LLMOutput
    issues: List[Issue]
    judge_results: Dict[str, dict]
    claims_count: int

    def conclusion(self) -> dict:
        by_layer = {"gate": 0, "safety": 0, "quality": 0}
        for i in self.issues:
            if not i.passed and i.layer in by_layer:
                by_layer[i.layer] += 1
        gate_fail = by_layer["gate"] > 0
        judge_enabled = any(r and r.get("score") is not None for r in self.judge_results.values())
        return {
            "gate": "FAIL" if gate_fail else "PASS",
            "by_layer": by_layer,
            "judge_enabled": judge_enabled,
            "summary": (
                "硬门禁 FAIL，存在确定性层违规，整单判失败。"
                if gate_fail else "硬门禁 PASS，可进入质量层看 judge 结果。"
            ),
        }

    def summary(self) -> dict:
        """记录列表用的紧凑摘要。"""
        c = self.conclusion()
        judge = {d: r.get("score") for d, r in self.judge_results.items() if r and r.get("score") is not None}
        return {
            "case_id": self.case_id,
            "source": self.source,
            "gate": c["gate"],
            "issue_count": len(self.issues),
            "by_layer": c["by_layer"],
            "judge_enabled": c["judge_enabled"],
            "judge": judge,
        }

    def to_dict(self) -> dict:
        """完整可序列化报告，供记录存储 / 报告详情页渲染。"""
        c = self.conclusion()
        out = self.output
        return {
            "case_id": self.case_id,
            "source": self.source,
            "note": self.note,
            "input": self.input.to_dict(),
            "reference": {
                "fact_count": len(self.reference.fact_db),
                "fact_db": {name: asdict(f) for name, f in self.reference.fact_db.items()},
                "profile": self.reference.profile,
                "profile_text": self.reference.profile_text,
            },
            "extracted": {
                "results": [asdict(r) for r in out.results],
                "dates": out.dates,
                "requirement_star": out.requirement_star,
                "requirement_region": out.requirement_region,
                "requirement_guests": out.requirement_guests,
                "requirement_hotels": out.requirement_hotels,
                "analysis_hotels": out.analysis_hotels,
                "claims_count": self.claims_count,
                "analysis_claims": [asdict(c) for c in out.analysis_claims],
                "table_claims": [asdict(c) for c in out.table_claims],
                "reason_claims": [asdict(c) for c in out.reason_claims],
                "table": out.table,
                "requirement_text": out.requirement_text,
                "analysis_text": out.analysis_text,
            },
            "issues": [asdict(i) for i in self.issues],
            "judge_results": self.judge_results,
            "conclusion": c,
        }


# --------------------------------------------------------------------------- #
# 运行入口
# --------------------------------------------------------------------------- #

def run_case_eval(
    case: EvalCase,
    rec: LLMOutputRecord,
    judge_config: Optional[dict] = None,
    judge_client=None,
    judge_model: Optional[str] = None,
) -> RunResult:
    """跑一个 case 的一份 LLM 输出：抽取 → 全量确定性层 → judge → 结构化结果。

    judge_config: 界面配置（config.json 的 judge 字段），有 key 则启用 judge；
                  否则回退环境变量。也可直接注入 judge_client / judge_model。
    """
    inp = case.input
    ref = case.reference
    fact_db = ref.fact_db
    out = parse_llm_output(rec.raw, inp.hotels)

    claims = _dedup_claims(out.analysis_claims + out.reason_claims + out.table_claims + rec.claims)
    issues = online.run_full_layer(inp, out, fact_db, claims)

    if judge_client is None:
        judge_client, judge_model = build_judge_client(judge_config)

    judge_results: Dict[str, dict] = {}
    if judge_client is not None:
        payloads = _judge_payloads(inp, ref, out)
        for dim, payload in payloads.items():
            judge_results[dim] = judge.judge_structured(dim, payload, client=judge_client, model=judge_model)

    return RunResult(
        case_id=case.case_id,
        source=rec.source,
        note=rec.note,
        input=inp,
        reference=ref,
        output=out,
        issues=issues,
        judge_results=judge_results,
        claims_count=len(claims),
    )
