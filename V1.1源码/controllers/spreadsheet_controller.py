"""表格编辑控制器 — 剪切/复制/粘贴/删除/行列操作/平移/撤销。"""
from PyQt6.QtWidgets import QApplication, QMessageBox
from PyQt6.QtCore import Qt, QItemSelectionModel
from models.spreadsheet_model import SpreadsheetModel
from views.spreadsheet_grid import SpreadsheetGrid


class SpreadsheetController:
    """处理所有编辑操作，包括快照式撤销。

    V1.1 多 sheet：撤销栈按模型分栈（_undo_stacks），
    切换 sheet 后各表撤销历史互不干扰。
    """

    MAX_UNDO = 100  # 最大撤销步数

    def __init__(self, model: SpreadsheetModel, grid: SpreadsheetGrid):
        self._model = model
        self._grid = grid
        self._undo_stacks: dict[int, list[dict]] = {}
        # 连接 delegate 的编辑开始信号来记录撤销
        grid.itemDelegate().edit_started.connect(self._record_undo)

    # ------------------------------------------------------------------
    # 模型切换（多 sheet）
    # ------------------------------------------------------------------

    def set_model(self, model: SpreadsheetModel) -> None:
        """切换到另一个 sheet 的模型（撤销栈按模型独立保留）。"""
        self._model = model

    @property
    def model(self) -> SpreadsheetModel:
        return self._model

    # ------------------------------------------------------------------
    # 撤销（快照机制）
    # ------------------------------------------------------------------

    def _undo_stack(self) -> list[dict]:
        """当前模型对应的撤销栈（自动创建）。"""
        key = id(self._model)
        stack = self._undo_stacks.get(key)
        if stack is None:
            stack = []
            self._undo_stacks[key] = stack
        return stack

    def _record_undo(self, row: int, col: int, old_value: str) -> None:
        """编辑开始时记录当前数据快照。"""
        self._push_snapshot()

    def _push_snapshot(self) -> None:
        """保存当前数据快照到当前模型的撤销栈。"""
        stack = self._undo_stack()
        stack.append(self._model.snapshot())
        if len(stack) > self.MAX_UNDO:
            stack.pop(0)

    def undo(self) -> None:
        """撤销上次操作（快照恢复）。"""
        stack = self._undo_stack()
        if not stack:
            return
        snapshot = stack.pop()
        self._model.restore_snapshot(snapshot)

    # ------------------------------------------------------------------
    # 剪贴板操作
    # ------------------------------------------------------------------

    def cut(self) -> None:
        """剪切：复制选中区域并清空。"""
        self.copy()
        self.delete_selection()

    def copy(self) -> None:
        """复制选中区域为制表符分隔文本。"""
        rng = self._grid.get_selection_range()
        if not rng:
            return
        min_r, min_c, max_r, max_c = rng
        lines = []
        for r in range(min_r, max_r + 1):
            row_data = [self._model.value(r, c) for c in range(min_c, max_c + 1)]
            lines.append('\t'.join(row_data))
        QApplication.clipboard().setText('\n'.join(lines))

    def paste(self) -> None:
        """粘贴剪贴板内容，自动检测 Tab 或逗号分隔。"""
        text = QApplication.clipboard().text()
        if not text:
            return
        # 统一换行符，去末尾空行
        text = text.replace('\r\n', '\n').replace('\r', '\n')
        lines = text.split('\n')
        while lines and lines[-1].strip() == '':
            lines.pop()
        if not lines:
            return

        delimiter = self._detect_delimiter(lines)
        data = [line.split(delimiter) for line in lines]

        current = self._grid.currentIndex()
        start_r = current.row() if current.isValid() else 0
        start_c = current.column() if current.isValid() else 0

        self._push_snapshot()
        for r_offset, row_data in enumerate(data):
            for c_offset, val in enumerate(row_data):
                self._model.set_value(start_r + r_offset, start_c + c_offset, val)

    @staticmethod
    def _detect_delimiter(lines: list[str]) -> str:
        """检测分隔符：Tab 优先，逗号次之，否则默认 Tab。"""
        sample = lines[:min(10, len(lines))]
        tab_count = sum(line.count('\t') for line in sample)
        comma_count = sum(line.count(',') for line in sample)
        if tab_count > 0 and tab_count >= comma_count:
            return '\t'
        elif comma_count > 0:
            return ','
        return '\t'

    def delete_selection(self) -> None:
        """删除选中区域内容。"""
        indexes = self._grid.selectionModel().selectedIndexes()
        if not indexes:
            return
        self._push_snapshot()
        for idx in indexes:
            self._model.setData(idx, '', Qt.ItemDataRole.EditRole)

    # ------------------------------------------------------------------
    # 方向键平移选中格子
    # ------------------------------------------------------------------

    def move_selection(self, dr: int, dc: int) -> bool:
        """将选中区域整体平移 (dr, dc)。碰到边界返回 False。"""
        rng = self._grid.get_selection_range()
        if not rng:
            return False
        min_r, min_c, max_r, max_c = rng

        # 边界检查
        if dr < 0 and min_r + dr < 0:
            return False
        if dr > 0 and max_r + dr >= self._model.row_total:
            return False
        if dc < 0 and min_c + dc < 0:
            return False
        if dc > 0 and max_c + dc >= self._model.col_total:
            return False

        self._push_snapshot()

        # 读取选中区域所有非空值
        cells: dict[tuple[int, int], str] = {}
        for r in range(min_r, max_r + 1):
            for c in range(min_c, max_c + 1):
                val = self._model.value(r, c)
                if val:
                    cells[(r, c)] = val

        # 清空原位
        for (r, c) in cells:
            self._model.set_value(r, c, '')

        # 写入新位置
        for (r, c), val in cells.items():
            self._model.set_value(r + dr, c + dc, val)

        # 更新选区到新位置
        new_min_r = min_r + dr
        new_min_c = min_c + dc
        new_max_r = max_r + dr
        new_max_c = max_c + dc
        self._set_selection_range(new_min_r, new_min_c, new_max_r, new_max_c)

        return True

    def _set_selection_range(self, min_r: int, min_c: int,
                              max_r: int, max_c: int) -> None:
        """设置表格的选中区域。逐格 select，不依赖 QItemSelection 构造器。"""
        sel = self._grid.selectionModel()
        sel.clear()
        for r in range(min_r, max_r + 1):
            for c in range(min_c, max_c + 1):
                sel.select(self._model.index(r, c),
                           QItemSelectionModel.SelectionFlag.Select)

    # ------------------------------------------------------------------
    # 行列操作
    # ------------------------------------------------------------------

    def insert_row(self, position: int = -1) -> None:
        """在指定位置插入一行。position=-1 时使用当前选中行。"""
        if position == -1:
            idx = self._grid.currentIndex()
            position = idx.row() if idx.isValid() else self._model.row_total
        self._push_snapshot()
        self._model.insert_row(position)

    def insert_column(self, position: int = -1) -> None:
        if position == -1:
            idx = self._grid.currentIndex()
            position = idx.column() if idx.isValid() else self._model.col_total
        self._push_snapshot()
        self._model.insert_column(position)

    def remove_row(self, position: int = -1) -> None:
        if position == -1:
            idx = self._grid.currentIndex()
            if not idx.isValid():
                return
            position = idx.row()
        if position < 0 or position >= self._model.row_total:
            return
        self._push_snapshot()
        self._model.remove_row(position)

    def remove_column(self, position: int = -1) -> None:
        if position == -1:
            idx = self._grid.currentIndex()
            if not idx.isValid():
                return
            position = idx.column()
        if position < 0 or position >= self._model.col_total:
            return
        self._push_snapshot()
        self._model.remove_column(position)
