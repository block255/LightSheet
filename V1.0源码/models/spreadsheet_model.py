"""核心表格数据模型 — QAbstractTableModel 子类，稀疏存储。"""
from PyQt6.QtCore import QAbstractTableModel, Qt, QModelIndex, pyqtSignal


class SpreadsheetModel(QAbstractTableModel):
    """以稀疏 dict 存储单元格数据。行列默认 100×26。"""

    dirty_changed = pyqtSignal(bool)

    DEFAULT_ROWS = 100
    DEFAULT_COLS = 26

    def __init__(self, parent=None):
        super().__init__(parent)
        self._data: dict[tuple[int, int], str] = {}
        self._row_count = self.DEFAULT_ROWS
        self._col_count = self.DEFAULT_COLS
        self._is_dirty = False
        self._file_path: str | None = None
        self._file_format: str = ''

    # ------------------------------------------------------------------
    # QAbstractTableModel 必须实现的方法
    # ------------------------------------------------------------------

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else self._row_count

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else self._col_count

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            return self._data.get((index.row(), index.column()), '')
        return None

    def setData(self, index: QModelIndex, value: str, role: int = Qt.ItemDataRole.EditRole) -> bool:
        if not index.isValid() or role != Qt.ItemDataRole.EditRole:
            return False
        key = (index.row(), index.column())
        value = str(value)
        if value == '':
            if key in self._data:
                del self._data[key]
        else:
            self._data[key] = value
        self.dataChanged.emit(index, index, [role])
        self._mark_dirty()
        return True

    def headerData(self, section: int, orientation: Qt.Orientation,
                   role: int = Qt.ItemDataRole.DisplayRole):
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            return self.col_letter(section)
        else:
            return str(section + 1)

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        default = super().flags(index)
        if index.isValid():
            return default | Qt.ItemFlag.ItemIsEditable
        return default

    # ------------------------------------------------------------------
    # 公开 API
    # ------------------------------------------------------------------

    def value(self, row: int, col: int) -> str:
        return self._data.get((row, col), '')

    def set_value(self, row: int, col: int, value: str) -> None:
        """以编程方式设值（不通过 model index），触发 dataChanged。"""
        index = self.index(row, col)
        self.setData(index, value)

    def clear(self) -> None:
        """清空所有数据，重置到默认尺寸。"""
        self.beginResetModel()
        self._data.clear()
        self._row_count = self.DEFAULT_ROWS
        self._col_count = self.DEFAULT_COLS
        self._is_dirty = False
        self._file_path = None
        self._file_format = ''
        self.endResetModel()
        self.dirty_changed.emit(False)

    def load_2d(self, matrix: list[list[str]]) -> None:
        """从二维列表加载数据，替换当前内容。"""
        rows = len(matrix)
        cols = max((len(r) for r in matrix), default=0)
        self.beginResetModel()
        self._data.clear()
        for r, row_data in enumerate(matrix):
            for c, val in enumerate(row_data):
                if val:
                    self._data[(r, c)] = str(val)
        self._row_count = max(rows, self.DEFAULT_ROWS)
        self._col_count = max(cols, self.DEFAULT_COLS)
        self._is_dirty = False
        self.endResetModel()
        self.dirty_changed.emit(False)

    def data_bounds(self) -> tuple[int, int, int, int] | None:
        """返回有数据区域的外接矩形 (r1, c1, r2, c2)。无数据返回 None。"""
        if not self._data:
            return None
        min_r = min(r for r, _ in self._data)
        max_r = max(r for r, _ in self._data)
        min_c = min(c for _, c in self._data)
        max_c = max(c for _, c in self._data)
        return min_r, min_c, max_r, max_c

    def to_2d(self) -> list[list[str]]:
        """导出为二维列表。只导出有数据的区域。"""
        if not self._data:
            return []
        max_r = max(r for r, _ in self._data) + 1
        max_c = max(c for _, c in self._data) + 1
        matrix = [[''] * max_c for _ in range(max_r)]
        for (r, c), val in self._data.items():
            matrix[r][c] = val
        return matrix

    def insert_row(self, position: int) -> None:
        if position < 0 or position > self._row_count:
            return
        self.beginInsertRows(QModelIndex(), position, position)
        new_data = {}
        for (r, c), val in self._data.items():
            new_data[(r + 1 if r >= position else r, c)] = val
        self._data = new_data
        self._row_count += 1
        self.endInsertRows()
        self._mark_dirty()

    def insert_column(self, position: int) -> None:
        if position < 0 or position > self._col_count:
            return
        self.beginInsertColumns(QModelIndex(), position, position)
        new_data = {}
        for (r, c), val in self._data.items():
            new_data[(r, c + 1 if c >= position else c)] = val
        self._data = new_data
        self._col_count += 1
        self.endInsertColumns()
        self._mark_dirty()

    def remove_row(self, position: int) -> None:
        if position < 0 or position >= self._row_count:
            return
        self.beginRemoveRows(QModelIndex(), position, position)
        new_data = {}
        for (r, c), val in self._data.items():
            if r == position:
                continue
            new_data[(r - 1 if r > position else r, c)] = val
        self._data = new_data
        self._row_count -= 1
        self.endRemoveRows()
        self._mark_dirty()

    def remove_column(self, position: int) -> None:
        if position < 0 or position >= self._col_count:
            return
        self.beginRemoveColumns(QModelIndex(), position, position)
        new_data = {}
        for (r, c), val in self._data.items():
            if c == position:
                continue
            new_data[(r, c - 1 if c > position else c)] = val
        self._data = new_data
        self._col_count -= 1
        self.endRemoveColumns()
        self._mark_dirty()

    # ------------------------------------------------------------------
    # 属性
    # ------------------------------------------------------------------

    @property
    def is_dirty(self) -> bool:
        return self._is_dirty

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

    @property
    def row_total(self) -> int:
        return self._row_count

    @property
    def col_total(self) -> int:
        return self._col_count

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

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _mark_dirty(self) -> None:
        if not self._is_dirty:
            self._is_dirty = True
            self.dirty_changed.emit(True)

    def restore_snapshot(self, snapshot: dict) -> None:
        """用快照恢复数据（供撤销使用）。"""
        self._data = snapshot
        self._mark_dirty()
        # 通知视图刷新全部可见单元格
        self.dataChanged.emit(
            self.index(0, 0),
            self.index(self._row_count - 1, self._col_count - 1),
            [Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole]
        )

    def mark_clean(self) -> None:
        if self._is_dirty:
            self._is_dirty = False
            self.dirty_changed.emit(False)
