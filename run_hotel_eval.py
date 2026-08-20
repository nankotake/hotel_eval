"""run_hotel_eval.py —— 酒店推荐评测入口

用法：
    python run_hotel_eval.py

可选：配置 judge（LLM-as-judge）环境变量后会自动启用：
    JUDGE_API_KEY  （或 OPENAI_API_KEY / DEEPSEEK_API_KEY）
    JUDGE_BASE_URL （DeepSeek 等 OpenAI 兼容端点）
    JUDGE_MODEL    （默认 gpt-4o-mini）

评测基础数据（酒店信息/入住条件/用户画像）在 hotel_eval/data/eval_case.json，
与 LLM 输出无关，由评测方提供。
"""

import sys

# Windows GBK 控制台兜底：报告含 ✓/✗ 等非 GBK 字符，强制 UTF-8 输出
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from hotel_eval.demo import main

if __name__ == "__main__":
    main()
