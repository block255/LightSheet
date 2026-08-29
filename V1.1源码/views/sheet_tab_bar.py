"""sheet 标签条 — QTabBar 子类，带右键菜单（重命名/删除）。

结构：sheet 标签（可切换/右键）+ 末尾「＋」加号标签（点击新增 sheet）。
- 加号标签与 sheet 标签并列，样式一致（同一 QSS 规则）；
- 点击加号 → 发 add_requested 信号，不改变当前选中；
- 加号标签不可被选中（currentChanged 保护）、右键菜单忽略它；
- 样式策略（2026-08-27 修正）：
  - 表头格子（QHeaderView）原生用 palette 的 Button 角色绘制（灰），
    外围窗口用 Window 角色（黑）——两者类别本就不同；
  - QTabBar 原生标签用 Window 角色绘制（与外围同类别），所以默认
    标签底色与外围分不开；
  - 本类监听 QApplication.paletteChanged（系统深浅色切换时一定触发），
    用当前 palette 动态生成样式表——标签底色 = Button 角色（与表头
    一致），选中 = Light 角色，行背景 = Window 角色。
  - 不用 QSS 的 palette(...) 关键字（静态求值，不跟随切换）；
    不用控件的 PaletteChange 事件（带样式表的控件收不到）。
"""
from PyQt6.QtWidgets import QTabBar, QMenu, QApplication
from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtGui import QPalette, QMouseEvent


class SheetTabBar(QTabBar):
    """工作表标签条：sheet 标签 + 末尾「＋」新增标签。

    左键点击 sheet 标签 = 切换（QTabBar 默认行为）；
    左键点击「＋」= 发 add_requested（不切换选中）；
    右键点击 sheet 标签 = 菜单（重命名 / 删除）；
    右键点击「＋」= 忽略。
    """

    rename_requested = pyqtSignal(int)   # sheet 标签索引
    delete_requested = pyqtSignal(int)   # sheet 标签索引
    add_requested = pyqtSignal()         # 点「＋」
    save_sheet_requested = pyqtSignal(int)          # 单表保存（仅该 sheet）
    export_sheet_requested = pyqtSignal(int, str)   # 单表导出为 (index, fmt)
    import_sheet_requested = pyqtSignal(int)        # 单表导入（覆盖该 sheet）

    PLUS_TEXT = '＋'

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDocumentMode(True)
        self.setExpanding(False)
        self.setUsesScrollButtons(True)
        self._plus_index = -1            # 「＋」标签索引（-1 = 未设置）
        self.currentChanged.connect(self._on_current_changed)
        self._apply_theme()
        # 系统主题切换（深浅色）→ 重新取色生成样式表
        app = QApplication.instance()
        if app is not None:
            app.paletteChanged.connect(self._apply_theme)

    # ------------------------------------------------------------------
    # 标签重建：sheet 名列表 + 末尾「＋」
    # ------------------------------------------------------------------

    def set_sheets(self, names: list[str], current: int = 0) -> None:
        """重建标签：每个 sheet 一个标签，末尾追加「＋」标签。

        重建期间屏蔽信号（不触发 currentChanged / 加号保护）。
        """
        self.blockSignals(True)
        while self.count() > 0:
            self.removeTab(0)
        for name in names:
            self.addTab(name)
        self._plus_index = self.addTab(self.PLUS_TEXT)
        if names:
            self.setCurrentIndex(max(0, min(current, len(names) - 1)))
        self.blockSignals(False)

    @property
    def sheet_count(self) -> int:
        """sheet 标签数量（不含「＋」）。"""
        return self.count() - 1 if self._plus_index >= 0 else self.count()

    @property
    def plus_index(self) -> int:
        return self._plus_index

    # ------------------------------------------------------------------
    # 加号标签：点击 → add_requested；禁止成为选中标签
    # ------------------------------------------------------------------

    def mousePressEvent(self, event: QMouseEvent):
        """左键点击「＋」→ 发信号且不切换选中；其余交给 QTabBar。"""
        if (event.button() == Qt.MouseButton.LeftButton and
                self._plus_index >= 0 and
                self.tabAt(event.pos()) == self._plus_index):
            self.add_requested.emit()
            return
        super().mousePressEvent(event)

    def _on_current_changed(self, index: int) -> None:
        """防止「＋」被选中（键盘方向键可能移到它）。"""
        if index == self._plus_index and self.sheet_count > 0:
            self.blockSignals(True)
            self.setCurrentIndex(self.sheet_count - 1)
            self.blockSignals(False)

    # ------------------------------------------------------------------
    # 主题跟随：应用 palette 变化 → 用当前角色颜色动态生成样式表
    # ------------------------------------------------------------------

    def _apply_theme(self, *args) -> None:
        """从当前 palette 取色生成标签样式（标签=Button 角色=表头同色）。"""
        if getattr(self, '_applying_theme', False):
            return
        self._applying_theme = True
        try:
            pal = QApplication.instance().palette()
            btn = pal.color(QPalette.ColorRole.Button).name()
            light = pal.color(QPalette.ColorRole.Light).name()
            mid = pal.color(QPalette.ColorRole.Mid).name()
            window = pal.color(QPalette.ColorRole.Window).name()
            midlight = pal.color(QPalette.ColorRole.Midlight).name()
            self.setStyleSheet(f'''
QTabBar {{
    background: {window};
}}
QTabBar::tab {{
    background: {btn};
    border: 1px solid {mid};
    border-bottom: none;
    border-top-left-radius: 4px;
    border-top-right-radius: 4px;
    padding: 3px 12px;
    margin-top: 4px;
    margin-right: 2px;
}}
QTabBar::tab:selected {{
    background: {light};
    border-color: {mid};
}}
QTabBar::tab:hover:!selected {{
    background: {midlight};
}}
''')
        finally:
            self._applying_theme = False

    # ------------------------------------------------------------------
    # 右键菜单
    # ------------------------------------------------------------------

    def contextMenuEvent(self, event):
        """右键 sheet 标签：弹菜单；「＋」或空白处不弹。

        多 sheet 工作簿额外提供「单表保存」「单表导出为」。
        """
        idx = self.tabAt(event.pos())
        if idx < 0 or idx == self._plus_index:
            return
        menu = QMenu(self)
        rename_act = menu.addAction('重命名')
        delete_act = menu.addAction('删除')
        # 多 sheet 时提供单表操作（单表文件下「保存」即全量，无需重复项）
        if self.sheet_count > 1:
            menu.addSeparator()
            save_act = menu.addAction('单表保存')
            save_act.triggered.connect(
                lambda: self.save_sheet_requested.emit(idx))
            import_act = menu.addAction('单表导入')
            import_act.triggered.connect(
                lambda: self.import_sheet_requested.emit(idx))
            export_menu = menu.addMenu('单表导出为')
            for label, fmt in (('CSV 文件 (.csv)', 'csv'),
                               ('Excel 文件 (.xlsx)', 'xlsx'),
                               ('文本文件 (.txt)', 'txt')):
                act = export_menu.addAction(label)
                act.triggered.connect(
                    lambda _=False, f=fmt: self.export_sheet_requested.emit(idx, f))
        chosen = menu.exec(event.globalPos())
        if chosen is rename_act:
            self.rename_requested.emit(idx)
        elif chosen is delete_act:
            self.delete_requested.emit(idx)
