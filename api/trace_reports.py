"""字段追溯报告归档：每次成功的追溯自动落盘，可列表/回看/删除。

一次追溯要跑 2-4 分钟的 agent loop，结果必须可沉淀——这是"追溯报告 → wiki 业务场景页/
需求文档草稿"的存储底座。存储为 ~/.adalflow/trace_reports/<id>.json（Docker volume 内，
镜像重建不丢），每份含完整 markdown + 工具调用轨迹。
"""

import json
import logging
import os
import re
import secrets
import time

logger = logging.getLogger(__name__)

_ID_RE = re.compile(r"^[0-9]+_[0-9a-f]+$")


def _dir() -> str:
    try:
        from adalflow.utils import get_adalflow_default_root_path
        root = get_adalflow_default_root_path()
    except Exception:
        root = os.path.join(os.path.expanduser("~"), ".adalflow")
    d = os.path.join(root, "trace_reports")
    os.makedirs(d, exist_ok=True)
    return d


def save_report(system: str, query: str, language: str, result: dict) -> str:
    """归档一次追溯结果，返回报告 id。"""
    rid = f"{int(time.time() * 1000)}_{secrets.token_hex(3)}"
    doc = {
        "id": rid, "system": system, "query": query, "language": language,
        "created_at": int(time.time() * 1000),
        "markdown": result.get("markdown") or "",
        "repos": result.get("repos") or [],
        "trace": result.get("trace") or [],
    }
    with open(os.path.join(_dir(), f"{rid}.json"), "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False)
    return rid


def list_reports(system: str = None, limit: int = 50) -> list:
    """报告元信息列表（不含 markdown 正文），新→旧。"""
    out = []
    for fn in os.listdir(_dir()):
        if not fn.endswith(".json"):
            continue
        try:
            with open(os.path.join(_dir(), fn), "r", encoding="utf-8") as f:
                d = json.load(f)
        except Exception:
            continue
        if system and d.get("system") != system:
            continue
        out.append({
            "id": d.get("id"), "system": d.get("system"), "query": d.get("query"),
            "created_at": d.get("created_at") or 0, "repos": d.get("repos") or [],
            "steps": sum(len(t.get("steps") or []) for t in (d.get("trace") or [])),
        })
    out.sort(key=lambda x: x["created_at"], reverse=True)
    return out[:limit]


def _path_of(report_id: str) -> str:
    """id 校验 + 路径拼接（id 来自 URL，防目录穿越）。非法 id 返回 ''。"""
    if not _ID_RE.fullmatch(report_id or ""):
        return ""
    return os.path.join(_dir(), f"{report_id}.json")


def get_report(report_id: str) -> dict:
    fp = _path_of(report_id)
    if not fp or not os.path.isfile(fp):
        return {}
    try:
        with open(fp, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def delete_report(report_id: str) -> bool:
    fp = _path_of(report_id)
    if not fp or not os.path.isfile(fp):
        return False
    os.remove(fp)
    return True
