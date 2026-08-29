"""纯 Python 表格数据层 —— 桌面版（PyQt6）与本地 Web 版共享的单一数据源。

设计（2026-08-24 本地 web 开发）：
- SpreadsheetModel（Qt）只负责把 TableData 喂给 Qt 视图（薄适配器）
- 本类不含任何 Qt 依赖，可被 Web 后端直接 import
- 所有表格数据逻辑（稀疏存储、行列、读写、快照）集中于此，改一处两端生效
"""
from __future__ import annotations


class TableData:
    """以稀疏 dict 存储单元格数据。行列默认 100×26。"""

    DEFAULT_ROWS = 100
    DEFAULT_COLS = 26

    def __init__(self):
        self._data: dict[tuple[int, int], str] = {}
        self._row_count = self.DEFAULT_ROWS
        self._col_count = self.DEFAULT_COLS
        self._file_path: str | None = None
        self._file_format: str = ''

    # ------------------------------------------------------------------
    # 读写
    # ------------------------------------------------------------------

    def value(self, row: int, col: int) -> str:
        return self._data.get((row, col), '')

    def set_value(self, row: int, col: int, value: str) -> None:
        value = str(value)
        key = (row, col)
        if value == '':
            self._data.pop(key, None)
        else:
            self._data[key] = value

    def clear(self) -> None:
        """清空所有数据，重置到默认尺寸。"""
        self._data.clear()
        self._row_count = self.DEFAULT_ROWS
        self._col_count = self.DEFAULT_COLS
        self._file_path = None
        self._file_format = ''

    def load_2d(self, matrix: list[list]) -> None:
        """从二维列表加载数据，替换当前内容。"""
        rows = len(matrix)
        cols = max((len(r) for r in matrix), default=0)
        self._data.clear()
        for r, row_data in enumerate(matrix):
            for c, val in enumerate(row_data):
                if val:
                    self._data[(r, c)] = str(val)
        self._row_count = max(rows, self.DEFAULT_ROWS)
        self._col_count = max(cols, self.DEFAULT_COLS)
        self._file_path = None
        self._file_format = ''

    def data_bounds(self) -> tuple[int, int, int, int] | None:
        """有数据区域外接矩形 (r1, c1, r2, c2)。无数据返回 None。"""
        if not self._data:
            return None
        min_r = min(r for r, _ in self._data)
        max_r = max(r for r, _ in self._data)
        min_c = min(c for _, c in self._data)
        max_c = max(c for _, c in self._data)
        return min_r, min_c, max_r, max_c

    def to_2d(self) -> list[list[str]]:
        """导出为二维列表（只含数据区域）。"""
        if not self._data:
            return []
        max_r = max(r for r, _ in self._data) + 1
        max_c = max(c for _, c in self._data) + 1
        matrix = [[''] * max_c for _ in range(max_r)]
        for (r, c), val in self._data.items():
            matrix[r][c] = val
        return matrix

    # ------------------------------------------------------------------
    # 行列操作
    # ------------------------------------------------------------------

    def insert_row(self, position: int) -> None:
        if position < 0 or position > self._row_count:
            return
        new_data = {}
        for (r, c), val in self._data.items():
            new_data[(r + 1 if r >= position else r, c)] = val
        self._data = new_data
        self._row_count += 1

    def insert_column(self, position: int) -> None:
        if position < 0 or position > self._col_count:
            return
        new_data = {}
        for (r, c), val in self._data.items():
            new_data[(r, c + 1 if c >= position else c)] = val
        self._data = new_data
        self._col_count += 1

    def remove_row(self, position: int) -> None:
        if position < 0 or position >= self._row_count:
            return
        new_data = {}
        for (r, c), val in self._data.items():
            if r == position:
                continue
            new_data[(r - 1 if r > position else r, c)] = val
        self._data = new_data
        self._row_count -= 1

    def remove_column(self, position: int) -> None:
        if position < 0 or position >= self._col_count:
            return
        new_data = {}
        for (r, c), val in self._data.items():
            if c == position:
                continue
            new_data[(r, c - 1 if c > position else c)] = val
        self._data = new_data
        self._col_count -= 1

    # ------------------------------------------------------------------
    # 属性
    # ------------------------------------------------------------------

    @property
    def row_total(self) -> int:
        return self._row_count

    @property
    def col_total(self) -> int:
        return self._col_count

    @property
    def file_path(self) -> str | None:
        return self._file_path

    @file_path.setter
    def file_path(self, path: str | None) -> None:
        self._file_path = path

    @property
    def file_format(self) -> str:
        return self._file_format

    @file_format.setter
    def file_format(self, fmt: str) -> None:
        self._file_format = fmt

    # ------------------------------------------------------------------
    # 快照（撤销用）
    # ------------------------------------------------------------------

    def snapshot(self) -> dict:
        """返回数据快照（浅拷贝 dict，可恢复）。"""
        return self._data.copy()

    def restore_snapshot(self, snapshot: dict) -> None:
        """用快照恢复数据。"""
        self._data = snapshot

    # ------------------------------------------------------------------
    # 工具
    # ------------------------------------------------------------------

    @staticmethod
    def col_letter(n: int) -> str:
        """0→'A', 25→'Z', 26→'AA', 701→'ZZ'。"""
        result = ''
        n += 1
        while n > 0:
            n -= 1
            result = chr(ord('A') + n % 26) + result
            n //= 26
        return result
