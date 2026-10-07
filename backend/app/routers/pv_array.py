"""光伏阵列接口：登记、修改、查询、导出与状态推进共用同一份底层记录。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.pv_array import PvArrayService, STATUS_ORDER

router = APIRouter(prefix="/api/pv_array", tags=["光伏阵列"])

service = PvArrayService()

LIST_FIELDS = ["阵列编号", "所属片区", "组件型号", "单块功率", "串联片数", "总装机容量", "投运日期", "阵列状态"]
STATUSES = STATUS_ORDER


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按阵列编号检索"),
    status: str | None = Query(default=None, description="投运、运行中、限功率、计划停机"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按阵列编号与状态过滤光伏阵列列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


# 注意：/export、/stats 是固定路径，必须排在 /{entry_id} 前面，
# 否则会被当成阵列编号 "export" 走单条详情，导出条数随之错位。
@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出光伏阵列清单：与列表、详情读同一个数据源，返回当前全量记录。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "pv_array", "total": total, "items": items}


@router.get("/stats")
def status_stats() -> dict[str, Any]:
    """各状态阵列数量，供页面状态卡片与运营概览核对。"""
    return {"module": "pv_array", "statuses": service.status_summary()}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条光伏阵列明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"光伏阵列 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条光伏阵列：阵列编号、所属片区、组件型号缺一不可；
    同一阵列编号重复提交只保留最早一条，后来的原样拒收。"""
    entry, errors = service.create_entry(payload.values)
    if errors:
        return ActionResult(ok=False, message="；".join(errors))
    return ActionResult(ok=True, message="光伏阵列已登记", entry=entry)


@router.put("/{entry_id}", response_model=ActionResult)
def update_entry(entry_id: int, payload: EntryPayload) -> ActionResult:
    """修改一条光伏阵列：必填项仍缺一不可，总装机容量等字段逐项写回底层记录。"""
    entry, errors = service.update_entry(entry_id, payload.values)
    if errors:
        return ActionResult(ok=False, message="；".join(errors))
    return ActionResult(ok=True, message="光伏阵列修改已保存", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条光伏阵列推进状态：只允许沿投运→运行中→限功率→计划停机走到下一档。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
