"""光伏阵列持久化：JSON 文件仓库。

只给光伏阵列这一个模块落盘：列表、单条详情、导出三处都从同一份文件读，
进程重启后读到的仍是最后一次保存的结果，不会回退到 seed 的旧值。

写入采用「临时文件 + os.replace」原子替换，避免半写文件被后续请求读到。
"""
from __future__ import annotations

import json
import os
from datetime import date
from typing import Any

from app.seed import SEED_ROWS

MODULE = "pv_array"

# 阵列状态沿投运 → 运行中 → 限功率 → 计划停机依次推进
STATUS_ORDER = ["投运", "运行中", "限功率", "计划停机"]
INITIAL_STATUS = STATUS_ORDER[0]
# 兼容存量记录里遗留的故障停机：允许读出与展示，但不参与状态推进
LEGACY_STATUSES = ["故障停机"]
VALID_STATUSES = STATUS_ORDER + LEGACY_STATUSES

PUBLIC_FIELDS = ["阵列编号", "所属片区", "组件型号", "单块功率", "串联片数", "总装机容量", "投运日期", "阵列状态"]

_DATA_DIR = os.environ.get("PV_DATA_DIR", os.path.join(os.path.dirname(os.path.dirname(__file__)), "data"))
_DATA_PATH = os.path.join(_DATA_DIR, "pv_array.json")


def _clean(value: Any) -> str:
    """提交值统一成去空白的字符串；None 视作空串。"""
    if value is None:
        return ""
    return str(value).strip()


def _normalize_status(row: dict[str, Any]) -> str:
    """存量阵列状态回填：优先沿用原有判定，非法值回退到「投运」。"""
    display = _clean(row.get("阵列状态"))
    if display in VALID_STATUSES:
        return display
    legacy = _clean(row.get("status"))
    if legacy in VALID_STATUSES:
        return legacy
    return INITIAL_STATUS


def _normalize_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """迁移存量阵列：同步双份状态、回填投运日期、按编号去重只留最早一条。"""
    normalized: list[dict[str, Any]] = []
    seen_codes: set[str] = set()
    today = date.today().isoformat()
    for raw in rows:
        row = dict(raw)
        code = _clean(row.get("阵列编号"))
        # 同一阵列编号的重复存量记录只保留最早一条（文件/seed 中先出现的为准）
        if not code or code in seen_codes:
            continue
        seen_codes.add(code)
        status = _normalize_status(row)
        entry: dict[str, Any] = {"id": int(row.get("id", 0) or 0)}
        for field in PUBLIC_FIELDS:
            if field == "阵列状态":
                continue
            entry[field] = _clean(row.get(field))
        if not entry["投运日期"]:
            entry["投运日期"] = today
        entry["阵列状态"] = status
        # 内部标记仅服务运营概览，不作为对外口径
        entry["status"] = status
        entry["pending"] = bool(row.get("pending")) if status in STATUS_ORDER else True
        entry["abnormal"] = bool(row.get("abnormal")) or status == "故障停机"
        normalized.append(entry)
    normalized.sort(key=lambda item: int(item.get("id", 0)))
    for index, row in enumerate(normalized, start=1):
        row["id"] = index
    return normalized


def _seed_rows() -> list[dict[str, Any]]:
    return [dict(row) for row in SEED_ROWS.get(MODULE, [])]


def load_rows() -> list[dict[str, Any]]:
    """读取落库阵列；文件缺失或损坏时回退到 seed 并立即迁移落盘。"""
    rows: list[dict[str, Any]] | None = None
    try:
        with open(_DATA_PATH, encoding="utf-8") as handle:
            payload = json.load(handle)
        if isinstance(payload, list):
            rows = payload
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        rows = None
    if rows is None:
        rows = _seed_rows()
    rows = _normalize_rows(rows)
    persist_rows(rows)
    return rows


def persist_rows(rows: list[dict[str, Any]]) -> None:
    """把当前阵列全量写到同一份落库文件，供列表/详情/导出共用。"""
    os.makedirs(_DATA_DIR, exist_ok=True)
    tmp_path = f"{_DATA_PATH}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as handle:
        json.dump(rows, handle, ensure_ascii=False, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp_path, _DATA_PATH)


def serialize(row: dict[str, Any]) -> dict[str, Any]:
    """对外统一口径：三处读到的字段完全一致，内部标记不外泄。"""
    return {field: _clean(row.get(field)) or None for field in PUBLIC_FIELDS} | {"id": int(row.get("id", 0))}
