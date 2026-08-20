"""report.py —— 分层汇总报告

原则：分层报、不混成一个总分。硬门禁(gate)失败即整单 fail，安全/质量层单独列。
"""

from __future__ import annotations

from typing import Dict, List

from .schema import HotelInput, Issue, LLMOutput

_LAYER_ORDER = ["gate", "safety", "quality"]
_LAYER_LABEL = {
    "gate": "硬门禁（一致性·回显/自洽/事实）",
    "safety": "安全层",
    "quality": "软性层（需人工确认 / judge）",
}


def render(
    issues: List[Issue],
    judge_results: Dict[str, dict],
    inp: HotelInput,
    out: LLMOutput,
    profile: List[str] = None,
    fact_count: int = 0,
) -> None:
    by_layer: Dict[str, List[Issue]] = {}
    for i in issues:
        by_layer.setdefault(i.layer, []).append(i)

    print("=" * 72)
    print("酒店推荐评测报告")
    print("=" * 72)
    print(f"入参(用户输入) : case={inp.extra.get('case_id', '-')}")
    print(f"  选择酒店     : {inp.hotels}")
    print(f"  入住条件     : 天数={inp.nights}  日期={inp.date or '-'}  人数={inp.guests or '-'}")
    print(f"参考信息(基准) : 酒店详情={fact_count} 家  用户画像={profile or '(未提供)'}")
    print(f"抽取 : 推荐结果={[r.name for r in out.results]}")
    print(f"       输出日期={out.dates}  需求星级={out.requirement_star}  需求区域={out.requirement_region}")
    print()

    gate_fail = False
    for layer in _LAYER_ORDER:
        items = by_layer.get(layer, [])
        fails = [i for i in items if not i.passed]
        print(f"【{_LAYER_LABEL[layer]}】")
        if not items:
            print("  - 无该层问题")
        for i in fails:
            ev = f"  <- {i.evidence}" if i.evidence else ""
            print(f"  ✗ [{i.check}] {i.detail}{ev}")
            if layer == "gate":
                gate_fail = True
        print()

    print("【LLM-as-judge 层】")
    any_judge = False
    for dim, res in judge_results.items():
        if not res or res.get("score") is None:
            continue
        any_judge = True
        conf = res.get("confidence", "medium")
        print(f"  {dim}: score={res['score']}  confidence={conf}")
        if res.get("evidence"):
            print(f"      依据: {res['evidence']}")
    if not any_judge:
        print("  - (未启用：未配置 API key，judge 层跳过，仅跑确定性层)")
    print()

    print("【结论】")
    if gate_fail:
        print("  硬门禁: FAIL —— 存在确定性层违规，整单判失败，无需进入质量层。")
    else:
        print("  硬门禁: PASS —— 无确定性违规，可进入质量层看 judge 结果。")
