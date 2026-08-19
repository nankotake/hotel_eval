"""judge.py —— LLM-as-judge 引擎

职责：把"某个维度"交给 LLM 打分，返回结构化结果 {score, evidence, confidence, self_doubt}。
关键工程点：
  - 事实校验不在这里做（剥离给 consistency 查库）。
  - 单次调用、多维度可分别调；不暴力多次采样，靠 confidence 把模糊样本筛出来转人工。
  - 无 API key 时返回 None（调用方跳过 judge，走确定性层兜底）。
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, Optional

from . import prompts


def _load_client():
    key = (
        os.environ.get("JUDGE_API_KEY")
        or os.environ.get("OPENAI_API_KEY")
        or os.environ.get("DEEPSEEK_API_KEY")
    )
    if not key:
        return None, None, key
    try:
        from openai import OpenAI
    except ImportError:
        return None, None, key
    base_url = os.environ.get("JUDGE_BASE_URL") or None
    model = os.environ.get("JUDGE_MODEL", "gpt-4o-mini")
    kwargs = {"api_key": key}
    if base_url:
        kwargs["base_url"] = base_url
    return OpenAI(**kwargs), model, key


def judge_structured(
    dimension: str,
    payload: Dict[str, Any],
    client=None,
    model: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """对单个维度打分。client/model 可注入（测试用），否则从环境读取。"""
    if client is None:
        client, model, key = _load_client()
        if client is None:
            return None

    prompt = prompts.build_judge_prompt(dimension, payload)
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "user", "content": prompt},
            ],
            temperature=0.0,
        )
        content = resp.choices[0].message.content
    except Exception as exc:
        return {"score": None, "evidence": f"judge 调用失败: {exc}", "confidence": "low", "self_doubt": str(exc)}

    return _parse(content)


def _parse(content: str) -> Dict[str, Any]:
    # 优先整体 JSON 解析
    text = content.strip()
    for candidate in (text, _strip_fence(text)):
        try:
            obj = json.loads(candidate)
            if isinstance(obj, dict) and "score" in obj:
                return {
                    "score": _as_int(obj.get("score")),
                    "evidence": str(obj.get("evidence", "")),
                    "confidence": str(obj.get("confidence", "medium")),
                    "self_doubt": str(obj.get("self_doubt", "")),
                    "raw": content,
                }
        except Exception:
            continue
    # 兜底：正则抓字段
    return {
        "score": _as_int(_grab(r'"score"\s*:\s*(\d+)', text)),
        "evidence": _grab(r'"evidence"\s*:\s*"([^"]*)"', text),
        "confidence": _grab(r'"confidence"\s*:\s*"([^"]*)"', text) or "medium",
        "self_doubt": _grab(r'"self_doubt"\s*:\s*"([^"]*)"', text),
        "raw": content,
    }


def _strip_fence(s: str) -> str:
    s = s.strip()
    s = re.sub(r"^```(?:json)?\s*", "", s)
    s = re.sub(r"\s*```$", "", s)
    return s


def _grab(pattern: str, text: str) -> str:
    m = re.search(pattern, text)
    return m.group(1) if m else ""


def _as_int(v) -> Optional[int]:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None
