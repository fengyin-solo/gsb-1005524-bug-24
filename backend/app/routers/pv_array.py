"""光伏阵列接口：登记、修改、顺序状态流转，列表/详情/导出共用同一份落库数据。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Response

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.pv_array import DomainError, PvArrayService

router = APIRouter(prefix="/api/pv_array", tags=["光伏阵列"])

service = PvArrayService()

STATUSES = ["投运", "运行中", "限功率", "计划停机"]


def _fresh(response: Response) -> Response:
    """列表、详情、导出都不许回显上一版缓存。"""
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


def _reject(error: DomainError) -> HTTPException:
    return HTTPException(status_code=error.status_code, detail=error.message)


@router.get("", response_model=PageResult[dict])
def list_entries(
    response: Response,
    keyword: str | None = Query(default=None, description="按阵列编号检索"),
    area: str | None = Query(default=None, description="按所属片区检索"),
    status: str | None = Query(default=None, description="投运、运行中、限功率、计划停机"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按阵列编号、所属片区与状态过滤光伏阵列列表；没有数据时返回空页，不报错。"""
    _fresh(response)
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total, stats = service.list_entries(keyword=keyword, area=area, status=status, page=page, size=size)
    result = PageResult(items=items, total=total, page=page, size=size)
    result.stats = stats  # type: ignore[attr-defined]
    return result


# 注意：/export 必须排在 /{entry_id} 之前，否则 export 会被当成阵列 id 解析
@router.get("/export")
def export_entries(
    response: Response,
    keyword: str | None = Query(default=None, description="按阵列编号检索"),
    area: str | None = Query(default=None, description="按所属片区检索"),
    status: str | None = Query(default=None, description="投运、运行中、限功率、计划停机"),
) -> dict[str, Any]:
    """导出光伏阵列清单：与列表同一过滤口径，条数即当前清单条数。"""
    _fresh(response)
    items, total = service.export_entries(keyword=keyword, area=area, status=status)
    return {"module": "pv_array", "total": total, "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int, response: Response) -> dict:
    """读取单条光伏阵列明细；不存在时给出可读的错误说明。"""
    _fresh(response)
    try:
        return service.get_entry(entry_id)
    except DomainError as error:
        raise _reject(error) from error


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条光伏阵列：阵列编号、所属片区、组件型号缺一项不许保存。"""
    try:
        entry = service.create_entry(payload.values)
    except DomainError as error:
        return ActionResult(ok=False, message=error.message)
    return ActionResult(ok=True, message="光伏阵列已登记", entry=entry)


@router.put("/{entry_id}", response_model=ActionResult)
def update_entry(entry_id: int, payload: EntryPayload) -> ActionResult:
    """修改一条光伏阵列：总装机容量等字段的改动立即落库，不保留旧值。"""
    try:
        entry = service.update_entry(entry_id, payload.values)
    except DomainError as error:
        return ActionResult(ok=False, message=error.message)
    return ActionResult(ok=True, message="光伏阵列修改已落库", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """沿投运 → 运行中 → 限功率 → 计划停机逐档推进；跨档动作原样拒收。"""
    action = str(payload.values.get("action") or "").strip()
    try:
        entry, message = service.advance_status(entry_id, action)
    except DomainError as error:
        return ActionResult(ok=False, message=error.message)
    return ActionResult(ok=True, message=message, entry=entry)
