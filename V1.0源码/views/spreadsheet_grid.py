"""表格网格视图 — QTableView 子类。"""
from PyQt6.QtWidgets import (
    QTableView, QHeaderView, QMenu, QStyledItemDelegate, QLineEdit,
    QDialog, QVBoxLayout, QPlainTextEdit, QDialogButtonBox, QApplication
)
from PyQt6.QtCore import Qt, pyqtSignal, QModelIndex, QTimer, QEvent, QItemSelection, QItemSelectionModel
from PyQt6.QtGui import QAction, QMouseEvent, QKeyEvent, QKeySequence


class ChineseLineEdit(QLineEdit):
    """右键菜单中文化的输入框。
    Ctrl 组合键（Ctrl+Z/V/C/S…）全部转发给表格，编辑器不拦截。
    输入内容不需要 Ctrl 键，所以不会影响正常打字。"""

    def keyPressEvent(self, event: QKeyEvent):
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            # 所有 Ctrl 组合键 → 关闭编辑器，转发给表格处理
            grid = _find_ancestor_grid(self)
            if grid:
                self.clearFocus()
                ev = QKeyEvent(event.type(), event.key(), event.modifiers(),
                               event.text(), event.isAutoRepeat(), event.count())
                QTimer.singleShot(0, lambda: QApplication.postEvent(grid, ev))
            return
        super().keyPressEvent(event)

    def contextMenuEvent(self, event):
        menu = self.createStandardContextMenu()
        translations = {
            '&Undo':        '撤销(&U)',
            '&Redo':        '重做(&R)',
            'Cu&t':         '剪切(&T)',
            '&Copy':        '复制(&C)',
            '&Paste':       '粘贴(&P)',
            'Delete':       '删除',
            'Select All':   '全选(&A)',
            'Undo':         '撤销',
            'Redo':         '重做',
            'Cut':          '剪切',
            'Copy':         '复制',
            'Paste':        '粘贴',
        }
        for action in menu.actions():
            text = action.text()
            if text in translations:
                action.setText(translations[text])
        menu.exec(event.globalPos())


def _find_ancestor_grid(widget):
    """向上查找 SpreadsheetGrid（不依赖类名，用 move_requested 特征识别）。"""
    w = widget.parent()
    while w:
        if hasattr(w, 'move_requested'):
            return w
        w = w.parent()
    return None


class CellEditDelegate(QStyledItemDelegate):
    """自定义单元格编辑器。
    通过事件过滤器在用户真正敲下第一个内容键时才记录撤销快照，
    避免"点格子不进编辑"或"切换选区"也产生空快照。"""

    edit_started = pyqtSignal(int, int, str)  # row, col, old_value

    # 纯导航键 —— 不会改变单元格内容，不该触发快照
    _NAV_KEYS = {
        Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Up, Qt.Key.Key_Down,
        Qt.Key.Key_Home, Qt.Key.Key_End, Qt.Key.Key_PageUp, Qt.Key.Key_PageDown,
        Qt.Key.Key_Tab, Qt.Key.Key_Backtab,
        Qt.Key.Key_Control, Qt.Key.Key_Shift, Qt.Key.Key_Alt, Qt.Key.Key_Meta,
        Qt.Key.Key_CapsLock, Qt.Key.Key_NumLock, Qt.Key.Key_ScrollLock,
        Qt.Key.Key_Escape, Qt.Key.Key_F1, Qt.Key.Key_F2, Qt.Key.Key_F3,
        Qt.Key.Key_F4, Qt.Key.Key_F5, Qt.Key.Key_F6, Qt.Key.Key_F7,
        Qt.Key.Key_F8, Qt.Key.Key_F9, Qt.Key.Key_F10, Qt.Key.Key_F11,
        Qt.Key.Key_F12,
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self._editing_index = QModelIndex()  # 当前正在编辑的格子，无效表示无

    def paint(self, painter, option, index: QModelIndex):
        """绘制单元格。如果当前格子正在被编辑，只画背景不画文字，
        避免底层文字与编辑器文字重叠产生"残影"。"""
        if index == self._editing_index and self._editing_index.isValid():
            # 只绘制背景，跳过文字
            style = option.widget.style() if option.widget else None
            if style:
                style.drawControl(
                    style.ControlElement.CE_ItemViewItem, option, painter, option.widget)
            return
        super().paint(painter, option, index)

    def createEditor(self, parent, option, index: QModelIndex):
        """使用中文化右键菜单的输入框。"""
        editor = ChineseLineEdit(parent)
        # 记录正在编辑的格子，paint() 会据此跳过文字绘制
        self._editing_index = QModelIndex(index)
        # 确保编辑器背景不透明，完全覆盖底层 cell
        editor.setAutoFillBackground(True)
        old_value = index.data(Qt.ItemDataRole.DisplayRole) or ''
        row, col = index.row(), index.column()

        # 保存编辑信息，供 eventFilter 在第一次真实按键时记录快照
        editor._edit_info = (row, col, old_value)
        editor.installEventFilter(self)

        return editor

    def destroyEditor(self, editor, index: QModelIndex):
        """编辑器关闭时清除编辑标记，恢复正常绘制。"""
        self._editing_index = QModelIndex()
        super().destroyEditor(editor, index)

    def eventFilter(self, obj, event):
        """拦截编辑器按键：
        - Ctrl+V 多格 → 已由 ChineseLineEdit.keyPressEvent 处理
        - 首个内容键 → 记录撤销快照，移除过滤器
        - 导航/功能键 → 忽略，不记录快照
        """
        if event.type() == QEvent.Type.KeyPress:
            key = event.key()
            # 跳过修饰键、导航键、功能键
            if key not in self._NAV_KEYS:
                info = getattr(obj, '_edit_info', None)
                if info is not None:
                    del obj._edit_info
                    obj.removeEventFilter(self)
                    self.edit_started.emit(*info)
        return super().eventFilter(obj, event)

    def setEditorData(self, editor, index: QModelIndex):
        super().setEditorData(editor, index)

        if not isinstance(editor, QLineEdit):
            return

        # 检查是否有双击点击位置
        grid = self.parent()
        double_x = grid.consume_double_click() if isinstance(grid, SpreadsheetGrid) else -1

        if double_x >= 0:
            # 双击：光标定位到鼠标所指字符位置
            QTimer.singleShot(0, lambda: _cursor_at_click(editor, double_x))
        else:
            # 单击：光标移到末尾
            text_len = len(editor.text())
            QTimer.singleShot(0, lambda: _cursor_to_end(editor, text_len))


def _cursor_to_end(editor: QLineEdit, length: int) -> None:
    """光标移到末尾并取消选中。"""
    try:
        editor.deselect()
        editor.setCursorPosition(length)
    except RuntimeError:
        pass


def _cursor_at_click(editor: QLineEdit, x_offset: int) -> None:
    """根据鼠标 x 偏移量，将光标定位到对应字符位置。"""
    try:
        editor.deselect()
        fm = editor.fontMetrics()
        text = editor.text()
        if not text:
            return
        x = max(0, x_offset - 4)
        accumulated = 0
        for i, ch in enumerate(text):
            cw = fm.horizontalAdvance(ch)
            if accumulated + cw // 2 >= x:
                editor.setCursorPosition(i)
                return
            accumulated += cw
        editor.setCursorPosition(len(text))
    except RuntimeError:
        pass


class SpreadsheetGrid(QTableView):
    """Excel 风格的表格网格。支持编辑/浏览双模式和双击精确定位。"""

    row_inserted = pyqtSignal(int)
    col_inserted = pyqtSignal(int)
    row_removed = pyqtSignal(int)
    col_removed = pyqtSignal(int)
    edit_mode_changed = pyqtSignal(bool)
    move_requested = pyqtSignal(int, int)  # dr, dc — 方向键平移选区

    CLICK_THRESHOLD = 5  # 像素，按压/释放距离小于此视为"点击"

    def __init__(self, parent=None):
        super().__init__(parent)
        self._delegate = CellEditDelegate(self)
        self.setItemDelegate(self._delegate)
        self._edit_mode = True
        self._double_click_x: int = -1
        self._press_pos = None  # QPoint，记录按下位置
        self._setup_appearance()
        self._setup_header()
        self._apply_edit_mode()

    # ------------------------------------------------------------------
    # 键盘事件：多格选中时方向键平移选区
    # ------------------------------------------------------------------

    # 方向键 → (dr, dc)
    _ARROW_DR_DC = {
        Qt.Key.Key_Up:    (-1, 0),
        Qt.Key.Key_Down:  (1, 0),
        Qt.Key.Key_Left:  (0, -1),
        Qt.Key.Key_Right: (0, 1),
    }

    def event(self, e: QEvent) -> bool:
        """在 event() 层拦截方向键——比 keyPressEvent 更早，
        返回 True 彻底阻止 QTableView 默认导航把多格选区收缩成单格。"""
        if e.type() == QEvent.Type.KeyPress:
            ke = e  # QKeyEvent
            if ke.modifiers() == Qt.KeyboardModifier.NoModifier:
                dr, dc = self._ARROW_DR_DC.get(ke.key(), (0, 0))
                if dr != 0 or dc != 0:
                    if not self._is_single_cell_selected():
                        if self.selectionModel().hasSelection():
                            self.move_requested.emit(dr, dc)
                            return True  # 已消费，阻止默认导航
        return super().event(e)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """多格选中时沉默可打印字符，防止触发编辑。
        方向键平移已在 event() 中处理。"""
        if event.modifiers() == Qt.KeyboardModifier.NoModifier:
            if not self._is_single_cell_selected():
                if event.text() and event.text().isprintable():
                    return
        super().keyPressEvent(event)

    # ------------------------------------------------------------------
    # 鼠标事件：区分"点击"与"拖拽框选"
    # ------------------------------------------------------------------

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_pos = event.pos()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if (self._edit_mode and
                event.button() == Qt.MouseButton.LeftButton and
                self._press_pos is not None and
                event.modifiers() == Qt.KeyboardModifier.NoModifier):
            delta = event.pos() - self._press_pos
            if delta.manhattanLength() < self.CLICK_THRESHOLD:
                # 静止点击：进入编辑
                idx = self.indexAt(event.pos())
                if idx.isValid() and idx == self.currentIndex():
                    self.edit(idx)
        self._press_pos = None
        super().mouseReleaseEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        # 一旦开始拖拽，清除点击标记（防止触发编辑）
        if (self._press_pos is not None and
                (event.pos() - self._press_pos).manhattanLength() >= self.CLICK_THRESHOLD):
            self._press_pos = None
        super().mouseMoveEvent(event)

    # ------------------------------------------------------------------
    # 双击定位
    # ------------------------------------------------------------------

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        self._press_pos = None  # 双击不需要单击编辑
        index = self.indexAt(event.pos())
        if index.isValid():
            rect = self.visualRect(index)
            self._double_click_x = event.pos().x() - rect.x()
        super().mouseDoubleClickEvent(event)

    def consume_double_click(self) -> int:
        val = self._double_click_x
        self._double_click_x = -1
        return val

    # ------------------------------------------------------------------
    # 模式切换
    # ------------------------------------------------------------------

    @property
    def is_edit_mode(self) -> bool:
        return self._edit_mode

    def set_edit_mode(self, enabled: bool) -> None:
        if self._edit_mode == enabled:
            return
        self._edit_mode = enabled
        self._apply_edit_mode()
        self.edit_mode_changed.emit(enabled)

    def toggle_edit_mode(self) -> None:
        self.set_edit_mode(not self._edit_mode)

    def _apply_edit_mode(self) -> None:
        if self._edit_mode:
            # 编辑模式：单击 = 手动触发 edit()（见 mouseReleaseEvent）
            self.setEditTriggers(
                self.EditTrigger.SelectedClicked |
                self.EditTrigger.EditKeyPressed |
                self.EditTrigger.AnyKeyPressed
            )
        else:
            # 浏览模式：双击才编辑
            self.setEditTriggers(
                self.EditTrigger.DoubleClicked |
                self.EditTrigger.EditKeyPressed |
                self.EditTrigger.AnyKeyPressed
            )

    # ------------------------------------------------------------------
    # 公开方法
    # ------------------------------------------------------------------

    def get_selection_range(self) -> tuple[int, int, int, int] | None:
        indexes = self.selectionModel().selectedIndexes()
        if not indexes:
            return None
        rows = [idx.row() for idx in indexes]
        cols = [idx.column() for idx in indexes]
        return min(rows), min(cols), max(rows), max(cols)

    def set_selection_range(self, r1: int, c1: int, r2: int, c2: int) -> None:
        """选中 (r1,c1) 到 (r2,c2) 的矩形区域（单次原子 select）。"""
        model = self.model()
        sel = self.selectionModel()
        top_left = model.index(r1, c1)
        bottom_right = model.index(r2, c2)
        sel.select(
            QItemSelection(top_left, bottom_right),
            QItemSelectionModel.SelectionFlag.ClearAndSelect,
        )
        sel.setCurrentIndex(top_left, QItemSelectionModel.SelectionFlag.NoUpdate)

    def _is_single_cell_selected(self) -> bool:
        """判断是否只选中了单一格子。"""
        indexes = self.selectionModel().selectedIndexes()
        if not indexes:
            return False
        rows = set(idx.row() for idx in indexes)
        cols = set(idx.column() for idx in indexes)
        return len(rows) == 1 and len(cols) == 1

    def select_all_cell_text(self) -> None:
        """单格：进入编辑并全选；多格：弹出对话框全选所有格子文字。"""
        if self._is_single_cell_selected():
            # 单格：直接进入编辑全选
            idx = self.currentIndex()
            if not idx.isValid():
                return
            self.edit(idx)
            editor = self.findChild(QLineEdit)
            if editor:
                QTimer.singleShot(0, editor.selectAll)
        else:
            # 多格：弹出对话框，展示所有文字并全选
            rng = self.get_selection_range()
            if not rng:
                return
            min_r, min_c, max_r, max_c = rng
            model = self.model()
            lines = []
            for r in range(min_r, max_r + 1):
                row_data = []
                for c in range(min_c, max_c + 1):
                    idx = model.index(r, c)
                    val = idx.data(Qt.ItemDataRole.DisplayRole) or ''
                    row_data.append(val)
                lines.append('\t'.join(row_data))

            dlg = QDialog(self)
            dlg.setWindowTitle(f'选中内容  ({max_r - min_r + 1}行 × {max_c - min_c + 1}列)')
            dlg.resize(500, 350)
            layout = QVBoxLayout(dlg)
            editor = QPlainTextEdit(dlg)
            editor.setPlainText('\n'.join(lines))
            editor.selectAll()
            layout.addWidget(editor)
            btn_box = QDialogButtonBox(
                QDialogButtonBox.StandardButton.Ok, dlg
            )
            btn_box.accepted.connect(dlg.accept)
            # 中文化按钮
            ok_btn = btn_box.button(QDialogButtonBox.StandardButton.Ok)
            if ok_btn:
                ok_btn.setText('关闭')
            layout.addWidget(btn_box)
            dlg.exec()

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        idx = self.indexAt(event.pos())

        # 全选内容 — 单格/多格自适应
        select_action = QAction('全选内容', self)
        select_action.triggered.connect(self.select_all_cell_text)
        menu.addAction(select_action)
        menu.addSeparator()

        # 插入行/列：使用当前选中格坐标（而非右键点击位置）
        cur = self.currentIndex()
        insert_row = cur.row() if cur.isValid() else (idx.row() if idx.isValid() else 0)
        insert_col = cur.column() if cur.isValid() else (idx.column() if idx.isValid() else 0)

        insert_row_action = QAction('插入行', self)
        insert_row_action.triggered.connect(lambda: self.row_inserted.emit(insert_row))
        insert_col_action = QAction('插入列', self)
        insert_col_action.triggered.connect(lambda: self.col_inserted.emit(insert_col))
        remove_row_action = QAction('删除行', self)
        remove_row_action.triggered.connect(lambda: self.row_removed.emit(insert_row))
        remove_col_action = QAction('删除列', self)
        remove_col_action.triggered.connect(lambda: self.col_removed.emit(insert_col))

        menu.addAction(insert_row_action)
        menu.addAction(insert_col_action)
        menu.addSeparator()
        menu.addAction(remove_row_action)
        menu.addAction(remove_col_action)
        menu.exec(event.globalPos())

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _setup_appearance(self) -> None:
        self.setAlternatingRowColors(False)
        self.setShowGrid(True)
        self.setGridStyle(Qt.PenStyle.SolidLine)
        self.setSelectionMode(self.SelectionMode.ContiguousSelection)
        self.setTabKeyNavigation(True)
        self.horizontalScrollMode()
        self.verticalHeader().setDefaultSectionSize(28)

    def _setup_header(self) -> None:
        h_header = self.horizontalHeader()
        h_header.setSectionsClickable(True)
        h_header.setDefaultSectionSize(80)
        h_header.setMinimumSectionSize(40)
        h_header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        h_header.setStretchLastSection(False)

        v_header = self.verticalHeader()
        v_header.setDefaultSectionSize(28)
        v_header.setMinimumSectionSize(20)
        v_header.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        v_header.setSectionsClickable(True)
        self.setSelectionBehavior(self.SelectionBehavior.SelectItems)
