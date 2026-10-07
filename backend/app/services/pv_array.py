"""光伏阵列业务规则：字段校验、编号去重、状态流转与存量回填都收在这里。

持久化口径：列表、单条详情、导出三处都直接读 store 里的同一份记录，
任何写入（登记 / 修改 / 状态推进）落库后所有读口径立即一致，不存在缓存层。
"""
from __future__ import annotations

from datetime import date

from typing import Any

from app.store import store

MODULE = "pv_array"
REQUIRED_FIELDS = ["阵列编号", "所属片区", "组件型号"]
# 阵列状态只能沿投运 → 运行中 → 限功率 → 计划停机依次推进，禁止跨档、回退。
STATUS_ORDER = ["投运", "运行中", "限功率", "计划停机"]
# 每个动作只代表“向下一档推进”，动作名沿用页面既有叫法。
ACTION_RULES = {
    "并网运行": "运行中",
    "降功率运行": "限功率",
    "申请停机": "计划停机",
}
# 除必填项外允许保存的业务字段；阵列状态由动作推进，不接受表单直接改。
OPTIONAL_FIELDS = ["单块功率", "串联片数", "总装机容量", "投运日期"]
PERSIST_FIELDS = REQUIRED_FIELDS + OPTIONAL_FIELDS


def _today() -> date | None:
    """隔离今天的取值，方便按投运日期回填时测试。"""
    return date.today()


def _parse_date(value: Any) -> date | None:
    """投运日期按 YYYY-MM-DD 解析，解析不了就视为日期缺失。"""
    if not value:
        return None
    try:
        return date.fromisoformat(str(value).strip()[:10])
    except ValueError:
        return None


def _sync_flags(entry: dict[str, Any]) -> None:
    """阵列状态变化后同步 pending / abnormal，运营概览读到的就是最新结果。"""
    status = entry.get("status")
    entry["pending"] = status in {"投运", "运行中", "限功率"}
    entry["abnormal"] = status == "限功率"
    entry["阵列状态"] = status


def backfill_legacy_rows(today: date | None = None) -> None:
    """兼容既有阵列记录：补齐状态机需要的字段。

    - 已经带合法 status 的（含旧版运行中/限功率/计划停机）原样沿用，过往判定不动；
    - status 缺失或认不出来的存量阵列，按投运日期回填：投运日期在今天（含）
      以前视为已运行，否则按刚投运处理；
    - 同步补齐展示用的「阵列状态」与 pending / abnormal 标志，
      保证列表、详情、导出读到同一份值。
    """
    today = today or _today()
    for entry in store.rows(MODULE):
        status = entry.get("status")
        if status not in STATUS_ORDER:
            commissioned = _parse_date(entry.get("投运日期"))
            status = "运行中" if commissioned is not None and commissioned <= today else "投运"
            entry["status"] = status
        _sync_flags(entry)


class PvArrayService:
    def __init__(self) -> None:
        # store 是进程级单例；构造函数可能被多次调用，回填必须幂等。
        backfill_legacy_rows()

    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("阵列编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def _find_by_code(self, code: str) -> dict[str, Any] | None:
        for row in store.rows(MODULE):
            if str(row.get("阵列编号") or "").strip() == code:
                return row
        return None

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        code = str(values["阵列编号"]).strip()
        # 同一阵列编号只认最早登记的一条；后来的原样拒收，不覆盖也不追加。
        if self._find_by_code(code) is not None:
            return None, [f"阵列编号「{code}」已登记，重复提交已拒收，以最早一条为准"]
        rows = store.rows(MODULE)
        entry: dict[str, Any] = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        for field in PERSIST_FIELDS:
            entry[field] = values.get(field)
        entry["status"] = STATUS_ORDER[0]
        _sync_flags(entry)
        rows.append(entry)
        return entry, []

    def update_entry(
        self, entry_id: int, values: dict[str, Any]
    ) -> tuple[dict[str, Any] | None, list[str]]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, [f"光伏阵列 {entry_id} 不存在或已归档"]
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        code = str(values["阵列编号"]).strip()
        holder = self._find_by_code(code)
        if holder is not None and int(holder.get("id", 0)) != entry_id:
            return None, [f"阵列编号「{code}」已登记，重复提交已拒收，以最早一条为准"]
        # 必填与可选字段逐项落库；总装机容量在 PERSIST_FIELDS 里，改动必然写回。
        for field in PERSIST_FIELDS:
            entry[field] = values.get(field)
        _sync_flags(entry)
        return entry, []

    def status_summary(self) -> dict[str, int]:
        """按当前状态统计阵列数，供页面「运行/限电/停机」卡片使用。"""
        summary = {status: 0 for status in STATUS_ORDER}
        for row in store.rows(MODULE):
            status = row.get("status")
            if status in summary:
                summary[status] += 1
        return summary

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"光伏阵列 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于光伏阵列可执行范围"
        current = entry.get("status")
        if current not in STATUS_ORDER:
            return None, f"当前状态「{current}」不在允许的状态序列里，无法推进"
        target = ACTION_RULES[action]
        current_index = STATUS_ORDER.index(current)
        target_index = STATUS_ORDER.index(target)
        # 只准走到紧邻的下一档：跨档、回退、重复停在同一档都拦下。
        if target_index != current_index + 1:
            if target_index <= current_index:
                return None, f"阵列状态只能沿{'→'.join(STATUS_ORDER)}向前推进，不能回退或重复停在「{current}」"
            return None, f"不能从「{current}」直接跳到「{target}」，请先推进到「{STATUS_ORDER[current_index + 1]}」"
        entry["status"] = target
        _sync_flags(entry)
        return entry, f"光伏阵列已{action}，状态推进为「{target}」"
