"""左侧面板 — 表格库/脚本库切换、文件夹树子版块。"""
import ctypes
import os

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QTreeView,
    QLabel, QLineEdit, QFileDialog, QHeaderView, QFrame, QMenu, QToolButton,
    QApplication, QComboBox,
)
from PyQt6.QtCore import Qt, pyqtSignal, QDir, QSortFilterProxyModel, QEvent, QTimer
from PyQt6.QtGui import QFileSystemModel, QShortcut, QKeySequence

from config.settings import AppSettings, _app_base_dir


def _lookup_order(order_map: dict, path: str, base: str) -> list | None:
    """查自定义顺序：先按目录绝对路径，再按相对 base 的路径（正斜杠）。

    打包预置的 config 用相对 exe 目录的 key（如 '脚本库/排序脚本'），
    因为最终解压位置未知；运行时目录绝对路径查不到时退回相对 key。
    """
    order = order_map.get(path)
    if order is None and path and base:
        try:
            rel = os.path.relpath(path, base)
        except ValueError:   # 不同盘符无相对路径
            rel = ''
        if rel and rel != '.':
            order = order_map.get(rel.replace('\\', '/'))
    return order

try:
    _SHLWAPI = ctypes.windll.shlwapi
    _SHLWAPI.StrCmpLogicalW.restype = ctypes.c_int
    _SHLWAPI.StrCmpLogicalW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
    _HAS_NATURAL_CMP = True
except Exception:
    _HAS_NATURAL_CMP = False


def _windows_natural_cmp(a: str, b: str) -> int:
    """用 Windows 文件管理器的自然排序比较（StrCmpLogicalW）。"""
    if _HAS_NATURAL_CMP:
        return _SHLWAPI.StrCmpLogicalW(a, b)
    al, bl = a.lower(), b.lower()
    return (al > bl) - (al < bl)


class FileFilterProxy(QSortFilterProxyModel):
    """只显示文件夹 + 指定后缀的文件，并按 Windows 文件管理器顺序排序。

    支持用户自定义顺序（2026-08-22）：某目录配置了顺序列表（dir 路径 ->
    [显示名按序]）时，该目录子项完全按列表排（文件/文件夹可交叉）；否则
    默认（文件夹排前 + Windows 自然排序）。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._extensions: tuple[str, ...] = ()
        self._order_map: dict[str, dict] = {}   # dir 绝对路径 -> {name: index}

    def set_extensions(self, extensions: list[str]) -> None:
        self._extensions = tuple(ext.lstrip('*') for ext in extensions)
        self.invalidateFilter()

    def set_user_order(self, order_map: dict[str, list]) -> None:
        """设置用户自定义顺序（dir 绝对路径 -> [显示名按序]）。"""
        self._order_map = order_map or {}
        self.invalidate()

    def _order_for(self, parent_idx) -> list | None:
        src = self.sourceModel()
        if parent_idx.isValid():
            path = src.filePath(parent_idx)
        else:
            path = ''
        return _lookup_order(self._order_map, path, _app_base_dir())

    def filterAcceptsRow(self, source_row: int, source_parent) -> bool:
        source = self.sourceModel()
        idx = source.index(source_row, 0, source_parent)
        if source.isDir(idx):
            return True
        return source.fileName(idx).endswith(self._extensions)

    def lessThan(self, left, right) -> bool:
        """文件夹排前，其余按 Windows 自然排序；有用户顺序则完全按列表排。"""
        src = self.sourceModel()
        order = self._order_for(left.parent())
        if order:
            lname = src.fileName(left)
            rname = src.fileName(right)
            try:
                li = order.index(lname)
            except ValueError:
                li = -1
            try:
                ri = order.index(rname)
            except ValueError:
                ri = -1
            if li >= 0 and ri >= 0:
                return li < ri
            if li >= 0:
                return True    # 在列表内优先
            if ri >= 0:
                return False
        left_dir = src.isDir(left)
        right_dir = src.isDir(right)
        if left_dir != right_dir:
            return left_dir  # 文件夹排在文件前面
        return _windows_natural_cmp(src.fileName(left), src.fileName(right)) < 0


class _OptionGroup(QWidget):
    """一组互斥按钮。layout_mode: 'h' 横排（默认，均分一行）/ 'v' 竖排（各占一行）。"""

    value_changed = pyqtSignal(str, str)

    def __init__(self, key, options, layout_mode='h', parent=None):
        super().__init__(parent)
        self._key = key
        self._btns = []
        if layout_mode == 'v':
            lo = QVBoxLayout(self)
            lo.setContentsMargins(0, 0, 0, 0)
            lo.setSpacing(4)
        else:
            lo = QHBoxLayout(self)
            lo.setContentsMargins(0, 0, 0, 0)
            lo.setSpacing(4)
        for o in options:
            b = QPushButton(o); b.setCheckable(True)
            b.setStyleSheet(
                'QPushButton:checked { background: #ffffff; color: #000000;'
                ' border: 1px solid #a0a0a0; font-weight: bold; }'
            )
            b.clicked.connect(lambda c, bb=b, oo=o: self._on(bb, oo))
            if layout_mode == 'v':
                lo.addWidget(b)
            else:
                lo.addWidget(b, 1)
            self._btns.append(b)

    def _on(self, btn, value):
        if not btn.isChecked(): btn.setChecked(True)
        for b in self._btns:
            if b is not btn: b.setChecked(False)
        self.value_changed.emit(self._key, value)

    @property
    def current_value(self):
        for b in self._btns:
            if b.isChecked(): return b.text()
        return None


class OperandSlot(QWidget):
    """计算元输入槽位：左箭头（菜单）+ 内容区（文本/输入框）+ 删除按钮。

    箭头固定在左侧，任何状态下点击都能重新选择
    （点选列/行、手动输入常数、从剪贴板接入、清除）；
    内容区在"文本按钮"（显示列名/常数/粘贴列）与"常数输入框"之间切换。
    """

    action_requested = pyqtSignal(int, str)
    constant_submitted = pyqtSignal(int, str)
    constant_cancelled = pyqtSignal(int)
    remove_requested = pyqtSignal(int)

    def __init__(self, index: int, pick_kind: str = 'column',
                 show_delete: bool = True, initial_text: str = '选择计算元',
                 text_mode: bool = False, parent=None):
        super().__init__(parent)
        self._index = index
        self._initial_text = initial_text
        lo = QHBoxLayout(self)
        lo.setContentsMargins(0, 0, 0, 0)
        lo.setSpacing(2)

        # 左箭头：始终显示，点击弹出菜单（Qt 对带菜单按钮自绘箭头，不再额外放文本符号）
        self._menu_btn = QToolButton(self)
        self._menu_btn.setToolTip('重新选择计算元')
        self._menu_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._menu_btn.setAutoRaise(True)
        self._menu_btn.setFixedWidth(22)

        # 菜单项：点选方向按运算方向取其一；文本模式用文本专用菜单项
        pick_item = ('点选行', 'row') if pick_kind == 'row' else ('点选列', 'column')
        if text_mode:
            menu_items = [
                pick_item,
                ('手动输入文本', 'text'),
                ('剪贴板单文本', 'clipboard_single'),
                ('剪贴板多文本', 'clipboard_multi'),
            ]
        else:
            menu_items = [
                pick_item,
                ('手动输入常数', 'constant'),
                ('从剪贴板接入', 'clipboard'),
            ]
        menu = QMenu(self._menu_btn)
        for text, action in menu_items:
            act = menu.addAction(text)
            act.triggered.connect(
                lambda checked=False, a=action: self._emit(a))
        menu.addSeparator()
        clear_act = menu.addAction('清除')
        clear_act.triggered.connect(lambda: self._emit('clear'))
        self._menu_btn.setMenu(menu)
        lo.addWidget(self._menu_btn)

        # 内容区：常态为文本按钮（只读展示），输入常数为输入框
        self._text_btn = QToolButton(self)
        self._text_btn.setText(initial_text)
        self._text_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self._text_btn.setAutoRaise(True)
        self._text_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        lo.addWidget(self._text_btn, 1)

        self._edit = QLineEdit(self)
        self._edit.setPlaceholderText('输入常数，回车确认')
        self._edit.returnPressed.connect(self._on_edit_return)
        self._edit.installEventFilter(self)
        self._edit.hide()
        lo.addWidget(self._edit, 1)

        # 删除按钮（固定槽位时隐藏）
        self._del_btn = None
        if show_delete:
            self._del_btn = QToolButton(self)
            self._del_btn.setText('✕')
            self._del_btn.setToolTip('删除此计算元')
            self._del_btn.setAutoRaise(True)
            self._del_btn.clicked.connect(self._on_delete)
            lo.addWidget(self._del_btn)

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _emit(self, action: str) -> None:
        self.action_requested.emit(self._index, action)

    def _on_delete(self) -> None:
        self.remove_requested.emit(self._index)

    def _on_edit_return(self) -> None:
        self.constant_submitted.emit(self._index, self._edit.text())

    def eventFilter(self, obj, event):
        # Esc 取消常数输入；失焦 → 有内容则提交判定，空则取消
        if obj is self._edit and event.type() == QEvent.Type.KeyPress:
            if event.key() == Qt.Key.Key_Escape:
                self.cancel_constant()
                self.constant_cancelled.emit(self._index)
                return True
        elif obj is self._edit and event.type() == QEvent.Type.FocusOut:
            if self._edit.text().strip():
                self.constant_submitted.emit(self._index, self._edit.text())
            else:
                self.cancel_constant()
                self.constant_cancelled.emit(self._index)
        return super().eventFilter(obj, event)

    # ------------------------------------------------------------------
    # 公开方法（供 SidePanel / 控制器调用）
    # ------------------------------------------------------------------

    def set_index(self, index: int) -> None:
        """删除槽位后重排索引。"""
        self._index = index

    @property
    def is_editing(self) -> bool:
        """是否处于常数输入态。"""
        return not self._edit.isHidden()

    def set_display(self, text: str) -> None:
        """退出常数输入态，内容区显示结果文本。"""
        self._edit.hide()
        self._text_btn.setText(text)
        self._text_btn.show()

    def show_editor(self) -> None:
        """进入常数输入态：内容区切换为输入框（箭头保持可用）。"""
        self._edit.clear()
        self._text_btn.hide()
        self._edit.show()
        self._edit.setFocus()

    def cancel_constant(self) -> None:
        """取消常数输入，回到文本按钮态（原文本保留）。"""
        self._edit.hide()
        self._text_btn.show()

    def reset(self) -> None:
        """清空为初始状态。"""
        self._edit.hide()
        self._text_btn.setText(self._initial_text)
        self._text_btn.show()


class DecimalsSlot(QWidget):
    """保留小数位数选择：左箭头（菜单）+ 内容区（文本/输入框）。

    交互模式与 OperandSlot 一致：箭头固定左侧，任何状态下可重新选择；
    菜单「默认（自动）」= 与计算元逐位置小数位数最多者一致，
    菜单「手动输入位数」→ 内容区切换为输入框（回车提交 / Esc 取消）。
    """

    mode_changed = pyqtSignal(str)       # 'auto' | 'manual'
    digits_submitted = pyqtSignal(str)   # 手动输入的位数文本
    cancelled = pyqtSignal()             # Esc 取消手动输入

    def __init__(self, parent=None):
        super().__init__(parent)
        lo = QHBoxLayout(self)
        lo.setContentsMargins(0, 0, 0, 0)
        lo.setSpacing(2)

        self._menu_btn = QToolButton(self)
        self._menu_btn.setToolTip('选择保留小数位数')
        self._menu_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._menu_btn.setAutoRaise(True)
        self._menu_btn.setFixedWidth(22)

        menu = QMenu(self._menu_btn)
        for text, action in [('默认（自动）', 'auto'), ('手动输入位数', 'manual')]:
            act = menu.addAction(text)
            act.triggered.connect(
                lambda checked=False, a=action: self._emit(a))
        self._menu_btn.setMenu(menu)
        lo.addWidget(self._menu_btn)

        self._text_btn = QToolButton(self)
        self._text_btn.setText('保留位数：默认（自动）')
        self._text_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self._text_btn.setAutoRaise(True)
        self._text_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        lo.addWidget(self._text_btn, 1)

        self._edit = QLineEdit(self)
        self._edit.setPlaceholderText('输入位数 0-10，回车确认')
        self._edit.returnPressed.connect(self._on_edit_return)
        self._edit.installEventFilter(self)
        self._edit.hide()
        lo.addWidget(self._edit, 1)

    def _emit(self, action: str) -> None:
        self.mode_changed.emit(action)

    def _on_edit_return(self) -> None:
        self.digits_submitted.emit(self._edit.text())

    def eventFilter(self, obj, event):
        # Esc 取消手动输入；失焦 → 有内容则提交判定，空则取消
        if obj is self._edit and event.type() == QEvent.Type.KeyPress:
            if event.key() == Qt.Key.Key_Escape:
                self.cancel()
                self.cancelled.emit()
                return True
        elif obj is self._edit and event.type() == QEvent.Type.FocusOut:
            if self._edit.text().strip():
                self.digits_submitted.emit(self._edit.text())
            else:
                self.cancel()
                self.cancelled.emit()
        return super().eventFilter(obj, event)

    @property
    def is_editing(self) -> bool:
        return not self._edit.isHidden()

    def show_editor(self) -> None:
        """进入手动输入态：内容区切换为输入框（箭头保持可用）。"""
        self._edit.clear()
        self._text_btn.hide()
        self._edit.show()
        self._edit.setFocus()

    def cancel(self) -> None:
        """取消手动输入，回到文本按钮态（原文本保留）。"""
        self._edit.hide()
        self._text_btn.show()

    def set_display(self, text: str) -> None:
        """提交成功后设置显示文本（退出编辑态）。"""
        self._edit.hide()
        self._text_btn.setText(text)
        self._text_btn.show()


class QuantileSlot(QWidget):
    """分位数选择：左箭头（菜单）+ 内容区（文本/输入框）。

    交互模式与 DecimalsSlot 一致：箭头固定左侧，任何状态下可重新选择；
    菜单「中位数」= 默认 0.5 分位；「手动输入分位数(小数)」→
    内容区切换为输入框（回车提交 / Esc 取消），控制器做 (0,1) 校验。
    """

    mode_changed = pyqtSignal(str)        # 'median' | 'manual'
    value_submitted = pyqtSignal(str)     # 手动输入的分位数文本
    cancelled = pyqtSignal()              # Esc 取消手动输入

    def __init__(self, parent=None):
        super().__init__(parent)
        lo = QHBoxLayout(self)
        lo.setContentsMargins(0, 0, 0, 0)
        lo.setSpacing(2)

        self._menu_btn = QToolButton(self)
        self._menu_btn.setToolTip('选择分位数')
        self._menu_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._menu_btn.setAutoRaise(True)
        self._menu_btn.setFixedWidth(22)

        menu = QMenu(self._menu_btn)
        for text, action in [('中位数', 'median'),
                             ('手动输入分位数(小数)', 'manual')]:
            act = menu.addAction(text)
            act.triggered.connect(
                lambda checked=False, a=action: self._emit(a))
        self._menu_btn.setMenu(menu)
        lo.addWidget(self._menu_btn)

        self._text_btn = QToolButton(self)
        self._text_btn.setText('中位数')
        self._text_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self._text_btn.setAutoRaise(True)
        self._text_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        lo.addWidget(self._text_btn, 1)

        self._edit = QLineEdit(self)
        self._edit.setPlaceholderText('输入分位数 0-1，回车确认')
        self._edit.returnPressed.connect(self._on_edit_return)
        self._edit.installEventFilter(self)
        self._edit.hide()
        lo.addWidget(self._edit, 1)

    def _emit(self, action: str) -> None:
        self.mode_changed.emit(action)

    def _on_edit_return(self) -> None:
        self.value_submitted.emit(self._edit.text())

    def eventFilter(self, obj, event):
        # Esc 取消；失焦 → 有内容则提交判定，空则取消
        if obj is self._edit and event.type() == QEvent.Type.KeyPress:
            if event.key() == Qt.Key.Key_Escape:
                self.cancel()
                self.cancelled.emit()
                return True
        elif obj is self._edit and event.type() == QEvent.Type.FocusOut:
            if self._edit.text().strip():
                self.value_submitted.emit(self._edit.text())
            else:
                self.cancel()
                self.cancelled.emit()
        return super().eventFilter(obj, event)

    @property
    def is_editing(self) -> bool:
        return not self._edit.isHidden()

    def show_editor(self) -> None:
        self._edit.clear()
        self._text_btn.hide()
        self._edit.show()
        self._edit.setFocus()

    def cancel(self) -> None:
        self._edit.hide()
        self._text_btn.show()

    def set_display(self, text: str) -> None:
        self._edit.hide()
        self._text_btn.setText(text)
        self._text_btn.show()


class ModeSlot(QWidget):
    """模式选择：左箭头（菜单）+ 文本显示（无手动输入）。

    交互模式与 QuantileSlot 一致但更简单：箭头固定左侧，菜单
    「默认」/「精确」，选中即生效（默认「默认」），无输入框。
    """

    mode_changed = pyqtSignal(str)   # 'default' | 'precise'

    def __init__(self, options=None, parent=None):
        super().__init__(parent)
        options = options or ['默认', '精确']
        self._options = options
        lo = QHBoxLayout(self)
        lo.setContentsMargins(0, 0, 0, 0)
        lo.setSpacing(2)

        self._menu_btn = QToolButton(self)
        self._menu_btn.setToolTip('选择模式')
        self._menu_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._menu_btn.setAutoRaise(True)
        self._menu_btn.setFixedWidth(22)

        menu = QMenu(self._menu_btn)
        for text in options:
            act = menu.addAction(text)
            act.triggered.connect(
                lambda checked=False, o=text: self._emit(o))
        self._menu_btn.setMenu(menu)
        lo.addWidget(self._menu_btn)

        self._text_btn = QToolButton(self)
        self._text_btn.setText(options[0])
        self._text_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self._text_btn.setAutoRaise(True)
        self._text_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        lo.addWidget(self._text_btn, 1)

    def _emit(self, text: str) -> None:
        self.set_display(text)
        self.mode_changed.emit(text)

    def set_display(self, text: str) -> None:
        self._text_btn.setText(text)


class InspectTypeSlot(QWidget):
    """检定类型选择：左箭头（菜单）+ 内容区（文本/输入框）。

    菜单 4 选项：任意判定/存在判定（无输入）→ 直接生效；
    存在型数量自定义/存在型比例自定义 → 内容区切换为输入框
    （回车提交 / Esc 取消），控制器做对应校验。
    """

    type_changed = pyqtSignal(str)        # '任意判定'|'存在判定'|'存在型数量自定义'|'存在型比例自定义'
    value_submitted = pyqtSignal(str)     # 数量/比例自定义的输入文本
    cancelled = pyqtSignal()              # Esc 取消输入

    def __init__(self, options=None, parent=None):
        super().__init__(parent)
        options = options or ['任意判定', '存在判定',
                              '存在型数量自定义', '存在型比例自定义']
        self._options = options
        lo = QHBoxLayout(self)
        lo.setContentsMargins(0, 0, 0, 0)
        lo.setSpacing(2)

        self._menu_btn = QToolButton(self)
        self._menu_btn.setToolTip('选择检定类型')
        self._menu_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._menu_btn.setAutoRaise(True)
        self._menu_btn.setFixedWidth(22)

        menu = QMenu(self._menu_btn)
        for text in options:
            act = menu.addAction(text)
            act.triggered.connect(
                lambda checked=False, o=text: self._emit(o))
        self._menu_btn.setMenu(menu)
        lo.addWidget(self._menu_btn)

        self._text_btn = QToolButton(self)
        self._text_btn.setText(options[0])
        self._text_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self._text_btn.setAutoRaise(True)
        self._text_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        lo.addWidget(self._text_btn, 1)

        self._edit = QLineEdit(self)
        self._edit.setPlaceholderText('输入数值，回车确认')
        self._edit.returnPressed.connect(self._on_edit_return)
        self._edit.installEventFilter(self)
        self._edit.hide()
        lo.addWidget(self._edit, 1)

    def _emit(self, text: str) -> None:
        self.type_changed.emit(text)

    def _on_edit_return(self) -> None:
        self.value_submitted.emit(self._edit.text())

    def eventFilter(self, obj, event):
        # Esc 取消；失焦 → 有内容则提交判定，空则取消
        if obj is self._edit and event.type() == QEvent.Type.KeyPress:
            if event.key() == Qt.Key.Key_Escape:
                self.cancel()
                self.cancelled.emit()
                return True
        elif obj is self._edit and event.type() == QEvent.Type.FocusOut:
            if self._edit.text().strip():
                self.value_submitted.emit(self._edit.text())
            else:
                self.cancel()
                self.cancelled.emit()
        return super().eventFilter(obj, event)

    @property
    def is_editing(self) -> bool:
        return not self._edit.isHidden()

    def show_editor(self) -> None:
        self._edit.clear()
        self._text_btn.hide()
        self._edit.show()
        self._edit.setFocus()

    def cancel(self) -> None:
        self._edit.hide()
        self._text_btn.show()

    def set_display(self, text: str) -> None:
        self._edit.hide()
        self._text_btn.setText(text)
        self._text_btn.show()

    def set_text(self, text: str) -> None:
        """仅更新显示文本（不退出编辑态；用于回显默认值）。"""
        self._text_btn.setText(text)


class OutputSlot(QWidget):
    """输出结果选择：左箭头（菜单）+ 内容区（文本/输入框）。

    菜单「默认」（显示默认值 0/1）或「自定义」→ 内容区切换为输入框
    （回车提交 / Esc 取消）。
    """

    mode_changed = pyqtSignal(str)        # 'default' | 'custom'
    value_submitted = pyqtSignal(str)     # 自定义输出文本
    cancelled = pyqtSignal()              # Esc 取消输入

    def __init__(self, default_text: str, parent=None):
        super().__init__(parent)
        self._default_text = default_text
        lo = QHBoxLayout(self)
        lo.setContentsMargins(0, 0, 0, 0)
        lo.setSpacing(2)

        self._menu_btn = QToolButton(self)
        self._menu_btn.setToolTip('选择输出方式')
        self._menu_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._menu_btn.setAutoRaise(True)
        self._menu_btn.setFixedWidth(22)

        menu = QMenu(self._menu_btn)
        for text, action in [('默认', 'default'), ('自定义', 'custom')]:
            act = menu.addAction(text)
            act.triggered.connect(
                lambda checked=False, a=action: self._emit(a))
        self._menu_btn.setMenu(menu)
        lo.addWidget(self._menu_btn)

        self._text_btn = QToolButton(self)
        self._text_btn.setText(default_text)
        self._text_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self._text_btn.setAutoRaise(True)
        self._text_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        lo.addWidget(self._text_btn, 1)

        self._edit = QLineEdit(self)
        self._edit.setPlaceholderText('输入输出内容，回车确认')
        self._edit.returnPressed.connect(self._on_edit_return)
        self._edit.installEventFilter(self)
        self._edit.hide()
        lo.addWidget(self._edit, 1)

    def _emit(self, action: str) -> None:
        self.mode_changed.emit(action)

    def _on_edit_return(self) -> None:
        self.value_submitted.emit(self._edit.text())

    def eventFilter(self, obj, event):
        # Esc 取消；失焦 → 有内容则提交判定，空则取消
        if obj is self._edit and event.type() == QEvent.Type.KeyPress:
            if event.key() == Qt.Key.Key_Escape:
                self.cancel()
                self.cancelled.emit()
                return True
        elif obj is self._edit and event.type() == QEvent.Type.FocusOut:
            if self._edit.text().strip():
                self.value_submitted.emit(self._edit.text())
            else:
                self.cancel()
                self.cancelled.emit()
        return super().eventFilter(obj, event)

    @property
    def is_editing(self) -> bool:
        return not self._edit.isHidden()

    def show_editor(self) -> None:
        self._edit.clear()
        self._text_btn.hide()
        self._edit.show()
        self._edit.setFocus()

    def cancel(self) -> None:
        self._edit.hide()
        self._text_btn.show()

    def set_display(self, text: str) -> None:
        self._edit.hide()
        self._text_btn.setText(text)
        self._text_btn.show()

    def reset_default(self) -> None:
        """恢复显示默认值。"""
        self._edit.hide()
        self._text_btn.setText(self._default_text)
        self._text_btn.show()


class SidePanel(QWidget):
    """左侧面板。映射文件夹子版块 + 底部空白（预留脚本交互）。"""

    file_clicked = pyqtSignal(str)
    mode_changed = pyqtSignal(str)
    script_run_requested = pyqtSignal(str)
    option_changed = pyqtSignal(str, str)
    confirm_clicked = pyqtSignal()
    auto_select_clicked = pyqtSignal()
    # --- 自定义运算按钮信号 ---
    open_editor_clicked = pyqtSignal()    # 「打开编辑器」
    check_errors_clicked = pyqtSignal()   # 「检查报错」
    # --- 框选排除按钮信号 ---
    exclude_row_clicked = pyqtSignal()   # 「排除首行」
    exclude_col_clicked = pyqtSignal()   # 「排除首列」
    # --- 小数补齐信号 ---
    pad_mode_changed = pyqtSignal(str)        # 区域选择模式 'auto'|'row'|'col'|'range'
    pad_decimals_mode_changed = pyqtSignal(str)  # 位数模式 'default'|'custom'
    pad_decimals_value_submitted = pyqtSignal(str)  # 自定义位数提交
    pad_decimals_cancelled = pyqtSignal()    # Esc 取消位数输入
    # --- 计算元交互信号 ---
    operand_action = pyqtSignal(int, str)              # (index, action)
    operand_constant_submitted = pyqtSignal(int, str)  # (index, text)
    operand_constant_cancelled = pyqtSignal(int)       # (index) 用户 Esc 取消常数输入
    operand_added = pyqtSignal()                       # 用户点「＋ 添加计算元」
    operand_removed = pyqtSignal(int)                  # 用户删除某计算元 (index)
    # --- 保留小数位数信号 ---
    decimals_mode_changed = pyqtSignal(str)            # 'auto' | 'manual'
    decimals_digits_submitted = pyqtSignal(str)        # 手动输入的位数文本
    decimals_cancelled = pyqtSignal()                  # Esc 取消手动输入
    # --- 输出位置信号 ---
    output_clipboard = pyqtSignal()
    output_pick = pyqtSignal()
    # --- 三角函数信号 ---
    function_changed = pyqtSignal(str)   # 函数下拉选择变化
    unit_changed = pyqtSignal(str)       # 角度单位变化（弧度/度）
    trig_validate = pyqtSignal()         # 点「校验并运算」
    # --- 分位数信号 ---
    quantile_mode_changed = pyqtSignal(str)   # 'median' | 'manual'
    quantile_value_submitted = pyqtSignal(str)  # 手动输入的分位数文本
    quantile_cancelled = pyqtSignal()          # Esc 取消手动输入
    # --- 模式选择信号 ---
    mode_selected = pyqtSignal(str)            # '默认' | '精确'
    # --- 计数条件信号 ---
    operator_changed = pyqtSignal(str)         # 符号下拉变化
    constant_submitted = pyqtSignal(str)       # 常数输入回车/失焦提交
    constant_cancelled = pyqtSignal()          # Esc 取消常数输入
    constant_changed = pyqtSignal()            # 常数内容变化（重置未确认）
    # --- 查找脚本信号 ---
    text_submitted = pyqtSignal(str)           # 查找文本提交（回车/失焦）
    text_cancelled = pyqtSignal()              # Esc 取消文本输入
    text_changed = pyqtSignal()                # 文本内容变化（重置未确认）
    ignore_head_changed = pyqtSignal(str)      # 忽略首格选项变化（'忽略首格'/'不忽略首格'）
    find_output_chosen = pyqtSignal(str)       # 查找输出方式（'hint'/'row'/'col'）
    find_pick_ref_clicked = pyqtSignal()       # 查找「选择参考列/行」按钮（点选模式开关）
    # --- 检定面板信号 ---
    inspect_type_changed = pyqtSignal(str)     # 检定类型变化
    inspect_value_submitted = pyqtSignal(str)  # 数量/比例自定义输入提交
    inspect_value_cancelled = pyqtSignal()     # Esc 取消输入
    fail_mode_changed = pyqtSignal(str)        # 不通过框模式 'default'|'custom'
    fail_value_submitted = pyqtSignal(str)     # 不通过框自定义提交
    fail_value_cancelled = pyqtSignal()        # 不通过框 Esc 取消
    pass_mode_changed = pyqtSignal(str)        # 通过框模式 'default'|'custom'
    pass_value_submitted = pyqtSignal(str)     # 通过框自定义提交
    pass_value_cancelled = pyqtSignal()        # 通过框 Esc 取消

    SPREADSHEET_FILTERS = ['*.csv', '*.xlsx', '*.xls', '*.txt', '*.tsv']
    SCRIPT_FILTERS = [
        '*.py', '*.js', '*.ts', '*.vbs', '*.ps1', '*.bat', '*.sh',
        '*.rb', '*.lua', '*.txt', '*.md'
    ]

    MODE_FILES = 'files'
    MODE_SCRIPTS = 'scripts'

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_mode = self.MODE_FILES
        self._file_folder = ''
        self._script_folder = ''
        # 文件树自定义顺序（持久化到配置；'files'/'scripts' 两份）
        self._settings = AppSettings()
        self._settings.load()
        self._tree_order: dict[str, dict] = self._settings.get(
            'file_tree_order', {})
        self._opt_groups: dict[str, _OptionGroup] = {}
        self._confirm_btn: QPushButton | None = None
        self._auto_btn: QPushButton | None = None
        self._open_editor_btn: QPushButton | None = None
        self._check_errors_btn: QPushButton | None = None
        self._script_rows: list = []
        self._script_widgets: list[QWidget] = []
        self._confirm_shortcuts: list = []
        # 计算元 / 输出按钮状态
        self._operand_slots: list['OperandSlot'] = []
        self._operand_rows: list = []        # 与 _operand_slots 平行的槽位行布局
        self._pick_kind: str = 'column'      # 当前运算方向的点选类型
        self._operand_text_mode: bool = False  # 当前计算元是否为文本模式（添加新框时沿用）
        self._confirm_row = None             # 确定按钮所在行布局
        self._editor_open_count = 0          # 处于常数输入态的槽位数
        self._add_operand_btn: QPushButton | None = None
        self._add_operand_btn_row = None      # 「＋ 添加计算元」按钮行（新槽位插到它之前）
        self._decimals_slot: 'DecimalsSlot | None' = None
        self._decimals_row = None             # 保留小数位数行布局（新增框插到它之前）
        self._operator_row = None             # 运算符号行布局（第一个计算元之后）
        self._clip_btn: QPushButton | None = None
        self._pick_btn: QPushButton | None = None
        # 框选排除按钮状态
        self._exclude_row_btn: QPushButton | None = None
        self._exclude_col_btn: QPushButton | None = None
        # 小数补齐面板状态
        self._pad_mode_group: _OptionGroup | None = None
        self._pad_decimals_slot: QuantileSlot | None = None
        self._pad_decimals_value = 'default'
        # 三角函数面板状态
        self._func_combo = None               # 函数下拉框
        self._func_group: _OptionGroup | None = None  # 角度单位按钮组
        self._func_row = None                 # 函数行
        self._unit_row = None                 # 单位行
        # 分位数面板状态
        self._dir_group: _OptionGroup | None = None  # 方向按钮组（对行/对列）
        self._quantile_slot: 'QuantileSlot | None' = None  # 分位数输入框
        self._quantile_row = None              # 分位数行
        self._quantile_value = ''              # 已确认的分位数值（'median' 或小数文本）
        # 模式选择面板状态
        self._mode_slot: 'ModeSlot | None' = None  # 模式选择框
        self._mode_row = None                  # 模式行
        self._mode_value = ''                  # 已选模式（'默认' 或 '精确'）
        # 计数条件面板状态
        self._op_combo = None                  # 符号下拉框
        self._const_edit: QLineEdit | None = None  # 常数输入框
        self._const_edit_row = None            # 常数行
        self._count_operator = ''              # 已选符号
        self._count_constant: str | None = None  # 已确认常数文本（None=未输入）
        # 检定面板状态
        self._inspect_type_slot = None         # 检定类型选择/输入框
        self._fail_slot = None                 # 不通过输出框
        self._pass_slot = None                 # 通过输出框
        self._inspect_type = ''                # 已选检定类型
        self._inspect_value: str | None = None  # 数量/比例自定义值（None=未输入/不需要）
        self._fail_result = '0'                # 不通过输出结果（默认 0）
        self._pass_result = '1'                # 通过输出结果（默认 1）
        self._setup_ui()
        self._setup_models()
        self._setup_shortcuts()

    # ------------------------------------------------------------------
    # 属性
    # ------------------------------------------------------------------

    @property
    def file_folder(self) -> str:
        return self._file_folder

    @file_folder.setter
    def file_folder(self, path: str) -> None:
        self._file_folder = path
        if path:
            self._set_tree_root(self._file_source, self._file_proxy, self._file_view, path)
            self._path_edit.setText(path)

    @property
    def script_folder(self) -> str:
        return self._script_folder

    @script_folder.setter
    def script_folder(self, path: str) -> None:
        self._script_folder = path
        if path:
            self._set_tree_root(self._script_source, self._script_proxy, self._script_view, path)

    def refresh_current(self) -> None:
        if self._current_mode == self.MODE_FILES:
            self._file_source.setRootPath(self._file_source.rootPath())
        else:
            self._script_source.setRootPath(self._script_source.rootPath())

    # --- 脚本面板方法 ---

    def set_script_prompt(self, text):
        self._script_prompt.setText(text)

    def show_script_buttons(self, groups, labels=None):
        self._clear_script_btns()
        # 每个按钮组单独一行，创建后立即铺进布局
        for key, options in groups.items():
            g = _OptionGroup(key, options)
            g.value_changed.connect(self.option_changed.emit)
            self._opt_groups[key] = g
            row = QHBoxLayout(); row.setSpacing(4)
            row.addWidget(g); row.addStretch()
            self._script_btn_area.addLayout(row)
            self._script_rows.append(row)
            self._script_widgets.extend(g._btns)

    # --- 分位数面板方法 ---

    def show_quantile_panel(self, direction_options: list[str]) -> None:
        """显示分位数步骤面板：方向互斥按钮组 → 分位数框 → 确定。

        确定按钮可用需：方向已选 且 分位数已确认（默认中位数, value='median'）。
        """
        self._clear_script_btns()
        # 1. 方向互斥按钮组（对行/对列）
        self._dir_group = _OptionGroup('direction', direction_options)
        self._dir_group.value_changed.connect(self.option_changed.emit)
        row = QHBoxLayout(); row.setSpacing(4)
        row.addWidget(self._dir_group); row.addStretch()
        self._script_btn_area.addLayout(row)
        self._script_rows.append(row)
        self._script_widgets.extend(self._dir_group._btns)
        # 2. 分位数输入框（默认中位数）
        self._quantile_slot = QuantileSlot(self)
        self._quantile_slot.mode_changed.connect(self.quantile_mode_changed.emit)
        self._quantile_slot.value_submitted.connect(self.quantile_value_submitted.emit)
        self._quantile_slot.cancelled.connect(self._on_quantile_cancelled)
        qrow = QHBoxLayout(); qrow.setSpacing(4)
        qrow.addWidget(self._quantile_slot)
        self._script_btn_area.addLayout(qrow)
        self._script_rows.append(qrow)
        self._quantile_row = qrow
        self._quantile_value = 'median'  # 默认中位数
        # 3. 确定按钮（默认禁用，需方向已选）
        self.show_confirm_button(enabled=False)

    def _on_quantile_cancelled(self) -> None:
        """用户 Esc 取消手动输入：关闭编辑态。"""
        self._editor_close()
        self.quantile_cancelled.emit()

    def show_quantile_editor(self) -> None:
        """进入手动输入分位数态。"""
        if self._quantile_slot is not None:
            self._quantile_slot.show_editor()
            self._editor_open()

    def set_quantile_display(self, text: str) -> None:
        """手动分位数提交成功后设置显示文本（退出编辑态）。"""
        if self._quantile_slot is not None:
            was_editing = self._quantile_slot.is_editing
            self._quantile_slot.set_display(text)
            if was_editing:
                self._editor_close()

    def reset_quantile(self, text: str = '中位数') -> None:
        """将分位数框恢复为指定显示（用于回到默认中位数）。"""
        if self._quantile_slot is not None:
            was_editing = self._quantile_slot.is_editing
            self._quantile_slot.set_display(text)
            if was_editing:
                self._editor_close()

    def get_direction_option(self) -> str:
        """获取当前选中的方向。"""
        return self._dir_group.current_value if self._dir_group is not None else None

    def get_quantile_value(self) -> str:
        """获取已确认的分位数值（'median' 或小数文本）。"""
        return self._quantile_value

    def set_quantile_value(self, value: str) -> None:
        """记录已确认的分位数值（控制器校验通过后调用）。"""
        self._quantile_value = value

    def quantile_readable(self) -> bool:
        """分位数是否可读（默认中位数或已确认手动值，编辑态不算）。"""
        if self._quantile_slot is None:
            return False
        return not self._quantile_slot.is_editing and bool(self._quantile_value)

    @property
    def direction_ready(self) -> bool:
        """方向按钮组是否已选中一项。"""
        return self._dir_group is not None and self._dir_group.current_value is not None

    # --- 模式选择面板方法 ---

    def show_mode_panel(self, direction_options: list[str],
                        mode_options=None) -> None:
        """显示模式步骤面板：方向互斥按钮组 → 模式选择框 → 确定。

        确定按钮可用需：方向已选 且 模式已选（默认「默认」恒满足）。
        """
        self._clear_script_btns()
        mode_options = mode_options or ['默认', '精确']
        # 1. 方向互斥按钮组（对行/对列）
        self._dir_group = _OptionGroup('direction', direction_options)
        self._dir_group.value_changed.connect(self.option_changed.emit)
        row = QHBoxLayout(); row.setSpacing(4)
        row.addWidget(self._dir_group); row.addStretch()
        self._script_btn_area.addLayout(row)
        self._script_rows.append(row)
        self._script_widgets.extend(self._dir_group._btns)
        # 2. 模式选择框（默认「默认」）
        self._mode_slot = ModeSlot(mode_options, self)
        self._mode_slot.mode_changed.connect(self.mode_selected.emit)
        mrow = QHBoxLayout(); mrow.setSpacing(4)
        mrow.addWidget(self._mode_slot)
        self._script_btn_area.addLayout(mrow)
        self._script_rows.append(mrow)
        self._mode_row = mrow
        self._mode_value = mode_options[0]  # 默认第一个选项
        # 3. 确定按钮（默认禁用，需方向已选）
        self.show_confirm_button(enabled=False)

    def get_mode_value(self) -> str:
        """获取当前选择的模式（如 '默认' / '精确'）。"""
        return self._mode_value

    def set_mode_value(self, value: str) -> None:
        """记录当前选择的模式。"""
        self._mode_value = value

    def mode_readable(self) -> bool:
        """模式是否已选（恒 True，默认第一个选项）。"""
        return self._mode_slot is not None and bool(self._mode_value)

    # --- 计数条件面板方法 ---

    def show_count_panel(self, direction_options: list[str],
                         operator_options=None) -> None:
        """显示计数步骤面板：方向互斥按钮组 → 符号下拉 → 常数输入框 → 确定。

        确定按钮可用需：方向已选 且 常数已输入且为有效实数。
        """
        self._clear_script_btns()
        operator_options = operator_options or ['=', '>', '<', '>=', '<=', '≠', '≡']
        # 1. 方向互斥按钮组（对行/对列）
        self._dir_group = _OptionGroup('direction', direction_options)
        self._dir_group.value_changed.connect(self.option_changed.emit)
        row = QHBoxLayout(); row.setSpacing(4)
        row.addWidget(self._dir_group); row.addStretch()
        self._script_btn_area.addLayout(row)
        self._script_rows.append(row)
        self._script_widgets.extend(self._dir_group._btns)
        # 2. 「计数条件」提示文本行
        cond_label = QLabel('计数条件')
        cond_label.setStyleSheet('font-weight: bold;')
        cond_row = QHBoxLayout(); cond_row.setSpacing(4)
        cond_row.addWidget(cond_label)
        cond_row.addStretch()
        self._script_btn_area.addLayout(cond_row)
        self._script_rows.append(cond_row)
        # 3. 数据 + 符号按钮 + 常数输入框（一排）
        self._op_btn = QToolButton(self)
        self._op_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._op_btn.setAutoRaise(True)
        self._op_btn.setToolTip('选择符号')
        self._op_btn.setText(operator_options[0])
        menu = QMenu(self._op_btn)
        for op in operator_options:
            act = menu.addAction(op)
            act.triggered.connect(
                lambda checked=False, o=op: self._on_op_selected(o))
        self._op_btn.setMenu(menu)
        self._op_btn.setMinimumWidth(36)  # 保证符号按钮足够宽显示
        # 隐藏下拉菜单指示箭头（保留菜单功能，外观更紧凑）
        self._op_btn.setStyleSheet(
            'QToolButton::menu-indicator { image: none; width: 0; }')
        self._const_edit = QLineEdit()
        self._const_edit.setPlaceholderText('输入常数，回车确认')
        self._const_edit.returnPressed.connect(self._on_const_return)
        self._const_edit.textChanged.connect(self._on_const_text_changed)
        self._const_edit.installEventFilter(self)
        cond_row2 = QHBoxLayout(); cond_row2.setSpacing(4)
        data_label = QLabel('数据')
        cond_row2.addWidget(data_label)
        cond_row2.addWidget(self._op_btn)
        cond_row2.addWidget(self._const_edit, 1)
        self._script_btn_area.addLayout(cond_row2)
        self._script_rows.append(cond_row2)
        self._count_operator = operator_options[0]  # 默认第一个符号
        self._count_constant = None  # 尚未确认
        # 4. 确定按钮（默认禁用）
        self.show_confirm_button(enabled=False)

    # --- 查找脚本面板方法 ---

    def show_find_lookup_panel(self, lookup_type: str,
                               operator_options=None,
                               ref_label: str = '参考列') -> None:
        """查找脚本条件面板：点选参考按钮 + 条件区（数据/文本）+ 确定。

        点选参考：先点「选择参考列/行」按钮 → 控制器进入点选模式并提示，
        此时点列头/行头才判定参考（避免点选与条件输入混用冲突）。
        数据查找：符号下拉 + 常数输入框；文本查找：文本输入框 + 忽略首格。
        """
        self._clear_script_btns()
        operator_options = operator_options or ['=', '>', '<', '>=', '<=', '≠', '≡']
        # 0. 点选参考按钮
        self._find_pick_btn = QPushButton(f'选择{ref_label}')
        self._find_pick_btn.clicked.connect(self.find_pick_ref_clicked.emit)
        row0 = QHBoxLayout(); row0.setSpacing(4)
        row0.addWidget(self._find_pick_btn); row0.addStretch()
        self._script_btn_area.addLayout(row0); self._script_rows.append(row0)
        self._script_widgets.append(self._find_pick_btn)
        if '数据' in lookup_type:
            cond_label = QLabel('查找条件')
            cond_label.setStyleSheet('font-weight: bold;')
            row = QHBoxLayout(); row.setSpacing(4)
            row.addWidget(cond_label); row.addStretch()
            self._script_btn_area.addLayout(row); self._script_rows.append(row)
            # 数据 + 符号下拉 + 常数输入框（复用 count 的组件与信号）
            self._op_btn = QToolButton(self)
            self._op_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
            self._op_btn.setAutoRaise(True)
            self._op_btn.setToolTip('选择符号')
            self._op_btn.setText(operator_options[0])
            menu = QMenu(self._op_btn)
            for op in operator_options:
                act = menu.addAction(op)
                act.triggered.connect(
                    lambda checked=False, o=op: self._on_op_selected(o))
            self._op_btn.setMenu(menu)
            self._op_btn.setMinimumWidth(36)
            self._op_btn.setStyleSheet(
                'QToolButton::menu-indicator { image: none; width: 0; }')
            self._const_edit = QLineEdit()
            self._const_edit.setPlaceholderText('输入常数，回车确认')
            self._const_edit.returnPressed.connect(self._on_const_return)
            self._const_edit.textChanged.connect(self._on_const_text_changed)
            self._const_edit.installEventFilter(self)
            row2 = QHBoxLayout(); row2.setSpacing(4)
            row2.addWidget(QLabel('数据'))
            row2.addWidget(self._op_btn)
            row2.addWidget(self._const_edit, 1)
            self._script_btn_area.addLayout(row2); self._script_rows.append(row2)
        else:
            # 文本查找：文本输入 + 忽略首格互斥
            self._find_text_edit = QLineEdit()
            self._find_text_edit.setPlaceholderText('输入查找文本，回车确认')
            self._find_text_edit.returnPressed.connect(self._on_find_text_return)
            self._find_text_edit.textChanged.connect(self._on_find_text_changed)
            self._find_text_edit.installEventFilter(self)
            row = QHBoxLayout(); row.setSpacing(4)
            row.addWidget(QLabel('查找文本'))
            row.addWidget(self._find_text_edit, 1)
            self._script_btn_area.addLayout(row); self._script_rows.append(row)
            self._find_ignore_group = _OptionGroup(
                'ignore_head', ['忽略首格', '不忽略首格'])
            self._find_ignore_group.value_changed.connect(
                lambda _k, v: self.ignore_head_changed.emit(v))
            row2 = QHBoxLayout(); row2.setSpacing(4)
            row2.addWidget(self._find_ignore_group); row2.addStretch()
            self._script_btn_area.addLayout(row2); self._script_rows.append(row2)
            # 默认"不忽略首格"
            self._find_ignore_group._btns[1].setChecked(True)
        self.show_confirm_button(enabled=False)

    def _on_find_text_return(self) -> None:
        """查找文本回车：提交给控制器。"""
        if self._find_text_edit is not None:
            self.text_submitted.emit(self._find_text_edit.text())

    def _on_find_text_changed(self) -> None:
        """查找文本内容变化：重置未确认并通知控制器。"""
        self.text_changed.emit()

    def show_find_output_panel(self) -> None:
        """查找脚本输出位置：提示栏 / 以行剪贴板 / 以列剪贴板（点击即输出）。"""
        self._clear_script_btns()
        for label, action in (('输出到提示栏', 'hint'),
                              ('以行输出到剪贴板', 'row'),
                              ('以列输出到剪贴板', 'col')):
            b = QPushButton(label)
            b.clicked.connect(lambda _=False, a=action:
                              self.find_output_chosen.emit(a))
            row = QHBoxLayout(); row.setSpacing(4)
            row.addWidget(b); row.addStretch()
            self._script_btn_area.addLayout(row)
            self._script_rows.append(row)
            self._script_widgets.append(b)

    def _on_op_selected(self, op: str) -> None:
        """符号按钮菜单选择：更新按钮显示、同步记录并通知控制器。"""
        if self._op_btn is not None:
            self._op_btn.setText(op)
        self._count_operator = op  # 面板侧同步记录，避免与按钮显示不一致
        self.operator_changed.emit(op)

    def _on_const_return(self) -> None:
        """常数输入回车：提交给控制器校验。"""
        if self._const_edit is not None:
            self.constant_submitted.emit(self._const_edit.text())

    def eventFilter(self, obj, event):
        # 常数/查找文本输入框：获得焦点 → 禁用 Enter 快捷键（避免吞回车）；
        # 失焦 → 自动确认；Esc → 取消并恢复
        is_find_text = obj is getattr(self, '_find_text_edit', None)
        is_const = obj is getattr(self, '_const_edit', None)
        if is_find_text or is_const:
            if event.type() == QEvent.Type.FocusIn:
                self._editor_open()
            elif event.type() == QEvent.Type.FocusOut:
                self._editor_close()
                if getattr(self, '_const_edit', None) is not None and is_const \
                        and self._const_edit.text().strip():
                    self.constant_submitted.emit(self._const_edit.text())
                elif getattr(self, '_find_text_edit', None) is not None \
                        and is_find_text \
                        and self._find_text_edit.text().strip():
                    self.text_submitted.emit(self._find_text_edit.text())
            elif event.type() == QEvent.Type.KeyPress:
                if event.key() == Qt.Key.Key_Escape:
                    self._editor_close()
                    if is_const:
                        self.constant_cancelled.emit()
                    else:
                        self.text_cancelled.emit()
                    return True
        return super().eventFilter(obj, event)

    def set_count_constant(self, value: str) -> None:
        """记录已确认的常数（控制器校验通过后调用），并退出输入态。"""
        self._count_constant = value
        if self._const_edit is not None:
            self._const_edit.clearFocus()  # 触发 FocusOut → _editor_close

    def _on_const_text_changed(self, text: str) -> None:
        """常数输入框内容变化：重置为未确认，并刷新确定按钮。"""
        self._count_constant = None
        # 通知控制器刷新对应确定按钮（计数或检定场景）
        self.constant_changed.emit()

    def set_operator(self, text: str) -> None:
        """记录已选符号。"""
        self._count_operator = text

    def get_count_operator(self) -> str:
        return self._count_operator

    def get_count_constant(self) -> str | None:
        return self._count_constant

    def count_ready(self) -> bool:
        """计数条件是否就绪（常数已确认，符号恒有值）。"""
        return self._const_edit is not None and self._count_constant is not None

    # --- 检定面板方法 ---

    def show_inspect_panel(self, direction_options: list[str],
                           operator_options=None, type_options=None) -> None:
        """显示检定步骤面板：方向 → 检定条件 → 检定类型 → 输出结果 → 确定。"""
        self._clear_script_btns()
        operator_options = operator_options or ['=', '>', '<', '>=', '<=', '≠', '≡']
        type_options = type_options or ['任意判定', '存在判定',
                                        '存在型数量自定义', '存在型比例自定义']
        # 1. 方向互斥按钮组（对行/对列）
        self._dir_group = _OptionGroup('direction', direction_options)
        self._dir_group.value_changed.connect(self.option_changed.emit)
        row = QHBoxLayout(); row.setSpacing(4)
        row.addWidget(self._dir_group); row.addStretch()
        self._script_btn_area.addLayout(row)
        self._script_rows.append(row)
        self._script_widgets.extend(self._dir_group._btns)
        # 2. 「检定条件」提示文本行
        cond_label = QLabel('检定条件')
        cond_label.setStyleSheet('font-weight: bold;')
        cond_row = QHBoxLayout(); cond_row.setSpacing(4)
        cond_row.addWidget(cond_label); cond_row.addStretch()
        self._script_btn_area.addLayout(cond_row)
        self._script_rows.append(cond_row)
        # 3. 数据 + 符号按钮 + 常数输入框（一排）
        self._op_btn = QToolButton(self)
        self._op_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._op_btn.setAutoRaise(True)
        self._op_btn.setToolTip('选择符号')
        self._op_btn.setText(operator_options[0])
        menu = QMenu(self._op_btn)
        for op in operator_options:
            act = menu.addAction(op)
            act.triggered.connect(
                lambda checked=False, o=op: self._on_op_selected(o))
        self._op_btn.setMenu(menu)
        self._op_btn.setMinimumWidth(36)
        self._op_btn.setStyleSheet(
            'QToolButton::menu-indicator { image: none; width: 0; }')
        self._const_edit = QLineEdit()
        self._const_edit.setPlaceholderText('输入常数，回车确认')
        self._const_edit.returnPressed.connect(self._on_const_return)
        self._const_edit.textChanged.connect(self._on_const_text_changed)
        self._const_edit.installEventFilter(self)
        cond_row2 = QHBoxLayout(); cond_row2.setSpacing(4)
        data_label = QLabel('数据')
        cond_row2.addWidget(data_label)
        cond_row2.addWidget(self._op_btn)
        cond_row2.addWidget(self._const_edit, 1)
        self._script_btn_area.addLayout(cond_row2)
        self._script_rows.append(cond_row2)
        self._count_operator = operator_options[0]
        self._count_constant = None
        # 4. 「检定类型」行
        type_label = QLabel('检定类型:')
        self._inspect_type_slot = InspectTypeSlot(type_options, self)
        self._inspect_type_slot.type_changed.connect(self.inspect_type_changed.emit)
        self._inspect_type_slot.value_submitted.connect(self.inspect_value_submitted.emit)
        self._inspect_type_slot.cancelled.connect(self.inspect_value_cancelled.emit)
        type_row = QHBoxLayout(); type_row.setSpacing(4)
        type_row.addWidget(type_label)
        type_row.addWidget(self._inspect_type_slot, 1)
        self._script_btn_area.addLayout(type_row)
        self._script_rows.append(type_row)
        self._inspect_type = type_options[0]
        self._inspect_value = None
        # 5. 「输出结果」行：不通过框 + 通过框
        out_label = QLabel('输出结果:')
        self._fail_slot = OutputSlot('0', self)   # 不通过，默认 0
        self._fail_slot.mode_changed.connect(self.fail_mode_changed.emit)
        self._fail_slot.value_submitted.connect(self.fail_value_submitted.emit)
        self._fail_slot.cancelled.connect(self.fail_value_cancelled.emit)
        self._pass_slot = OutputSlot('1', self)   # 通过，默认 1
        self._pass_slot.mode_changed.connect(self.pass_mode_changed.emit)
        self._pass_slot.value_submitted.connect(self.pass_value_submitted.emit)
        self._pass_slot.cancelled.connect(self.pass_value_cancelled.emit)
        out_row = QHBoxLayout(); out_row.setSpacing(4)
        out_row.addWidget(out_label)
        out_row.addWidget(self._fail_slot, 1)
        out_row.addWidget(self._pass_slot, 1)
        self._script_btn_area.addLayout(out_row)
        self._script_rows.append(out_row)
        self._fail_result = '0'
        self._pass_result = '1'
        # 6. 确定按钮（默认禁用）
        self.show_confirm_button(enabled=False)

    # --- 检定面板访问方法 ---

    def inspect_type_ready(self) -> bool:
        """检定类型就绪：任意/存在恒满足；数量/比例需对应值已确认。"""
        if self._inspect_type_slot is None:
            return False
        if self._inspect_type in ('存在型数量自定义', '存在型比例自定义'):
            return self._inspect_value is not None and not self._inspect_type_slot.is_editing
        return bool(self._inspect_type)

    def inspect_ready(self) -> bool:
        """检定整体就绪：方向 + 常数 + 检定类型 + 输出两框（均为已确认值）。"""
        return (self.direction_ready and self.count_ready()
                and self.inspect_type_ready()
                and self._fail_slot is not None and self._pass_slot is not None
                and self._fail_result is not None and self._pass_result is not None)

    def set_inspect_type(self, text: str) -> None:
        self._inspect_type = text
        if text in ('存在型数量自定义', '存在型比例自定义'):
            self._inspect_value = None  # 需重新输入
        else:
            self._inspect_value = None  # 无需值

    def set_inspect_value(self, value: str) -> None:
        self._inspect_value = value

    def get_inspect_type(self) -> str:
        return self._inspect_type

    def get_inspect_value(self) -> str | None:
        return self._inspect_value

    def set_fail_result(self, text: str) -> None:
        self._fail_result = text

    def set_pass_result(self, text: str) -> None:
        self._pass_result = text

    def get_fail_result(self) -> str:
        return self._fail_result

    def get_pass_result(self) -> str:
        return self._pass_result

    def show_inspect_type_editor(self) -> None:
        if self._inspect_type_slot is not None:
            self._inspect_type_slot.show_editor()
            self._editor_open()

    def set_inspect_type_display(self, text: str) -> None:
        if self._inspect_type_slot is not None:
            was_editing = self._inspect_type_slot.is_editing
            self._inspect_type_slot.set_display(text)
            if was_editing:
                self._editor_close()

    def reset_inspect_type(self, text: str) -> None:
        if self._inspect_type_slot is not None:
            was_editing = self._inspect_type_slot.is_editing
            self._inspect_type_slot.set_text(text)
            if was_editing:
                self._editor_close()

    def show_fail_editor(self) -> None:
        if self._fail_slot is not None:
            self._fail_slot.show_editor()
            self._editor_open()

    def set_fail_display(self, text: str) -> None:
        if self._fail_slot is not None:
            was_editing = self._fail_slot.is_editing
            self._fail_slot.set_display(text)
            if was_editing:
                self._editor_close()

    def reset_fail(self) -> None:
        if self._fail_slot is not None:
            was_editing = self._fail_slot.is_editing
            self._fail_slot.reset_default()
            if was_editing:
                self._editor_close()

    def show_pass_editor(self) -> None:
        if self._pass_slot is not None:
            self._pass_slot.show_editor()
            self._editor_open()

    def set_pass_display(self, text: str) -> None:
        if self._pass_slot is not None:
            was_editing = self._pass_slot.is_editing
            self._pass_slot.set_display(text)
            if was_editing:
                self._editor_close()

    def reset_pass(self) -> None:
        if self._pass_slot is not None:
            was_editing = self._pass_slot.is_editing
            self._pass_slot.reset_default()
            if was_editing:
                self._editor_close()

    def show_confirm_button(self, enabled=False):
        if not hasattr(self, '_confirm_btn') or self._confirm_btn is None:
            self._confirm_btn = QPushButton('确定')
            self._confirm_btn.clicked.connect(self.confirm_clicked.emit)
            # 确定按钮单独一行，只铺一次
            row = QHBoxLayout(); row.setSpacing(4)
            row.addStretch(); row.addWidget(self._confirm_btn)
            self._script_btn_area.addLayout(row)
            self._script_rows.append(row)
            self._confirm_row = row
        self._confirm_btn.setEnabled(enabled)
        # 只在无输入框打开时恢复 Enter 快捷键（否则输入框回车被全局快捷键吞掉，
        # 与 _editor_open/_editor_close 的计数器协调；count/inspect 常数框同理）
        if self._editor_open_count == 0:
            for sc in self._confirm_shortcuts:
                sc.setEnabled(True)

    def show_custom_calc_buttons(self, confirm_enabled=False):
        """自定义运算步骤：打开编辑器 / 检查报错 / 确定 三按钮。

        设计记录（02-操作类型.md）：编辑器关闭时侧栏显示三按钮，
        点「打开编辑器」才打开编辑器弹窗。
        """
        # 1. 打开编辑器按钮
        self._open_editor_btn = QPushButton('打开编辑器')
        self._open_editor_btn.clicked.connect(self.open_editor_clicked.emit)
        row = QHBoxLayout(); row.setSpacing(4)
        row.addWidget(self._open_editor_btn); row.addStretch()
        self._script_btn_area.addLayout(row)
        self._script_rows.append(row)
        # 2. 检查报错按钮
        self._check_errors_btn = QPushButton('检查报错')
        self._check_errors_btn.clicked.connect(self.check_errors_clicked.emit)
        row2 = QHBoxLayout(); row2.setSpacing(4)
        row2.addWidget(self._check_errors_btn); row2.addStretch()
        self._script_btn_area.addLayout(row2)
        self._script_rows.append(row2)
        # 3. 确定按钮（默认禁用，构建积木后由控制器点亮）
        self.show_confirm_button(enabled=confirm_enabled)

    def show_auto_select_button(self):
        """框选区域步骤：显示「自动识别整个表格」按钮。"""
        if self._auto_btn is None:
            self._auto_btn = QPushButton('🔍 自动识别整个表格')
            self._auto_btn.clicked.connect(self.auto_select_clicked.emit)
            row = QHBoxLayout(); row.setSpacing(4)
            row.addWidget(self._auto_btn); row.addStretch()
            self._script_btn_area.addLayout(row)
            self._script_rows.append(row)

    # --- 框选排除面板方法 ---

    def show_range_ex_panel(self) -> None:
        """框选+排除步骤：自动识别按钮 → 「排除首行」「排除首列」→ 确定。"""
        self._clear_script_btns()
        # 1. 自动识别按钮
        self._auto_btn = QPushButton('🔍 自动识别整个表格')
        self._auto_btn.clicked.connect(self.auto_select_clicked.emit)
        row = QHBoxLayout(); row.setSpacing(4)
        row.addWidget(self._auto_btn); row.addStretch()
        self._script_btn_area.addLayout(row)
        self._script_rows.append(row)
        # 2. 排除首行 / 排除首列按钮
        self._exclude_row_btn = QPushButton('排除首行')
        self._exclude_row_btn.clicked.connect(self.exclude_row_clicked.emit)
        self._exclude_col_btn = QPushButton('排除首列')
        self._exclude_col_btn.clicked.connect(self.exclude_col_clicked.emit)
        erow = QHBoxLayout(); erow.setSpacing(4)
        erow.addWidget(self._exclude_row_btn)
        erow.addWidget(self._exclude_col_btn)
        erow.addStretch()
        self._script_btn_area.addLayout(erow)
        self._script_rows.append(erow)
        # 3. 确定按钮（默认禁用，需有选区）
        self.show_confirm_button(enabled=False)

    def set_confirm_enabled(self, enabled):
        """仅切换确定按钮可用状态，不重排布局（拖拽框选时避免频繁重绘）。"""
        if self._confirm_btn is not None:
            self._confirm_btn.setEnabled(enabled)

    # --- 小数补齐面板方法 ---

    def show_pad_area_panel(self) -> None:
        """补齐第一步：区域选择（自动识别/点选行/点选列/自行框选 互斥竖排）+ 确定。"""
        self._clear_script_btns()
        # 1. 4 个互斥模式按钮（竖排，各一行，文字完整显示）
        self._pad_mode_group = _OptionGroup('pad_mode',
                                            ['自动识别整个表格', '点选行', '点选列', '自行框选'],
                                            layout_mode='v')
        self._pad_mode_group.value_changed.connect(
            lambda _k, v: self.pad_mode_changed.emit(v))
        row = QHBoxLayout(); row.setSpacing(4)
        row.addWidget(self._pad_mode_group); row.addStretch()
        self._script_btn_area.addLayout(row)
        self._script_rows.append(row)
        self._script_widgets.extend(self._pad_mode_group._btns)
        # 2. 确定按钮（默认禁用，区域就绪后由控制器点亮）
        self.show_confirm_button(enabled=False)

    def get_pad_mode(self) -> str:
        return self._pad_mode_group.current_value if self._pad_mode_group else ''

    # --- 补齐位数面板方法 ---

    def show_pad_decimals_panel(self) -> None:
        """补齐第二步：位数选择（默认/自定义 选择+输入框）+ 确定。"""
        self._clear_script_btns()
        # 1. 位数选择框：复用 QuantileSlot 交互（菜单+输入），
        #    菜单文字改为「默认/自定义位数」，信号映射 median→default、manual→custom
        self._pad_decimals_slot = QuantileSlot(self)
        menu = self._pad_decimals_slot._menu_btn.menu()
        menu.clear()
        for text, action in [('默认', 'default'), ('自定义位数', 'custom')]:
            act = menu.addAction(text)
            act.triggered.connect(
                lambda checked=False, a=action: self._pad_decimals_slot._emit(a))
        self._pad_decimals_slot._text_btn.setText('默认')
        self._pad_decimals_slot.mode_changed.connect(self.pad_decimals_mode_changed.emit)
        self._pad_decimals_slot.value_submitted.connect(self.pad_decimals_value_submitted.emit)
        self._pad_decimals_slot.cancelled.connect(self._on_pad_decimals_cancel)
        label = QLabel('补齐位数:')
        row = QHBoxLayout(); row.setSpacing(4)
        row.addWidget(label)
        row.addWidget(self._pad_decimals_slot, 1)
        self._script_btn_area.addLayout(row)
        self._script_rows.append(row)
        self._pad_decimals_value = 'default'  # 默认
        # 2. 确定按钮：默认模式已生效 → 初始即亮
        self.show_confirm_button(enabled=True)

    def _on_pad_decimals_cancel(self) -> None:
        self._editor_close()
        self.pad_decimals_cancelled.emit()

    def show_pad_decimals_editor(self) -> None:
        if self._pad_decimals_slot is not None:
            self._pad_decimals_slot.show_editor()
            self._editor_open()

    def set_pad_decimals_display(self, text: str) -> None:
        if self._pad_decimals_slot is not None:
            was_editing = self._pad_decimals_slot.is_editing
            self._pad_decimals_slot.set_display(text)
            if was_editing:
                self._editor_close()

    def reset_pad_decimals(self) -> None:
        if self._pad_decimals_slot is not None:
            was_editing = self._pad_decimals_slot.is_editing
            self._pad_decimals_slot.set_display('默认')
            if was_editing:
                self._editor_close()

    def get_pad_decimals_value(self) -> str:
        """返回已确认的位数设置：'default' 或 数字字符串。"""
        return getattr(self, '_pad_decimals_value', 'default')

    def set_pad_decimals_value(self, value: str) -> None:
        self._pad_decimals_value = value

    def pad_decimals_ready(self) -> bool:
        slot = getattr(self, '_pad_decimals_slot', None)
        return (slot is not None and not slot.is_editing
                and bool(getattr(self, '_pad_decimals_value', 'default')))

    # --- 计算元输入方法 ---

    def show_operand_slots(self, count: int, pick_kind: str = 'column',
                           with_decimals: bool = False, operator: str = '',
                           fixed_count: int = 0, slot_labels=None,
                           text_mode: bool = False) -> None:
        """显示 N 个计算元框 + 可选「＋ 添加计算元」按钮。

        pick_kind: 运算方向的点选类型（'column'=点选列 / 'row'=点选行）。
        with_decimals: True 时在添加按钮之后显示「保留小数位数」选择行。
        operator: 非空时在第一个计算元与其余之间显示该符号行
                  （如 '-' 提示第一个为被减数）。
        fixed_count: >0 时槽位数量固定，不显示添加/删除按钮。
        slot_labels: 与槽位平行的标签列表，代替「选择计算元」作为初始文字。
        text_mode: True 时槽位菜单用文本专用项（手动输入文本/剪贴板单/多文本）。
        """
        self._clear_script_btns()
        self._pick_kind = pick_kind
        self._operand_text_mode = text_mode
        self._operand_slots = []
        self._operand_rows = []
        show_delete = (fixed_count == 0)
        for i in range(count):
            label = slot_labels[i] if slot_labels and i < len(slot_labels) else '选择计算元'
            self._add_operand_slot(show_delete=show_delete, initial_text=label,
                                   text_mode=text_mode)
            if i == 0 and operator:
                self._show_operator_row(operator)
        if fixed_count == 0:
            self._add_operand_btn = QPushButton('＋ 添加计算元')
            self._add_operand_btn.clicked.connect(self._on_add_operand)
            row = QHBoxLayout(); row.setSpacing(4)
            row.addWidget(self._add_operand_btn); row.addStretch()
            self._insert_script_row(row)
            self._script_rows.append(row)
            self._add_operand_btn_row = row
        if with_decimals:
            self._show_decimals_slot()

    def _show_operator_row(self, symbol: str) -> None:
        """在第一个计算元行之后显示运算符号行（只显示一次）。

        符号水平居中（两侧 stretch）；加粗并放大字号，保证醒目可见
        （颜色保持默认，不额外涂色）。
        """
        label = QLabel(symbol)
        f = label.font()
        f.setPointSize(11)
        f.setBold(True)
        label.setFont(f)
        row = QHBoxLayout(); row.setSpacing(4)
        row.addStretch()
        row.addWidget(label)
        row.addStretch()
        self._insert_script_row(row)
        self._script_rows.append(row)
        self._operator_row = row

    # --- 三角函数面板 ---

    def show_trig_function_panel(self, functions: list[str], pick_kind: str = 'column',
                                 units=None, with_decimals: bool = True) -> None:
        """显示三角函数步骤面板：函数下拉 → 单计算元 → 单位 → 保留小数 → 确定。

        functions: 下拉函数选项列表（9 个三角/反三角）。
        pick_kind: 运算方向的点选类型（'column'=点选列 / 'row'=点选行）。
        units: 角度单位选项，如 ['弧度', '度']，默认第一个。
        with_decimals: True 时显示「保留小数位数」选择行。
        """
        self._clear_script_btns()
        units = units or ['弧度', '度']
        self._pick_kind = pick_kind

        # 1. 函数下拉行（在最上，下拉框按内容自适应宽度，不撑满整行）
        self._func_combo = QComboBox()
        self._func_combo.addItems(functions)
        self._func_combo.currentTextChanged.connect(self.function_changed.emit)
        func_row = QHBoxLayout(); func_row.setSpacing(4)
        func_label = QLabel('函数:')
        func_row.addWidget(func_label)
        func_row.addWidget(self._func_combo)
        func_row.addStretch()
        self._script_btn_area.addLayout(func_row)
        self._script_rows.append(func_row)
        self._func_row = func_row

        # 2. 单个计算元槽位（固定，无删除按钮）
        self._operand_slots = []
        self._operand_rows = []
        self._add_operand_slot(show_delete=False, initial_text='输入计算元')

        # 3. 角度单位互斥按钮行（无标签；写法与「选行列」按钮组 show_script_buttons 完全一致，
        #    不默认选中，完全复用 _OptionGroup 原生行为）
        self._func_group = _OptionGroup('unit', units)
        self._func_group.value_changed.connect(
            lambda _k, v: self.unit_changed.emit(v))
        unit_row = QHBoxLayout(); unit_row.setSpacing(4)
        unit_row.addWidget(self._func_group); unit_row.addStretch()
        self._script_btn_area.addLayout(unit_row)
        self._script_rows.append(unit_row)
        self._unit_row = unit_row

        # 4. 保留小数位数
        if with_decimals:
            self._show_decimals_slot()

        # 自动执行一次"选择弧度制"：延迟到按钮显示稳定后再选中，
        # 避免初始 setChecked 干扰布局尺寸计算导致的挤压/截字问题
        QTimer.singleShot(0, self._default_select_unit)

    def _default_select_unit(self) -> None:
        """延迟回调：默认选中第一个单位（弧度制），并触发单位变化信号。"""
        if self._func_group is not None and self._func_group._btns:
            units = self._func_group._btns
            units[0].setChecked(True)
            for b in units[1:]:
                b.setChecked(False)
            self.unit_changed.emit(units[0].text())

    def set_function(self, text: str) -> None:
        """外部设置函数下拉框当前值（如控制器初始化）。"""
        if self._func_combo is not None:
            idx = self._func_combo.findText(text)
            if idx >= 0:
                self._func_combo.setCurrentIndex(idx)

    def get_function(self) -> str:
        return self._func_combo.currentText() if self._func_combo is not None else ''

    def get_unit(self) -> str:
        return self._func_group.current_value if self._func_group is not None else ''

    def add_operand_slot(self) -> None:
        """追加一个计算元框（用户点「＋ 添加计算元」）。"""
        self._add_operand_slot(text_mode=self._operand_text_mode)

    def _add_operand_slot(self, show_delete: bool = True,
                          initial_text: str = '选择计算元',
                          text_mode: bool | None = None) -> int:
        if text_mode is None:
            text_mode = self._operand_text_mode  # 未显式指定时沿用面板当前模式
        idx = len(self._operand_slots)
        slot = OperandSlot(idx, self._pick_kind, show_delete, initial_text,
                           text_mode, self)
        slot.action_requested.connect(self.operand_action.emit)
        slot.constant_submitted.connect(self.operand_constant_submitted.emit)
        slot.constant_cancelled.connect(self._on_slot_constant_cancelled)
        slot.remove_requested.connect(self._remove_operand_slot)
        row = QHBoxLayout(); row.setSpacing(4)
        row.addWidget(slot)
        # 新槽位插到「＋ 添加计算元」按钮行之前（按钮始终在所有计算元下方）
        self._insert_script_row(row, anchor=self._add_operand_btn_row)
        self._script_rows.append(row)
        self._operand_slots.append(slot)
        self._operand_rows.append(row)
        return idx

    def _insert_script_row(self, row: QHBoxLayout, anchor=None) -> None:
        """把一行布局插入到 anchor 行之前；anchor 为空时用默认锚点
        （「保留小数位数」行 → 确定按钮），都没有则追加到末尾。"""
        if anchor is not None:
            idx = self._script_btn_area.indexOf(anchor)
            if idx >= 0:
                self._script_btn_area.insertLayout(idx, row)
                return
        anchor2 = self._decimals_row if self._decimals_row is not None else self._confirm_row
        if anchor2 is not None:
            idx = self._script_btn_area.indexOf(anchor2)
            if idx >= 0:
                self._script_btn_area.insertLayout(idx, row)
                return
        self._script_btn_area.addLayout(row)

    # --- 保留小数位数输入 ---

    def _show_decimals_slot(self) -> None:
        """显示「保留小数位数」选择行（添加按钮之后、确定按钮之前）。"""
        self._decimals_slot = DecimalsSlot(self)
        self._decimals_slot.mode_changed.connect(self.decimals_mode_changed.emit)
        self._decimals_slot.digits_submitted.connect(self.decimals_digits_submitted.emit)
        self._decimals_slot.cancelled.connect(self._on_decimals_cancelled)
        row = QHBoxLayout(); row.setSpacing(4)
        row.addWidget(self._decimals_slot)
        self._insert_script_row(row)
        self._script_rows.append(row)
        self._decimals_row = row

    def _on_decimals_cancelled(self) -> None:
        """用户 Esc 取消手动输入：关闭编辑态并转发给控制器。"""
        self._editor_close()
        self.decimals_cancelled.emit()

    def show_decimals_editor(self) -> None:
        """进入手动输入态（编辑态期间 Enter 快捷键让给输入框）。"""
        if self._decimals_slot is not None:
            self._decimals_slot.show_editor()
            self._editor_open()

    def set_decimals_display(self, text: str) -> None:
        """手动位数提交成功后设置显示文本（退出编辑态）。"""
        if self._decimals_slot is not None:
            was_editing = self._decimals_slot.is_editing
            self._decimals_slot.set_display(text)
            if was_editing:
                self._editor_close()

    def _remove_operand_slot(self, index: int) -> None:
        """删除某个计算元框，剩余框索引重排。"""
        if not (0 <= index < len(self._operand_slots)):
            return
        if self._operand_slots[index].is_editing:
            self._editor_close()
        slot = self._operand_slots.pop(index)
        row = self._operand_rows.pop(index)
        if row in self._script_rows:
            self._script_rows.remove(row)
        while row.count():
            item = row.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._script_btn_area.removeItem(row)
        for i, s in enumerate(self._operand_slots):
            s.set_index(i)
        self.operand_removed.emit(index)

    def _on_slot_constant_cancelled(self, index: int) -> None:
        """用户 Esc 取消常数输入：转发给控制器并关闭编辑态。"""
        self._editor_close()
        self.operand_constant_cancelled.emit(index)

    def _on_add_operand(self) -> None:
        self._add_operand_slot(text_mode=self._operand_text_mode)
        self.operand_added.emit()

    def set_slot_display(self, index: int, text: str) -> None:
        """设置某个计算元框的显示文本（退出常数输入态）。"""
        if 0 <= index < len(self._operand_slots):
            slot = self._operand_slots[index]
            was_editing = slot.is_editing
            slot.set_display(text)
            if was_editing:
                self._editor_close()

    def show_slot_editor(self, index: int) -> None:
        """让某个计算元框进入常数输入态。

        输入态期间禁用 Enter 确认快捷键，把回车让给输入框提交常数。
        """
        if 0 <= index < len(self._operand_slots):
            self._operand_slots[index].show_editor()
            self._editor_open()

    def reset_slot(self, index: int) -> None:
        """清空某个计算元框为初始状态。"""
        if 0 <= index < len(self._operand_slots):
            slot = self._operand_slots[index]
            was_editing = slot.is_editing
            slot.reset()
            if was_editing:
                self._editor_close()

    def _editor_open(self) -> None:
        self._editor_open_count += 1
        if self._editor_open_count == 1:
            self._set_enter_shortcuts(False)

    def _editor_close(self) -> None:
        if self._editor_open_count > 0:
            self._editor_open_count -= 1
            if self._editor_open_count == 0:
                self._set_enter_shortcuts(True)

    def _set_enter_shortcuts(self, enabled: bool) -> None:
        for sc in self._confirm_shortcuts:
            sc.setEnabled(enabled)

    @property
    def operand_slot_count(self) -> int:
        return len(self._operand_slots)

    # --- 输出位置按钮 ---

    def show_output_buttons(self) -> None:
        """显示「输出到剪贴板」「点选输出列/行」两个按钮（点击即动作）。"""
        self._clear_script_btns()
        self._clip_btn = QPushButton('📋 输出到剪贴板')
        self._clip_btn.clicked.connect(self.output_clipboard.emit)
        self._pick_btn = QPushButton('🎯 点选输出列/行')
        self._pick_btn.clicked.connect(self.output_pick.emit)
        for b in (self._clip_btn, self._pick_btn):
            row = QHBoxLayout(); row.setSpacing(4)
            row.addWidget(b); row.addStretch()
            self._script_btn_area.addLayout(row)
            self._script_rows.append(row)

    def _setup_shortcuts(self):
        """Enter / 数字键盘 Enter 作为「确定」快捷键（仅脚本交互期间启用）。"""
        for key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            sc = QShortcut(QKeySequence(key), self)
            sc.setEnabled(False)
            sc.activated.connect(self._confirm_by_key)
            self._confirm_shortcuts.append(sc)

    def _confirm_by_key(self):
        """Enter 确认；但焦点在输入框（如常数输入）时，Enter 交给输入框提交。"""
        focus = QApplication.focusWidget()
        if isinstance(focus, QLineEdit):
            return
        if self._confirm_btn is not None and self._confirm_btn.isEnabled():
            self._confirm_btn.click()

    def get_option(self, key):
        g = self._opt_groups.get(key)
        return g.current_value if g else None

    def all_options_selected(self):
        return all(g.current_value is not None for g in self._opt_groups.values())

    def clear_script_panel(self):
        self._clear_script_btns()
        self._script_prompt.setText('未运行脚本')

    def _clear_script_btns(self):
        for row in getattr(self, '_script_rows', []):
            while row.count():
                item = row.takeAt(0)
                if item.widget(): item.widget().deleteLater()
                if item.layout(): self._clear_layout(item.layout())
            self._script_btn_area.removeItem(row)
        self._script_rows = []
        self._opt_groups = {}
        self._confirm_btn = None
        self._confirm_row = None
        self._auto_btn = None
        self._open_editor_btn = None
        self._check_errors_btn = None
        self._script_widgets = []
        self._operand_slots = []
        self._operand_rows = []
        self._pick_kind = 'column'
        self._operand_text_mode = False
        self._editor_open_count = 0
        self._add_operand_btn = None
        self._add_operand_btn_row = None
        self._decimals_slot = None
        self._decimals_row = None
        self._operator_row = None
        self._clip_btn = None
        self._pick_btn = None
        self._exclude_row_btn = None
        self._exclude_col_btn = None
        self._pad_mode_group = None
        self._pad_decimals_slot = None
        self._pad_decimals_value = 'default'
        self._func_combo = None
        self._func_group = None
        self._func_row = None
        self._unit_row = None
        self._dir_group = None
        self._quantile_slot = None
        self._quantile_row = None
        self._quantile_value = ''
        self._mode_slot = None
        self._mode_row = None
        self._mode_value = ''
        self._op_combo = None
        self._op_btn = None
        self._const_edit = None
        self._const_edit_row = None
        self._count_operator = ''
        self._count_constant = None
        self._inspect_type_slot = None
        self._fail_slot = None
        self._pass_slot = None
        self._inspect_type = ''
        self._inspect_value = None
        self._fail_result = '0'
        self._pass_result = '1'
        for sc in self._confirm_shortcuts:
            sc.setEnabled(False)

    @staticmethod
    def _clear_layout(layout):
        while layout.count():
            item = layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()
            if item.layout(): SidePanel._clear_layout(item.layout())

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 8, 6, 6)
        layout.setSpacing(6)

        # -- 标题行 --
        header_row = QHBoxLayout()
        title = QLabel('资源浏览')
        title.setStyleSheet('font-weight: bold; font-size: 13px;')
        header_row.addWidget(title)
        header_row.addStretch()
        layout.addLayout(header_row)

        # -- 切换按钮 --
        btn_row = QHBoxLayout()
        btn_row.setSpacing(2)
        self._btn_files = QPushButton('表格库')
        self._btn_scripts = QPushButton('脚本库')
        for b in (self._btn_files, self._btn_scripts):
            b.setCheckable(True)
            b.setFlat(True)
        self._btn_files.clicked.connect(lambda: self._switch_mode(self.MODE_FILES))
        self._btn_scripts.clicked.connect(lambda: self._switch_mode(self.MODE_SCRIPTS))
        self._btn_files.setStyleSheet(self._btn_style(True))
        self._btn_scripts.setStyleSheet(self._btn_style(False))
        btn_row.addWidget(self._btn_files)
        btn_row.addWidget(self._btn_scripts)
        layout.addLayout(btn_row)

        # ══════════════════════════════════════════════════════════════
        # 映射文件夹 子版块
        # ══════════════════════════════════════════════════════════════

        panel = QFrame()
        panel.setFrameStyle(QFrame.Shape.StyledPanel)
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(6, 6, 6, 6)
        panel_layout.setSpacing(4)

        # -- 路径栏 + 图标按钮 --
        top_row = QHBoxLayout()
        top_row.setSpacing(4)

        self._path_edit = QLineEdit()
        self._path_edit.setReadOnly(True)
        self._path_edit.setStyleSheet('padding: 2px 4px;')
        top_row.addWidget(self._path_edit, 1)

        # 浏览按钮
        browse_btn = QToolButton()
        browse_btn.setText('📂')
        browse_btn.setToolTip('浏览文件夹')
        browse_btn.setAutoRaise(True)
        browse_btn.clicked.connect(self._browse_folder)
        top_row.addWidget(browse_btn)

        # 刷新按钮
        refresh_btn = QToolButton()
        refresh_btn.setText('🔄')
        refresh_btn.setToolTip('刷新')
        refresh_btn.setAutoRaise(True)
        refresh_btn.clicked.connect(self.refresh_current)
        top_row.addWidget(refresh_btn)

        panel_layout.addLayout(top_row)

        # -- 文件树 --
        self._file_view = self._create_tree()
        self._file_view.clicked.connect(
            lambda i: self._on_click(i, self._file_source, self._file_proxy))
        self._file_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._file_view.customContextMenuRequested.connect(
            self._on_file_context_menu)
        self._script_view = self._create_tree()
        self._script_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._script_view.customContextMenuRequested.connect(self._on_script_context_menu)
        self._script_view.hide()

        panel_layout.addWidget(self._file_view, 1)
        panel_layout.addWidget(self._script_view, 1)

        layout.addWidget(panel)  # 面板只占内容高度，不撑满

        # -- 脚本操作面板 --
        self._script_panel = QFrame()
        self._script_panel.setFrameStyle(QFrame.Shape.StyledPanel)
        sp = QVBoxLayout(self._script_panel)
        sp.setContentsMargins(6, 4, 6, 4)
        sp.setSpacing(4)
        self._script_prompt = QLabel('未运行脚本')
        self._script_prompt.setStyleSheet('border: none;')
        self._script_prompt.setWordWrap(True)   # 长提示换行显示（不再截断）
        sp.addWidget(self._script_prompt)
        self._script_btn_area = QVBoxLayout()
        self._script_btn_area.setSpacing(4)
        sp.addLayout(self._script_btn_area)
        self._script_panel.setVisible(False)
        layout.addWidget(self._script_panel)

        layout.addStretch(1)  # 底部留白

    @staticmethod
    def _create_tree() -> QTreeView:
        t = QTreeView()
        t.setHeaderHidden(True)
        t.setAnimated(True)
        t.setIndentation(16)
        t.setEditTriggers(QTreeView.EditTrigger.NoEditTriggers)
        t.setExpandsOnDoubleClick(True)
        return t

    # ------------------------------------------------------------------
    # 模型
    # ------------------------------------------------------------------

    def _setup_models(self) -> None:
        self._file_source = QFileSystemModel(self)
        self._file_source.setFilter(QDir.Filter.AllEntries | QDir.Filter.NoDotAndDotDot)
        self._file_source.setNameFilters([])
        self._file_proxy = FileFilterProxy(self)
        self._file_proxy.setSourceModel(self._file_source)
        self._file_proxy.set_extensions(self.SPREADSHEET_FILTERS)
        self._file_proxy.set_user_order(self._tree_order.get(self.MODE_FILES, {}))
        self._file_proxy.setDynamicSortFilter(True)
        self._file_proxy.sort(0, Qt.SortOrder.AscendingOrder)
        self._file_view.setModel(self._file_proxy)
        self._conf_cols(self._file_view)

        self._script_source = QFileSystemModel(self)
        self._script_source.setFilter(QDir.Filter.AllEntries | QDir.Filter.NoDotAndDotDot)
        self._script_source.setNameFilters([])
        self._script_proxy = FileFilterProxy(self)
        self._script_proxy.setSourceModel(self._script_source)
        self._script_proxy.set_extensions(self.SCRIPT_FILTERS)
        self._script_proxy.set_user_order(self._tree_order.get(self.MODE_SCRIPTS, {}))
        self._script_proxy.setDynamicSortFilter(True)
        self._script_proxy.sort(0, Qt.SortOrder.AscendingOrder)
        self._script_view.setModel(self._script_proxy)
        self._conf_cols(self._script_view)

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _switch_mode(self, mode):
        self._current_mode = mode
        is_f = mode == self.MODE_FILES
        self._btn_files.setChecked(is_f)
        self._btn_scripts.setChecked(not is_f)
        self._btn_files.setStyleSheet(self._btn_style(is_f))
        self._btn_scripts.setStyleSheet(self._btn_style(not is_f))
        self._file_view.setVisible(is_f)
        self._script_view.setVisible(not is_f)
        self._path_edit.setText(self._file_folder if is_f else self._script_folder)
        self._script_panel.setVisible(not is_f)
        self.mode_changed.emit(mode)

    def show_script_mode(self) -> None:
        """切换到「脚本库」模式，显示脚本操作面板（供补齐等面板流程使用）。"""
        if self._current_mode != self.MODE_SCRIPTS:
            self._switch_mode(self.MODE_SCRIPTS)

    def _browse_folder(self):
        start = self._file_folder if self._current_mode == self.MODE_FILES else self._script_folder
        # DontUseNativeDialog：绕开 Windows 原生文件对话框的 COM 崩溃
        # （0x8001010e RPC_E_WRONG_THREAD，error.log 大量转储）；保留 ShowDirsOnly。
        d = QFileDialog.getExistingDirectory(
            self, '选择文件夹', start,
            QFileDialog.Option.ShowDirsOnly
            | QFileDialog.Option.DontUseNativeDialog)
        if d:
            if self._current_mode == self.MODE_FILES:
                self.file_folder = d
            else:
                self.script_folder = d
            # 用户主动改库路径 → 显式持久化（setter 不再隐式写盘）
            self._settings.file_folder = self._file_folder
            self._settings.script_folder = self._script_folder
            self._settings.save()

    def _on_click(self, pi, src, proxy):
        si = proxy.mapToSource(pi)
        if src.isDir(si):
            return
        self.file_clicked.emit(src.filePath(si))

    def _on_script_context_menu(self, pos):
        i = self._script_view.indexAt(pos)
        if not i.isValid(): return
        si = self._script_proxy.mapToSource(i)
        m = QMenu(self)
        run_action = None
        if not self._script_source.isDir(si):
            run_action = m.addAction('▶ 运行')
            m.addSeparator()
        self._add_order_actions(m, self._script_view, self._script_source,
                                self._script_proxy, self.MODE_SCRIPTS, si)
        chosen = m.exec(self._script_view.viewport().mapToGlobal(pos))
        order_info = getattr(m, '_chosen', None)
        if chosen is run_action:
            self.script_run_requested.emit(self._script_source.filePath(si))
        elif order_info:
            self._apply_order(*order_info)

    def _on_file_context_menu(self, pos):
        i = self._file_view.indexAt(pos)
        if not i.isValid(): return
        si = self._file_proxy.mapToSource(i)
        m = QMenu(self)
        self._add_order_actions(m, self._file_view, self._file_source,
                                self._file_proxy, self.MODE_FILES, si)
        chosen = m.exec(self._file_view.viewport().mapToGlobal(pos))
        order_info = getattr(m, '_chosen', None)
        if order_info:
            self._apply_order(*order_info)

    @staticmethod
    def _add_order_actions(menu: QMenu, tree, src, proxy, mode, source_idx):
        """追加 上移/下移/置顶/置底/恢复默认 排序菜单项。

        选中项为目录或文件均可；排序作用于选中项所在**父目录**的子项顺序。
        操作返回 (mode, dir_path, name, action) 元组。
        """
        name = src.fileName(source_idx)
        parent_idx = source_idx.parent()
        dir_path = src.filePath(parent_idx) if parent_idx.isValid() else ''
        for label, act in (('↑ 上移', 'up'), ('↓ 下移', 'down'),
                           ('置顶', 'top'), ('置底', 'bottom')):
            menu.addAction(label).triggered.connect(
                lambda _=False, a=act, n=name:
                setattr(menu, '_chosen', (mode, dir_path, n, a)))
        menu.addSeparator()
        r = menu.addAction('恢复默认排序')
        r.triggered.connect(
            lambda: setattr(menu, '_chosen',
                            (mode, dir_path, name, 'reset')))

    def _apply_order(self, mode, dir_path, name, action):
        """按操作调整某目录内子项的自定义顺序并持久化。"""
        src = self._file_source if mode == self.MODE_FILES \
            else self._script_source
        # 规范化路径（QFileSystemModel.filePath 用正斜杠）
        dir_path = src.filePath(src.index(dir_path))
        if action == 'reset':
            self._tree_order.setdefault(mode, {}).pop(dir_path, None)
        else:
            names = self._displayed_names(mode, dir_path)
            if name not in names:
                return
            idx = names.index(name)
            names.remove(name)
            if action == 'top':
                names.insert(0, name)
            elif action == 'bottom':
                names.append(name)
            elif action == 'up':
                names.insert(max(idx - 1, 0), name)
            elif action == 'down':
                names.insert(min(idx + 1, len(names)), name)
            self._tree_order.setdefault(mode, {})[dir_path] = names
        self._settings.set('file_tree_order', self._tree_order)
        self._settings.save()
        # 刷新对应 proxy
        if mode == self.MODE_FILES:
            self._file_proxy.set_user_order(
                self._tree_order.get(mode, {}))
        else:
            self._script_proxy.set_user_order(
                self._tree_order.get(mode, {}))

    def _displayed_names(self, mode, dir_path) -> list[str]:
        """当前显示顺序下某目录的直接子项名列表（proxy 视角）。"""
        if mode == self.MODE_FILES:
            src, proxy = self._file_source, self._file_proxy
        else:
            src, proxy = self._script_source, self._script_proxy
        src_idx = src.index(dir_path)
        proxy_parent = proxy.mapFromSource(src_idx)
        names = []
        for row in range(proxy.rowCount(proxy_parent)):
            pi = proxy.index(row, 0, proxy_parent)
            si = proxy.mapToSource(pi)
            names.append(src.fileName(si))
        return names

    @staticmethod
    def _set_tree_root(src, proxy, tree, path):
        tree.setRootIndex(proxy.mapFromSource(src.setRootPath(path)))

    @staticmethod
    def _conf_cols(tree):
        h = tree.header()
        h.setStretchLastSection(False)
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for i in range(1, h.count()):
            h.hideSection(i)

    @staticmethod
    def _btn_style(on):
        if on:
            return ('QPushButton { background: #333; color: #fff; padding: 4px 12px;'
                    ' border: 2px solid #222; border-radius: 3px; font-weight: bold; }')
        return ('QPushButton { background: transparent; color: #555; padding: 4px 12px;'
                ' border: 2px solid transparent; border-radius: 3px; }'
                'QPushButton:hover { background: #eee; }')
