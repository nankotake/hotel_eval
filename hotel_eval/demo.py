"""demo.py —— 入口示例：遍历 data/ 下所有 case，跑通整条评测链路。

数据全部来自 JSON 文件（代码里不写死样本）：
  - eval_cases.json   入参（用户输入）+ 参考信息（酒店详情/用户画像）
  - llm_outputs.json  评测对象（LLM 原始输出 + 声称）

跑法：python run_hotel_eval.py
"""

from __future__ import annotations

from . import prompts, report
from .casefile import EvalCase, LLMOutputRecord, load_cases, load_llm_outputs
from .engine import _judge_payloads, run_case_eval


def run_one(case: EvalCase, rec: LLMOutputRecord, show_prompt: bool = False) -> None:
    """跑一个 case 的一份 LLM 输出：抽取 → 全量确定性层 → judge → 报告。

    实际计算委托给 engine.run_case_eval（返回结构化结果），这里只负责打印。
    """
    result = run_case_eval(case, rec)

    inp = result.input
    ref = result.reference
    out = result.output

    print()
    print("=" * 72)
    print(f"评测 case: {case.case_id}   输出来源: {rec.source or '(未标注)'}")
    print(f"入参(用户输入): 选择酒店={inp.hotels}  天数={inp.nights}  日期={inp.date or '-'}  人数={inp.guests or '-'}")
    print(f"参考信息(基准): 酒店详情={len(ref.fact_db)} 家  用户画像={ref.profile or '(未提供)'}")
    if ref.profile_text:
        print(f"                画像描述: {ref.profile_text}")
    print(f"声称(待核对): {result.claims_count} 条（自动 {len(out.analysis_claims) + len(out.reason_claims) + len(out.table_claims)} + 手工 {len(rec.claims)}，去重后）")
    print()

    # 报告
    report.render(result.issues, result.judge_results, inp, out, ref.profile, len(ref.fact_db), ref.profile_text)

    # 展示 judge 提示词样例（供对照手写 prompt；只在第一份输出打印一次）
    if show_prompt and not result.conclusion()["judge_enabled"]:
        payloads = _judge_payloads(inp, ref, out)
        print("=" * 72)
        print("提示：未检测到 JUDGE_API_KEY / OPENAI_API_KEY / DEEPSEEK_API_KEY。")
        print("judge 层跳过；下面打印'相关性'维度的 judge 提示词模板，供对照：")
        print("=" * 72)
        print(prompts.build_judge_prompt("相关性", payloads["相关性"]))


def main() -> None:
    cases = load_cases()
    outputs = load_llm_outputs()

    for ci, case in enumerate(cases):
        recs = [o for o in outputs if o.case_id == case.case_id]
        if not recs:
            print(f"[跳过] case '{case.case_id}' 在 llm_outputs.json 里没有对应输出")
            continue
        for ri, rec in enumerate(recs):
            run_one(case, rec, show_prompt=(ci == 0 and ri == 0))

    # 行为校准示例（合成数据，与具体 case 无关，演示 judge 分 vs 行为 的对齐度计算）
    print()
    print("=" * 72)
    print("行为校准示例（合成数据，演示 judge 分与真实预订的相关性）")
    print("=" * 72)
    demo_records = [
        online.OnlineRecord("a", 5.0, booked=1),
        online.OnlineRecord("b", 4.5, booked=1),
        online.OnlineRecord("c", 3.0, booked=0),
        online.OnlineRecord("d", 2.0, booked=0),
        online.OnlineRecord("e", 4.0, booked=1),
        online.OnlineRecord("f", 1.0, booked=0),
        online.OnlineRecord("g", 3.5, booked=0),
    ]
    print(online.compute_calibration(demo_records))


if __name__ == "__main__":
    main()
