"""数据仓库：光伏阵列走 JSON 落盘，其余模块仍为内存示例数据。

真实项目里这里会换成数据库访问层；光伏阵列的登记、改容量与状态流转都必须
重启不丢，所以该模块单独由 app.persistence 负责读写同一份文件。
"""
from __future__ import annotations

from typing import Any

from app import persistence
from app.seed import SEED_ROWS

PV_MODULE = persistence.MODULE


class Store:
    def __init__(self) -> None:
        self._tables: dict[str, list[dict[str, Any]]] = {
            name: [dict(row) for row in rows] for name, rows in SEED_ROWS.items()
        }
        # 光伏阵列以落库文件为准，覆盖 seed：刷新/重启后读到最后一次保存
        self._tables[PV_MODULE] = persistence.load_rows()

    def module_names(self) -> list[str]:
        return sorted(self._tables)

    def rows(self, module: str) -> list[dict[str, Any]]:
        return self._tables.setdefault(module, [])

    def find(self, module: str, entry_id: int) -> dict[str, Any] | None:
        for row in self.rows(module):
            if int(row.get("id", 0)) == entry_id:
                return row
        return None

    def persist(self, module: str) -> None:
        """把指定模块当前内存数据写回持久层；目前仅光伏阵列支持。"""
        if module == PV_MODULE:
            persistence.persist_rows(self.rows(module))

    def overview(self) -> dict[str, object]:
        modules: list[dict[str, object]] = []
        for name in self.module_names():
            rows = self.rows(name)
            item: dict[str, object] = {
                "name": name,
                "created": len(rows),
                "pending": sum(1 for row in rows if row.get("pending")),
                "abnormal": sum(1 for row in rows if row.get("abnormal")),
            }
            if name == PV_MODULE:
                # 状态变化要反映到运营概览：按四档状态统计阵列数
                item["statuses"] = {
                    status: sum(1 for row in rows if row.get("阵列状态") == status)
                    for status in persistence.STATUS_ORDER
                }
            modules.append(item)
        cards = [
            {"label": "业务模块", "value": len(modules)},
            {"label": "今日新增", "value": sum(int(item["created"]) for item in modules)},
            {"label": "待处理", "value": sum(int(item["pending"]) for item in modules)},
            {"label": "异常量", "value": sum(int(item["abnormal"]) for item in modules)},
        ]
        return {"cards": cards, "modules": modules}


store = Store()
