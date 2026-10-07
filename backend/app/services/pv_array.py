"""光伏阵列业务规则：登记校验、容量落库、编号去重与顺序状态机。

对外只暴露统一口径的字段（见 persistence.serialize），列表、单条详情、导出
都经过同一序列化，保证三处读到的是同一份数据。
"""
from __future__ import annotations

from typing import Any

from app import persistence
from app.store import store

MODULE = persistence.MODULE
REQUIRED_FIELDS = ["阵列编号", "所属片区", "组件型号"]
# 除必填三项外，登记/修改时一并落库的可编辑字段
EDITABLE_FIELDS = REQUIRED_FIELDS + ["单块功率", "串联片数", "总装机容量", "投运日期"]
STATUS_ORDER = persistence.STATUS_ORDER
# 每个动作只能从当前档进入紧邻的下一档，不允许跨档
NEXT_ACTIONS = {
    "投运": ("确认投运", "运行中"),
    "运行中": ("降功率运行", "限功率"),
    "限功率": ("申请停机", "计划停机"),
}


class DomainError(Exception):
    """业务校验失败：携带 HTTP 状态码与可读说明，路由层原样拒收。"""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


def _clean(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _derive_flags(status: str) -> tuple[bool, bool]:
    """新状态写入后同步运营概览所需标记。"""
    pending = status in ("投运", "限功率")
    abnormal = status in ("限功率", "故障停机")
    return pending, abnormal


class PvArrayService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        area: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int, dict[str, int]]:
        rows = store.rows(MODULE)
        stats = {name: 0 for name in STATUS_ORDER}
        for row in rows:
            name = row.get("阵列状态")
            if name in stats:
                stats[name] += 1

        filtered = rows
        if keyword:
            filtered = [row for row in filtered if keyword in str(row.get("阵列编号", ""))]
        if area:
            filtered = [row for row in filtered if area in str(row.get("所属片区", ""))]
        if status:
            filtered = [row for row in filtered if row.get("阵列状态") == status]

        total = len(filtered)
        start = max(page - 1, 0) * size
        page_rows = [persistence.serialize(row) for row in filtered[start:start + size]]
        return page_rows, total, stats

    def export_entries(
        self,
        *,
        keyword: str | None = None,
        area: str | None = None,
        status: str | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        # 导出与列表同一筛选口径、同一份序列化，条数不会错位
        items, total, _ = self.list_entries(keyword=keyword, area=area, status=status, page=1, size=10_000)
        return items, total

    def get_entry(self, entry_id: int) -> dict[str, Any]:
        row = store.find(MODULE, entry_id)
        if row is None:
            raise DomainError(404, f"光伏阵列 {entry_id} 不存在或已归档")
        return persistence.serialize(row)

    def create_entry(self, values: dict[str, Any]) -> dict[str, Any]:
        cleaned = self._clean_values(values)
        missing = [field for field in REQUIRED_FIELDS if not cleaned[field]]
        if missing:
            raise DomainError(400, f"缺少必填字段：{'、'.join(missing)}，不予登记")

        rows = store.rows(MODULE)
        code = cleaned["阵列编号"]
        # 同一阵列编号重复提交：只留最早一条，后来的原样拒收
        if any(_clean(row.get("阵列编号")) == code for row in rows):
            raise DomainError(409, f"阵列编号 {code} 已登记，重复提交已拒收，仅保留最早一条记录")

        entry: dict[str, Any] = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update(cleaned)
        if not entry["投运日期"]:
            entry["投运日期"] = ""
        entry["阵列状态"] = STATUS_ORDER[0]
        entry["status"] = STATUS_ORDER[0]
        entry["pending"], entry["abnormal"] = _derive_flags(STATUS_ORDER[0])
        rows.append(entry)
        store.persist(MODULE)
        return persistence.serialize(entry)

    def update_entry(self, entry_id: int, values: dict[str, Any]) -> dict[str, Any]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            raise DomainError(404, f"光伏阵列 {entry_id} 不存在或已归档")

        # 只覆盖本次实际提交的可编辑字段，兼容只改容量等部分字段的既有记录；
        # 显式提交的空串才算清空，未提交的字段沿用原值
        submitted = {
            field: _clean(values[field])
            for field in EDITABLE_FIELDS
            if field in values
        }
        merged = {field: _clean(entry.get(field)) for field in EDITABLE_FIELDS}
        merged.update(submitted)

        missing = [field for field in REQUIRED_FIELDS if not merged[field]]
        if missing:
            raise DomainError(400, f"缺少必填字段：{'、'.join(missing)}，不予保存")

        code = merged["阵列编号"]
        if any(
            int(row.get("id", 0)) != entry_id and _clean(row.get("阵列编号")) == code
            for row in store.rows(MODULE)
        ):
            raise DomainError(409, f"阵列编号 {code} 已被其他阵列占用，修改已拒收")

        # 总装机容量等可编辑字段直接覆盖落库，不留旧值
        entry.update(merged)
        store.persist(MODULE)
        return persistence.serialize(entry)

    def advance_status(self, entry_id: int, action: str) -> tuple[dict[str, Any], str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            raise DomainError(404, f"光伏阵列 {entry_id} 不存在或已归档")

        current = _clean(entry.get("阵列状态"))
        rule = NEXT_ACTIONS.get(current)
        if rule is None:
            raise DomainError(409, f"阵列当前为「{current}」，已到末档或为存量历史状态，不允许再变更")
        allowed_action, target = rule
        if action != allowed_action:
            raise DomainError(409, f"「{current}」状态只允许执行「{allowed_action}」，动作「{action}」跨档或非法，已拒收")

        index = STATUS_ORDER.index(current)
        if STATUS_ORDER[index + 1] != target:
            # 双保险：目标必须是紧邻下一档
            raise DomainError(409, "阵列状态只允许沿投运、运行中、限功率、计划停机逐档推进，不允许跨档")

        entry["阵列状态"] = target
        entry["status"] = target
        entry["pending"], entry["abnormal"] = _derive_flags(target)
        store.persist(MODULE)
        return persistence.serialize(entry), f"光伏阵列已{allowed_action}，状态更新为「{target}」"

    def _clean_values(self, values: dict[str, Any]) -> dict[str, str]:
        return {field: _clean(values.get(field)) for field in EDITABLE_FIELDS}
