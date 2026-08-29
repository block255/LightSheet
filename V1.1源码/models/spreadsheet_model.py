"""核心表格数据模型 — QAbstractTableModel 子类（Qt 薄适配器）。

数据实际存储在纯 Python 的 TableData（models/table_data.py）中，
本类只负责：
  1. 实现 QAbstractTableModel 接口（data/setData/rowCount/...）
  2. 在数据变化时发出 Qt 信号（dataChanged / begin-* / end-*）
  3. 维护 UI 级 dirty 状态

共享层（TableData）可被本地 Web 版直接复用，改一处两端生效。
"""
from PyQt6.QtCore import QAbstractTableModel, Qt, QModelIndex, pyqtSignal

from models.table_data import TableData


class SpreadsheetModel(QAbstractTableModel):
    """以稀疏 dict 存储单元格数据。行列默认 100×26。"""

    dirty_changed = pyqtSignal(bool)

    DEFAULT_ROWS = TableData.DEFAULT_ROWS
    DEFAULT_COLS = TableData.DEFAULT_COLS

    def __init__(self, parent=None):
        super().__init__(parent)
        self._table = TableData()
        self._is_dirty = False

    # ------------------------------------------------------------------
    # QAbstractTableModel 必须实现的方法
    # ------------------------------------------------------------------

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else self._table.row_total

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else self._table.col_total

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            return self._table.value(index.row(), index.column())
        return None

    def setData(self, index: QModelIndex, value: str, role: int = Qt.ItemDataRole.EditRole) -> bool:
        if not index.isValid() or role != Qt.ItemDataRole.EditRole:
            return False
        self._table.set_value(index.row(), index.column(), value)
        self.dataChanged.emit(index, index, [role])
        self._mark_dirty()
        return True

    def headerData(self, section: int, orientation: Qt.Orientation,
                   role: int = Qt.ItemDataRole.DisplayRole):
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            return TableData.col_letter(section)
        else:
            return str(section + 1)

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        default = super().flags(index)
        if index.isValid():
            return default | Qt.ItemFlag.ItemIsEditable
        return default

    # ------------------------------------------------------------------
    # 公开 API（转发到 TableData，保持原签名）
    # ------------------------------------------------------------------

    def value(self, row: int, col: int) -> str:
        return self._table.value(row, col)

    def set_value(self, row: int, col: int, value: str) -> None:
        """以编程方式设值（不通过 model index），触发 dataChanged。"""
        index = self.index(row, col)
        self.setData(index, value)

    def clear(self) -> None:
        """清空所有数据，重置到默认尺寸。"""
        self.beginResetModel()
        self._table.clear()
        self._is_dirty = False
        self.endResetModel()
        self.dirty_changed.emit(False)

    def load_2d(self, matrix: list[list[str]]) -> None:
        """从二维列表加载数据，替换当前内容。"""
        self.beginResetModel()
        self._table.load_2d(matrix)
        self._is_dirty = False
        self.endResetModel()
        self.dirty_changed.emit(False)

    def data_bounds(self) -> tuple[int, int, int, int] | None:
        return self._table.data_bounds()

    def to_2d(self) -> list[list[str]]:
        return self._table.to_2d()

    def insert_row(self, position: int) -> None:
        if position < 0 or position > self._table.row_total:
            return
        self.beginInsertRows(QModelIndex(), position, position)
        self._table.insert_row(position)
        self.endInsertRows()
        self._mark_dirty()

    def insert_column(self, position: int) -> None:
        if position < 0 or position > self._table.col_total:
            return
        self.beginInsertColumns(QModelIndex(), position, position)
        self._table.insert_column(position)
        self.endInsertColumns()
        self._mark_dirty()

    def remove_row(self, position: int) -> None:
        if position < 0 or position >= self._table.row_total:
            return
        self.beginRemoveRows(QModelIndex(), position, position)
        self._table.remove_row(position)
        self.endRemoveRows()
        self._mark_dirty()

    def remove_column(self, position: int) -> None:
        if position < 0 or position >= self._table.col_total:
            return
        self.beginRemoveColumns(QModelIndex(), position, position)
        self._table.remove_column(position)
        self.endRemoveColumns()
        self._mark_dirty()

    # ------------------------------------------------------------------
    # 属性
    # ------------------------------------------------------------------

    @staticmethod
    def col_letter(n: int) -> str:
        """0→'A', 25→'Z', 26→'AA', 701→'ZZ'（委托 TableData，保持原 API）。"""
        return TableData.col_letter(n)

    @property
    def is_dirty(self) -> bool:
        return self._is_dirty

    @property
    def file_path(self) -> str | None:
        return self._table.file_path

    @file_path.setter
    def file_path(self, path: str | None) -> None:
        self._table.file_path = path

    @property
    def file_format(self) -> str:
        return self._table.file_format

    @file_format.setter
    def file_format(self, fmt: str) -> None:
        self._table.file_format = fmt

    @property
    def row_total(self) -> int:
        return self._table.row_total

    @property
    def col_total(self) -> int:
        return self._table.col_total

    # ------------------------------------------------------------------
    # 快照（撤销用，公共 API）
    # ------------------------------------------------------------------

    def snapshot(self) -> dict:
        """返回数据快照（供撤销栈使用）。"""
        return self._table.snapshot()

    def restore_snapshot(self, snapshot: dict) -> None:
        """用快照恢复数据（供撤销使用）。"""
        self._table.restore_snapshot(snapshot)
        self._mark_dirty()
        # 通知视图刷新全部可见单元格
        self.dataChanged.emit(
            self.index(0, 0),
            self.index(self._table.row_total - 1, self._table.col_total - 1),
            [Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole]
        )

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _mark_dirty(self) -> None:
        if not self._is_dirty:
            self._is_dirty = True
            self.dirty_changed.emit(True)

    def mark_dirty(self) -> None:
        """公开标记为已修改（程序性改内容后调用，如单表导入）。"""
        self._mark_dirty()

    def mark_clean(self) -> None:
        if self._is_dirty:
            self._is_dirty = False
            self.dirty_changed.emit(False)
