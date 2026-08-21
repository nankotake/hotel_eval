"""store.py —— JSON 持久化层（cases / outputs / eval_sets / records / config）

Web 界面读写数据的统一入口。沿用现有 data/*.json 格式：
  - eval_cases.json    入参 + 参考信息（一项 = 一个 case）
  - llm_outputs.json   评测对象（一项 = 一份 LLM 输出，按 case_id 挂到 case）
新增：
  - eval_sets.json     评测集（一组 case_id）
  - eval_records.json  评测记录（一次运行的结果）
  - config.json        judge 配置（api_key / base_url / model）
"""

from __future__ import annotations

import json
import os
from typing import Dict, List, Optional

from .casefile import (
    DEFAULT_CASES_PATH,
    DEFAULT_OUTPUTS_PATH,
    EvalCase,
    LLMOutputRecord,
    load_cases,
    load_llm_outputs,
)

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
SETS_PATH = os.path.join(DATA_DIR, "eval_sets.json")
RECORDS_PATH = os.path.join(DATA_DIR, "eval_records.json")
CONFIG_PATH = os.path.join(DATA_DIR, "config.json")

_DEFAULT_CONFIG = {
    "judge_api_key": "",
    "judge_base_url": "",
    "judge_model": "gpt-4o-mini",
}


# --------------------------------------------------------------------------- #
# 通用读写
# --------------------------------------------------------------------------- #

def _read_json(path: str, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _write_json(path: str, data) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# --------------------------------------------------------------------------- #
# cases
# --------------------------------------------------------------------------- #

def get_cases() -> List[EvalCase]:
    return load_cases()


def save_cases(cases: List[EvalCase]) -> None:
    _write_json(DEFAULT_CASES_PATH, [c.to_dict() for c in cases])


def upsert_case(case: EvalCase) -> None:
    cases = get_cases()
    for i, c in enumerate(cases):
        if c.case_id == case.case_id:
            cases[i] = case
            break
    else:
        cases.append(case)
    save_cases(cases)


def delete_case(case_id: str) -> None:
    cases = [c for c in get_cases() if c.case_id != case_id]
    save_cases(cases)
    # 一并清掉该 case 的输出、评测集引用
    delete_case_outputs(case_id)
    sets = get_eval_sets()
    for s in sets:
        if case_id in s.get("case_ids", []):
            s["case_ids"] = [x for x in s["case_ids"] if x != case_id]
    save_eval_sets(sets)


# --------------------------------------------------------------------------- #
# llm outputs
# --------------------------------------------------------------------------- #

def get_outputs() -> List[LLMOutputRecord]:
    outputs = load_llm_outputs()
    # 缺省给没有 output_id 的旧数据补一个稳定 id
    for o in outputs:
        if not o.output_id:
            o.output_id = f"{o.case_id}::out-{_stable_index(outputs, o)}"
    return outputs


def _stable_index(outputs: List[LLMOutputRecord], target: LLMOutputRecord) -> str:
    """用内容哈希保证旧数据（无 output_id）也能得到稳定的 id。"""
    import hashlib
    return hashlib.md5(f"{target.case_id}:{target.raw}".encode("utf-8")).hexdigest()[:6]


def save_outputs(outputs: List[LLMOutputRecord]) -> None:
    _write_json(DEFAULT_OUTPUTS_PATH, [o.to_dict() for o in outputs])


def get_case_outputs(case_id: str) -> List[LLMOutputRecord]:
    return [o for o in get_outputs() if o.case_id == case_id]


def upsert_output(rec: LLMOutputRecord) -> None:
    outputs = get_outputs()
    if rec.output_id:
        for i, o in enumerate(outputs):
            if o.output_id == rec.output_id:
                outputs[i] = rec
                break
        else:
            outputs.append(rec)
    else:
        outputs.append(rec)
    save_outputs(outputs)


def delete_output(output_id: str) -> None:
    outputs = [o for o in get_outputs() if o.output_id != output_id]
    save_outputs(outputs)


def delete_case_outputs(case_id: str) -> None:
    outputs = [o for o in get_outputs() if o.case_id != case_id]
    save_outputs(outputs)


# --------------------------------------------------------------------------- #
# eval sets
# --------------------------------------------------------------------------- #

def get_eval_sets() -> List[dict]:
    return _read_json(SETS_PATH, [])


def save_eval_sets(sets: List[dict]) -> None:
    _write_json(SETS_PATH, sets)


def upsert_eval_set(s: dict) -> None:
    sets = get_eval_sets()
    for i, x in enumerate(sets):
        if x.get("set_id") == s.get("set_id"):
            sets[i] = s
            break
    else:
        sets.append(s)
    save_eval_sets(sets)


def delete_eval_set(set_id: str) -> None:
    sets = [s for s in get_eval_sets() if s.get("set_id") != set_id]
    save_eval_sets(sets)


# --------------------------------------------------------------------------- #
# eval records
# --------------------------------------------------------------------------- #

def get_records() -> List[dict]:
    return _read_json(RECORDS_PATH, [])


def add_record(record: dict) -> dict:
    records = get_records()
    records.append(record)
    _write_json(RECORDS_PATH, records)
    return record


def get_record(record_id: str) -> Optional[dict]:
    for r in get_records():
        if r.get("record_id") == record_id:
            return r
    return None


def delete_record(record_id: str) -> None:
    records = [r for r in get_records() if r.get("record_id") != record_id]
    _write_json(RECORDS_PATH, records)


def clear_records() -> None:
    _write_json(RECORDS_PATH, [])


# --------------------------------------------------------------------------- #
# config
# --------------------------------------------------------------------------- #

def get_config() -> dict:
    cfg = _read_json(CONFIG_PATH, {})
    return {**_DEFAULT_CONFIG, **cfg}


def save_config(cfg: dict) -> None:
    cur = get_config()
    cur.update({k: v for k, v in cfg.items() if k in _DEFAULT_CONFIG})
    _write_json(CONFIG_PATH, cur)
