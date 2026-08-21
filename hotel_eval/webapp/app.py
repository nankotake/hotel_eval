"""webapp —— hotel_eval 可视化界面后端（FastAPI）

提供 REST 接口，让前端管理 单case / 评测集 / 评测记录 / 报告详情，并触发单次或批量评测。
静态前端文件在 webapp/static/ 下，由 / 路由返回。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .. import engine, store
from ..casefile import build_case, build_output
from ..engine import RunResult

app = FastAPI(title="hotel_eval 可视化界面", version="1.0.0")

# 允许本地前端跨域访问（同源部署时其实不需要，但保留以便独立调试）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

STATIC_DIR = __import__("os").path.join(__import__("os").path.dirname(__file__), "static")


# --------------------------------------------------------------------------- #
# 请求体模型
# --------------------------------------------------------------------------- #

class ConfigIn(BaseModel):
    judge_api_key: Optional[str] = ""
    judge_base_url: Optional[str] = ""
    judge_model: Optional[str] = ""


class CaseIn(BaseModel):
    case_id: str
    input: Dict[str, Any]
    reference: Dict[str, Any]


class OutputIn(BaseModel):
    case_id: str
    raw: str
    source: str = ""
    note: str = ""
    claims: List[Dict[str, Any]] = []
    output_id: str = ""


class EvalSetIn(BaseModel):
    set_id: str
    name: str = ""
    description: str = ""
    case_ids: List[str] = []


class RunIn(BaseModel):
    case_id: str
    output_id: Optional[str] = None


class RunBatchIn(BaseModel):
    case_ids: Optional[List[str]] = None
    set_id: Optional[str] = None
    # 可选：只跑每个 case 的"第一个"输出（默认跑全部输出）
    first_output_only: bool = False


# --------------------------------------------------------------------------- #
# 辅助
# --------------------------------------------------------------------------- #

def _case_detail(case_id: str) -> dict:
    """返回 case 的完整信息（含其输出），供详情页/编辑表单回填。"""
    for c in store.get_cases():
        if c.case_id == case_id:
            outputs = [o.to_dict() for o in store.get_case_outputs(case_id)]
            return {
                "case": c.to_dict(),
                "fact_count": len(c.reference.fact_db),
                "outputs": outputs,
            }
    raise HTTPException(status_code=404, detail=f"case '{case_id}' 不存在")


def _case_list() -> List[dict]:
    """case 列表（带摘要：选择酒店、条件、事实数、输出数）。"""
    outputs = store.get_outputs()
    by_case: Dict[str, int] = {}
    for o in outputs:
        by_case[o.case_id] = by_case.get(o.case_id, 0) + 1
    out = []
    for c in store.get_cases():
        inp = c.input
        out.append({
            "case_id": c.case_id,
            "hotels": inp.hotels,
            "date": inp.date,
            "guests": inp.guests,
            "nights": inp.nights,
            "region": inp.region,
            "budget": inp.budget,
            "fact_count": len(c.reference.fact_db),
            "profile": c.reference.profile,
            "output_count": by_case.get(c.case_id, 0),
        })
    return out


def _eval_set_list() -> List[dict]:
    """评测集列表（带 case 数量与名称快照）。"""
    case_map = {c.case_id: c for c in store.get_cases()}
    sets = []
    for s in store.get_eval_sets():
        ids = s.get("case_ids", [])
        sets.append({
            "set_id": s.get("set_id"),
            "name": s.get("name", ""),
            "description": s.get("description", ""),
            "case_count": len(ids),
            "case_ids": ids,
            "case_names": [case_map.get(i, {}).input.hotels[0] if i in case_map and case_map[i].input.hotels else i for i in ids],
        })
    return sets


def _record_from_result(result: RunResult) -> dict:
    """把一次评测结果落成一条评测记录。"""
    c = result.conclusion()
    rec = {
        "record_id": f"rec-{uuid.uuid4().hex[:12]}",
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "case_id": result.case_id,
        "source": result.source,
        "gate": c["gate"],
        "issue_count": len(result.issues),
        "by_layer": c["by_layer"],
        "judge_enabled": c["judge_enabled"],
        "judge_summary": result.summary()["judge"],
        "report": result.to_dict(),
    }
    store.add_record(rec)
    return rec


def _run_one(case_id: str, output_id: Optional[str]) -> dict:
    """跑单个 case 的一份输出，落库并返回记录摘要。"""
    case = next((c for c in store.get_cases() if c.case_id == case_id), None)
    if case is None:
        raise HTTPException(status_code=404, detail=f"case '{case_id}' 不存在")
    outputs = store.get_case_outputs(case_id)
    if not outputs:
        raise HTTPException(status_code=400, detail=f"case '{case_id}' 没有 LLM 输出，先添加输出")
    if output_id:
        rec = next((o for o in outputs if o.output_id == output_id), None)
        if rec is None:
            raise HTTPException(status_code=404, detail=f"output '{output_id}' 不存在于 case '{case_id}'")
    else:
        rec = outputs[0]
    result = engine.run_case_eval(case, rec, judge_config=store.get_config())
    saved = _record_from_result(result)
    return saved


# --------------------------------------------------------------------------- #
# 配置
# --------------------------------------------------------------------------- #

@app.get("/api/config")
def get_config():
    cfg = store.get_config()
    # 不回传完整 key，只回传"是否已配置"，避免泄露
    return {
        "has_key": bool(cfg["judge_api_key"]),
        "judge_base_url": cfg["judge_base_url"],
        "judge_model": cfg["judge_model"],
    }


@app.post("/api/config")
def set_config(body: ConfigIn):
    store.save_config(body.model_dump())
    cfg = store.get_config()
    return {
        "has_key": bool(cfg["judge_api_key"]),
        "judge_base_url": cfg["judge_base_url"],
        "judge_model": cfg["judge_model"],
    }


@app.post("/api/config/test")
def test_config(body: ConfigIn):
    """用当前配置试调一次 judge，验证 key/端点可用。"""
    store.save_config(body.model_dump())
    client, model = engine.build_judge_client(store.get_config())
    if client is None:
        return {"ok": False, "detail": "未配置 API key，无法测试"}
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "ping"}],
            temperature=0.0,
        )
        return {"ok": True, "detail": f"模型 {model} 连通正常：{resp.choices[0].message.content[:60]}"}
    except Exception as exc:
        return {"ok": False, "detail": f"测试失败: {exc}"}


# --------------------------------------------------------------------------- #
# Cases（单 case 管理）
# --------------------------------------------------------------------------- #

@app.get("/api/cases")
def list_cases():
    return _case_list()


@app.get("/api/cases/{case_id}")
def get_case(case_id: str):
    return _case_detail(case_id)


@app.post("/api/cases")
def create_case(body: CaseIn):
    if not body.case_id.strip():
        raise HTTPException(status_code=400, detail="case_id 不能为空")
    if any(c.case_id == body.case_id for c in store.get_cases()):
        raise HTTPException(status_code=409, detail=f"case '{body.case_id}' 已存在")
    store.upsert_case(build_case(body.model_dump()))
    return {"ok": True, "case_id": body.case_id}


@app.put("/api/cases/{case_id}")
def update_case(case_id: str, body: CaseIn):
    if body.case_id != case_id:
        raise HTTPException(status_code=400, detail="case_id 不可更改")
    if not any(c.case_id == case_id for c in store.get_cases()):
        raise HTTPException(status_code=404, detail=f"case '{case_id}' 不存在")
    store.upsert_case(build_case(body.model_dump()))
    return {"ok": True, "case_id": case_id}


@app.delete("/api/cases/{case_id}")
def delete_case(case_id: str):
    store.delete_case(case_id)
    return {"ok": True, "case_id": case_id}


# --------------------------------------------------------------------------- #
# LLM 输出
# --------------------------------------------------------------------------- #

@app.get("/api/cases/{case_id}/outputs")
def list_outputs(case_id: str):
    if not any(c.case_id == case_id for c in store.get_cases()):
        raise HTTPException(status_code=404, detail=f"case '{case_id}' 不存在")
    return [o.to_dict() for o in store.get_case_outputs(case_id)]


@app.post("/api/cases/{case_id}/outputs")
def create_output(case_id: str, body: OutputIn):
    if body.case_id != case_id:
        raise HTTPException(status_code=400, detail="case_id 不匹配")
    if not any(c.case_id == case_id for c in store.get_cases()):
        raise HTTPException(status_code=404, detail=f"case '{case_id}' 不存在")
    if not body.output_id:
        body.output_id = f"{case_id}::out-{uuid.uuid4().hex[:8]}"
    store.upsert_output(build_output(body.model_dump()))
    return {"ok": True, "output_id": body.output_id}


@app.put("/api/outputs/{output_id}")
def update_output(output_id: str, body: OutputIn):
    if body.output_id != output_id:
        raise HTTPException(status_code=400, detail="output_id 不可更改")
    store.upsert_output(build_output(body.model_dump()))
    return {"ok": True, "output_id": output_id}


@app.delete("/api/outputs/{output_id}")
def delete_output(output_id: str):
    store.delete_output(output_id)
    return {"ok": True, "output_id": output_id}


# --------------------------------------------------------------------------- #
# 评测集
# --------------------------------------------------------------------------- #

@app.get("/api/eval-sets")
def list_eval_sets():
    return _eval_set_list()


@app.get("/api/eval-sets/{set_id}")
def get_eval_set(set_id: str):
    s = next((x for x in store.get_eval_sets() if x.get("set_id") == set_id), None)
    if s is None:
        raise HTTPException(status_code=404, detail=f"set '{set_id}' 不存在")
    case_map = {c.case_id: c for c in store.get_cases()}
    ids = s.get("case_ids", [])
    s = dict(s)
    s["case_details"] = [
        {"case_id": i, "hotels": case_map[i].input.hotels if i in case_map else []}
        for i in ids
    ]
    return s


@app.post("/api/eval-sets")
def create_eval_set(body: EvalSetIn):
    if not body.set_id.strip():
        raise HTTPException(status_code=400, detail="set_id 不能为空")
    if any(x.get("set_id") == body.set_id for x in store.get_eval_sets()):
        raise HTTPException(status_code=409, detail=f"set '{body.set_id}' 已存在")
    store.upsert_eval_set(body.model_dump())
    return {"ok": True, "set_id": body.set_id}


@app.put("/api/eval-sets/{set_id}")
def update_eval_set(set_id: str, body: EvalSetIn):
    if body.set_id != set_id:
        raise HTTPException(status_code=400, detail="set_id 不可更改")
    store.upsert_eval_set(body.model_dump())
    return {"ok": True, "set_id": set_id}


@app.delete("/api/eval-sets/{set_id}")
def delete_eval_set(set_id: str):
    store.delete_eval_set(set_id)
    return {"ok": True, "set_id": set_id}


# --------------------------------------------------------------------------- #
# 评测记录 + 报告详情
# --------------------------------------------------------------------------- #

@app.get("/api/records")
def list_records():
    records = store.get_records()
    records.sort(key=lambda r: r.get("timestamp", ""), reverse=True)
    # 列表只返回摘要，不含完整 report，减少体积
    return [{k: v for k, v in r.items() if k != "report"} for r in records]


@app.get("/api/records/{record_id}")
def get_record(record_id: str):
    r = store.get_record(record_id)
    if r is None:
        raise HTTPException(status_code=404, detail=f"record '{record_id}' 不存在")
    return r


@app.delete("/api/records/{record_id}")
def delete_record(record_id: str):
    store.delete_record(record_id)
    return {"ok": True, "record_id": record_id}


@app.post("/api/records/clear")
def clear_records():
    store.clear_records()
    return {"ok": True}


# --------------------------------------------------------------------------- #
# 触发评测（单次 / 批量）
# --------------------------------------------------------------------------- #

@app.post("/api/eval/run")
def run_single(body: RunIn):
    try:
        saved = _run_one(body.case_id, body.output_id)
    except HTTPException:
        raise
    return {k: v for k, v in saved.items() if k != "report"}


@app.post("/api/eval/run-batch")
def run_batch(body: RunBatchIn):
    case_ids: List[str] = []
    if body.set_id:
        s = next((x for x in store.get_eval_sets() if x.get("set_id") == body.set_id), None)
        if s is None:
            raise HTTPException(status_code=404, detail=f"set '{body.set_id}' 不存在")
        case_ids = s.get("case_ids", [])
    elif body.case_ids:
        case_ids = body.case_ids
    else:
        case_ids = [c.case_id for c in store.get_cases()]

    results = []
    for case_id in case_ids:
        case = next((c for c in store.get_cases() if c.case_id == case_id), None)
        if case is None:
            results.append({"case_id": case_id, "status": "skipped", "reason": "case 不存在"})
            continue
        outputs = store.get_case_outputs(case_id)
        if not outputs:
            results.append({"case_id": case_id, "status": "skipped", "reason": "无 LLM 输出"})
            continue
        to_run = outputs[:1] if body.first_output_only else outputs
        for o in to_run:
            result = engine.run_case_eval(case, o, judge_config=store.get_config())
            saved = _record_from_result(result)
            results.append({
                "case_id": case_id,
                "output_id": o.output_id,
                "record_id": saved["record_id"],
                "status": "done",
                "gate": saved["gate"],
                "issue_count": saved["issue_count"],
            })
    passed = sum(1 for r in results if r.get("gate") == "PASS")
    done = sum(1 for r in results if r.get("status") == "done")
    return {"total": len(results), "done": done, "passed": passed, "results": results}


# --------------------------------------------------------------------------- #
# 前端静态资源
# --------------------------------------------------------------------------- #

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def index():
    return FileResponse(__import__("os").path.join(STATIC_DIR, "index.html"))
