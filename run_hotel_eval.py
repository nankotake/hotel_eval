"""run_hotel_eval.py —— 酒店推荐评测入口

用法：
    python run_hotel_eval.py

可选：配置 judge（LLM-as-judge）环境变量后会自动启用：
    JUDGE_API_KEY  （或 OPENAI_API_KEY / DEEPSEEK_API_KEY）
    JUDGE_BASE_URL （DeepSeek 等 OpenAI 兼容端点）
    JUDGE_MODEL    （默认 gpt-4o-mini）
"""

from hotel_eval.demo import main

if __name__ == "__main__":
    main()
