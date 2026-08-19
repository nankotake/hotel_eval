"""demo.py —— 入口示例：用真实酒店输出跑通整条评测链路。

跑法：python run_hotel_eval.py
"""

from __future__ import annotations

from . import judge, online, prompts, relevance, report
from .extractor import parse_llm_output
from .schema import Claim, HotelFact, HotelInput

# --------------------------------------------------------------------------- #
# 被测数据（真实样例，来自用户粘贴的酒店推荐输出）
# --------------------------------------------------------------------------- #

RAW_OUTPUT = """需求理解完成

用户将在近期前往上海，并有入住当地酒店的需求，打算 独自在2026-08-19入住酒店，并于2026-08-20离店(共1晚）。用户本次对比的酒店共3家，它们是：宿适精选酒 店（上海虹桥国展中心店)、上海埕前假日酒店(大场镇地铁 站店)以及季朵酒店(上海国际旅游度假区店)。

酒店分析完成

宿适精选酒店(上海虹桥国展中心店)：这家舒适型酒店以 153元起的亲民价格吸引众多旅客，步行260米即达临洮 路地铁站，出行极为便利。酒店周边餐饮丰富，3公里内 有300家餐厅可选，前台服务热情周到，主动为客人提供 本地美食地图。虽然设施略显老旧，但房间宽敞、床品舒 适，性价比依然出色。
上海埕前假日酒店（大场镇地铁站店）：184元起的新开业经 济型酒店，7号线大场镇站B1层直达，雨天出行也无需淋 雨。酒店配备独立洗衣机和一次性干巾等贴心设施，卫生 标准极高，房间崭新整洁。对面就是宝山日月光商场，吃 喝玩乐一应俱全，是追求干净舒适体验的年轻住客理想之 选。
季朵酒店(上海国际旅游度假区店)：202元起的舒适型酒 店，提供川沙地铁站免费送站服务，还设有直达迪士尼的 接驳班车。酒店房间配备超大投影设备，床品舒适，毛巾 浴巾均为一次性用品，卫生标准令人安心。工作人员服务 温柔细致，特别适合亲子家庭和迪士尼游客入住。

根据你的偏好，为你推荐以下酒店
方案一 迪士尼旁好住处
季朵酒店(上海国际旅游度 假区店）舒适型
综合推荐指数 ***** ¥202起
床品舒适：床垫软硬适中，玩一天回来躺下特 别解乏，房间整洁干净，睡得很舒服很安心~
服务贴心：有免费接驳车直达迪士尼和地铁 站，工作人员温柔耐心，还帮忙找回丢失的手链 特别暖心！

方案二 新净舒适超值选
上海埕前假日酒店(大场镇 地铁站店）经济型
综合推荐指数 ***** ¥184起
卫生干净：新开业酒店， 房间特别宽敞整洁 配备一次性干巾和独立洗衣机，卫生标准让人特别 安心~
交通便利：地铁7号线B1层直达，雨天也不用 淋雨，对面就是日月光商场，出行觅食都超方便!

全部酒店对比
|酒店|季朵酒店（上海国际旅游度假...|上海埕前假日酒店(大场镇地...|宿适精选酒店（上海虹桥国展...|
|-----|-----|-----|-----|
|推荐指数|*****|*****|****|
|价格|¥202起 30天低价|￥184起 30天低价|￥153起 30天低价|
|位置|--|周边是大宁公园和上海木文化博物馆|在上海古漪园、南翔古镇以及临洮路（地铁站）附件|
|评分|5.0 超棒|4.6 好|4.2|
|亮点设施|免费停车场、无烟楼层|无烟楼层、电梯、外卖接收|充电车位、付费停车场|
"""

INPUT = HotelInput(
    hotels=[
        "宿适精选酒店（上海虹桥国展中心店）",
        "上海埕前假日酒店（大场镇地铁站店）",
        "季朵酒店（上海国际旅游度假区店）",
    ],
    date="2026-08-19",
    guests=1,  # 需求说"独自"
    nights=1,
)

FACT_DB = {
    "宿适精选酒店（上海虹桥国展中心店）": HotelFact(
        name="宿适精选酒店（上海虹桥国展中心店）",
        region="青浦区", star="舒适型", price=153, score=4.2,
        facilities=["临洮路地铁站步行可达", "周边餐饮丰富"],
    ),
    "上海埕前假日酒店（大场镇地铁站店）": HotelFact(
        name="上海埕前假日酒店（大场镇地铁站店）",
        region="宝山区", star="经济型", price=184, score=4.6,
        facilities=["独立洗衣机", "一次性干巾"],
    ),
    "季朵酒店（上海国际旅游度假区店）": HotelFact(
        name="季朵酒店（上海国际旅游度假区店）",
        region="浦东新区", star="舒适型", price=202, score=5.0,
        facilities=["迪士尼接驳", "川沙地铁站送站", "投影设备"],
    ),
}

# 事实声称：结构化部分（方案/对比表）可靠抽取；自由文本里的声称手工补（生产里由系统结构化输出或抽取模型负责）
CLAIMS = [
    Claim(hotel="宿适精选酒店（上海虹桥国展中心店）", attribute="price", value=153, source="分析段"),
    Claim(hotel="上海埕前假日酒店（大场镇地铁站店）", attribute="price", value=184, source="方案二"),
    Claim(hotel="季朵酒店（上海国际旅游度假区店）", attribute="price", value=202, source="方案一"),
    Claim(hotel="宿适精选酒店（上海虹桥国展中心店）", attribute="score", value=4.2, source="对比表"),
    Claim(hotel="上海埕前假日酒店（大场镇地铁站店）", attribute="score", value=4.6, source="对比表"),
    Claim(hotel="季朵酒店（上海国际旅游度假区店）", attribute="score", value=5.0, source="对比表"),
    Claim(hotel="宿适精选酒店（上海虹桥国展中心店）", attribute="facility", value="300家餐厅", source="分析段"),
]


def _judge_payloads(out) -> dict:
    reasons = "\n".join(r for h in out.results for r in h.reasons)
    profile = relevance.extract_user_profile(out.requirement_text)
    audience = relevance.extract_audience_signals((out.analysis_text or "") + "\n" + reasons)
    return {
        "语义": {"text": reasons or out.raw},
        "相关性": {
            "input": {"hotels": INPUT.hotels, "date": INPUT.date, "guests": INPUT.guests},
            "user_profile": profile,
            "results": [r.name for r in out.results],
            "reasons_audience": audience,
            "reasons": reasons,
        },
        "安全性": {"text": out.raw},
        "权衡质量": {"input": INPUT.hotels, "results": [r.name for r in out.results],
                      "reasons": reasons},
    }


def main() -> None:
    out = parse_llm_output(RAW_OUTPUT, INPUT.hotels)

    # 1) 全量确定性层（在线也跑这套，零成本）
    issues = online.run_full_layer(INPUT, out, FACT_DB, CLAIMS)

    # 2) judge 层（有 key 才跑）
    payloads = _judge_payloads(out)
    judge_results = {}
    for dim, payload in payloads.items():
        judge_results[dim] = judge.judge_structured(dim, payload)

    # 3) 报告
    report.render(issues, judge_results, INPUT, out)

    # 4) 展示 judge 提示词样例（供对照你现在的手写 prompt）
    if all(r is None for r in judge_results.values()):
        print("=" * 72)
        print("提示：未检测到 JUDGE_API_KEY / OPENAI_API_KEY / DEEPSEEK_API_KEY。")
        print("judge 层跳过；下面打印'相关性'维度的 judge 提示词模板，供对照：")
        print("=" * 72)
        print(prompts.build_judge_prompt("相关性", payloads["相关性"]))

    # 5) 行为校准示例（合成数据，演示 judge 分 vs 行为 的对齐度计算）
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
