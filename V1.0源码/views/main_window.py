"""主窗口 — 总装所有组件并完成信号/槽连线。"""
from pathlib import Path

from PyQt6.QtWidgets import QMainWindow, QSplitter, QMessageBox
from PyQt6.QtCore import Qt, QByteArray

from config.settings import AppSettings
from models.spreadsheet_model import SpreadsheetModel
from views.spreadsheet_grid import SpreadsheetGrid
from views.side_panel import SidePanel
from views.menu_bar import create_menu_bar
from views.toolbar import create_toolbar
from views.status_bar import StatusBar
from controllers.spreadsheet_controller import SpreadsheetController
from controllers.file_io_controller import FileIOController
from controllers.script_controller import ScriptController
from controllers.decimal_pad_controller import DecimalPadController


class MainWindow(QMainWindow):
    """应用主窗口。"""

    def __init__(self, settings: AppSettings):
        super().__init__()
        self._settings = settings

        # -- 核心模块 --
        self._model = SpreadsheetModel(self)
        self._file_io = FileIOController(settings)
        self._file_io.set_model(self._model)
        self._file_io.set_file_folder_provider(lambda: self._side_panel.file_folder)

        # -- 界面 --
        self._setup_window()
        self._setup_menu()
        self._setup_toolbar()
        self._setup_central()
        self._setup_statusbar()
        self._setup_controller()

        # -- 连线 --
        self._wire_signals()

        # -- 恢复状态 --
        self._restore_state()

    # ==================================================================
    # 界面搭建
    # ==================================================================

    def _setup_window(self) -> None:
        self.setWindowTitle('LightSheet — 轻量表格')
        self.resize(1200, 700)
        self.setMinimumSize(800, 500)

    def _setup_menu(self) -> None:
        self._menu_bar, self._menu_actions = create_menu_bar(self)
        self.setMenuBar(self._menu_bar)

    def _setup_toolbar(self) -> None:
        self._toolbar, self._toolbar_actions = create_toolbar(self)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, self._toolbar)

    def _setup_central(self) -> None:
        self._splitter = QSplitter(Qt.Orientation.Horizontal, self)

        # 左侧面板
        self._side_panel = SidePanel(self)
        # 复用主窗口的 settings 实例（否则 SidePanel 内部新建实例写入后，
        # 退出时主窗口实例用旧内存覆盖 → 自定义文件顺序等配置丢失）
        self._side_panel._settings = self._settings
        self._side_panel.setMinimumWidth(180)
        self._side_panel.setMaximumWidth(400)
        self._splitter.addWidget(self._side_panel)

        # 中间表格
        self._grid = SpreadsheetGrid(self)
        self._grid.setModel(self._model)
        self._splitter.addWidget(self._grid)

        # 比例：侧栏 220px 给默认，剩下的给表格
        self._splitter.setSizes([220, 980])
        self._splitter.setStretchFactor(0, 0)
        self._splitter.setStretchFactor(1, 1)

        self.setCentralWidget(self._splitter)

    def _setup_statusbar(self) -> None:
        self._status_bar = StatusBar(self)
        self.setStatusBar(self._status_bar)

    def _setup_controller(self) -> None:
        self._sheet_ctrl = SpreadsheetController(self._model, self._grid)
        self._script_ctrl = ScriptController(
            self._model, self._grid, self._status_bar, self._side_panel)
        self._pad_ctrl = DecimalPadController(
            self._model, self._grid, self._side_panel,
            push_snapshot=self._sheet_ctrl._push_snapshot)

    # ==================================================================
    # 信号/槽连线
    # ==================================================================

    def _wire_signals(self) -> None:
        # --- 文件操作 ---
        self._menu_actions['new'].triggered.connect(self._on_new)
        self._menu_actions['open'].triggered.connect(self._on_open)
        self._menu_actions['save'].triggered.connect(self._on_save)
        self._menu_actions['save_as'].triggered.connect(self._on_save_as)
        self._menu_actions['export_csv'].triggered.connect(lambda: self._on_export('csv'))
        self._menu_actions['export_xlsx'].triggered.connect(lambda: self._on_export('xlsx'))
        self._menu_actions['export_txt'].triggered.connect(lambda: self._on_export('txt'))
        self._menu_actions['exit'].triggered.connect(self.close)

        self._toolbar_actions['new'].triggered.connect(self._on_new)
        self._toolbar_actions['open'].triggered.connect(self._on_open)
        self._toolbar_actions['save'].triggered.connect(self._on_save)

        # --- 编辑操作 ---
        self._menu_actions['undo'].triggered.connect(self._sheet_ctrl.undo)
        self._menu_actions['cut'].triggered.connect(self._sheet_ctrl.cut)
        self._menu_actions['copy'].triggered.connect(self._sheet_ctrl.copy)
        self._menu_actions['paste'].triggered.connect(self._sheet_ctrl.paste)
        self._menu_actions['delete'].triggered.connect(self._sheet_ctrl.delete_selection)
        self._menu_actions['insert_row'].triggered.connect(
            lambda: self._sheet_ctrl.insert_row())
        self._menu_actions['insert_col'].triggered.connect(
            lambda: self._sheet_ctrl.insert_column())
        self._menu_actions['remove_row'].triggered.connect(
            lambda: self._sheet_ctrl.remove_row())
        self._menu_actions['remove_col'].triggered.connect(
            lambda: self._sheet_ctrl.remove_column())

        self._toolbar_actions['cut'].triggered.connect(self._sheet_ctrl.cut)
        self._toolbar_actions['copy'].triggered.connect(self._sheet_ctrl.copy)
        self._toolbar_actions['paste'].triggered.connect(
            lambda: self._sheet_ctrl.paste())
        self._toolbar_actions['insert_row'].triggered.connect(
            lambda: self._sheet_ctrl.insert_row())
        self._toolbar_actions['insert_col'].triggered.connect(
            lambda: self._sheet_ctrl.insert_column())
        self._toolbar_actions['deselect'].triggered.connect(self._on_deselect)
        self._toolbar_actions['pad_decimals'].triggered.connect(self._on_pad_decimals)

        # --- 右键菜单行列操作 ---
        self._grid.row_inserted.connect(self._sheet_ctrl.insert_row)
        self._grid.col_inserted.connect(self._sheet_ctrl.insert_column)
        self._grid.row_removed.connect(self._sheet_ctrl.remove_row)
        self._grid.col_removed.connect(self._sheet_ctrl.remove_column)

        # --- WASD 平移选区 ---
        self._grid.move_requested.connect(self._sheet_ctrl.move_selection)

        # --- 侧栏 ---
        self._side_panel.file_clicked.connect(self._on_side_file_clicked)
        self._side_panel.script_run_requested.connect(self._on_script_run)
        self._side_panel.mode_changed.connect(self._on_panel_mode_changed)

        # --- 状态更新 ---
        self._grid.selectionModel().selectionChanged.connect(self._on_selection_changed)
        self._model.dataChanged.connect(self._on_data_changed)
        self._model.dirty_changed.connect(self._on_dirty_changed)

        # --- 视图菜单 ---
        self._menu_actions['toggle_edit_mode'].triggered.connect(self._on_toggle_edit_mode)
        self._menu_actions['refresh_panel'].triggered.connect(self._side_panel.refresh_current)
        self._grid.edit_mode_changed.connect(self._on_edit_mode_changed)

        # --- 关于 ---
        self._menu_actions['about'].triggered.connect(self._on_about)
        self._menu_actions['tutorial'].triggered.connect(self._on_tutorial)

    # ==================================================================
    # 槽函数
    # ==================================================================

    def _on_new(self) -> None:
        if self._file_io.new_file():
            self._update_status_all()

    def _on_open(self) -> None:
        if self._file_io.open_file_dialog():
            self._update_status_all()

    def _on_save(self) -> None:
        self._file_io.save_file()
        self._update_status_all()

    def _on_save_as(self) -> None:
        self._file_io.save_as_file()
        self._update_status_all()

    def _on_export(self, fmt: str) -> None:
        self._file_io.export_file(fmt)

    def _on_deselect(self) -> None:
        """取消所有选中格子。"""
        self._grid.clearSelection()
        self._grid.setCurrentIndex(self._model.index(-1, -1))

    def _on_pad_decimals(self) -> None:
        """小数补齐：中断运行中的脚本，转而启动补齐流程。"""
        self._script_ctrl.abort()
        self._pad_ctrl.start()

    def _on_side_file_clicked(self, path: str) -> None:
        """单击侧栏文件 → 打开。"""
        if self._file_io.open_file(path):
            self._update_status_all()

    def _on_script_run(self, path: str) -> None:
        """侧栏右键"运行"脚本：先中断补齐流程，再运行脚本。"""
        self._pad_ctrl.abort()
        self._script_ctrl.run_script(path)

    def _on_panel_mode_changed(self, mode: str) -> None:
        """切换到表格库 → 取消正在交互的脚本/补齐流程。"""
        if mode == 'files':
            self._script_ctrl.abort()
            self._pad_ctrl.abort()

    def _on_selection_changed(self) -> None:
        idx = self._grid.currentIndex()
        if idx.isValid():
            self._status_bar.set_cell_position(idx.row(), idx.column())
        else:
            self._status_bar.set_cell_position(0, 0)

    def _on_data_changed(self) -> None:
        pass  # dirty_changed 已处理状态栏

    def _on_dirty_changed(self, dirty: bool) -> None:
        name = None
        if self._model.file_path:
            name = Path(self._model.file_path).name
        self._status_bar.set_file_info(name, dirty)

    def _on_toggle_edit_mode(self, checked: bool) -> None:
        self._grid.set_edit_mode(checked)

    def _on_edit_mode_changed(self, enabled: bool) -> None:
        self._menu_actions['toggle_edit_mode'].setChecked(enabled)
        self._status_bar.set_edit_mode(enabled)

    def _on_about(self) -> None:
        QMessageBox.about(
            self, '关于 LightSheet',
            'LightSheet — 轻量表格\n\n'
            '一个简洁干净的本地表格软件。\n'
            'Python + PyQt6 构建。'
        )

    def _on_tutorial(self) -> None:
        """帮助 → 教程：教程目录界面（左侧章节列表 + 右侧内容）。"""
        from PyQt6.QtWidgets import (QDialog, QHBoxLayout, QListWidget,
                                     QTextBrowser, QListWidgetItem)
        dialog = QDialog(self)
        dialog.setWindowTitle('LightSheet 使用教程')
        dialog.resize(780, 600)
        lo = QHBoxLayout(dialog)
        # 左侧目录
        list_w = QListWidget(dialog)
        list_w.setFixedWidth(190)
        lo.addWidget(list_w)
        # 右侧内容
        browser = QTextBrowser(dialog)
        browser.setOpenExternalLinks(True)
        lo.addWidget(browser, 1)

        for title, _ in _TUTORIAL_SECTIONS:
            QListWidgetItem(title, list_w)

        def _show(row: int) -> None:
            if 0 <= row < len(_TUTORIAL_SECTIONS):
                browser.setPlainText(_TUTORIAL_SECTIONS[row][1])

        list_w.currentRowChanged.connect(_show)
        list_w.setCurrentRow(0)
        dialog.exec()

    # ==================================================================
    # 状态恢复与保存
    # ==================================================================

    def _update_status_all(self) -> None:
        """刷新状态栏全部信息。"""
        self._status_bar.set_dimensions(self._model.row_total, self._model.col_total)
        name = None
        if self._model.file_path:
            name = Path(self._model.file_path).name
        self._status_bar.set_file_info(name, self._model.is_dirty)
        self._status_bar.set_format(self._model.file_format)

        # 同步侧栏文件夹到设置
        if self._side_panel.file_folder:
            self._settings.file_folder = self._side_panel.file_folder
        if self._side_panel.script_folder:
            self._settings.script_folder = self._side_panel.script_folder

        # 更新窗口标题
        base = 'LightSheet'
        if self._model.file_path:
            dirty = ' *' if self._model.is_dirty else ''
            self.setWindowTitle(f'{Path(self._model.file_path).name}{dirty} — {base}')
        else:
            self.setWindowTitle(f'{base} — 轻量表格')

    def _restore_state(self) -> None:
        """启动时恢复上次的状态。"""
        # 恢复窗口几何
        geo = self._settings.window_geometry
        if geo:
            self.restoreGeometry(QByteArray.fromBase64(geo.encode()))
        state = self._settings.window_state
        if state:
            self.restoreState(QByteArray.fromBase64(state.encode()))
        splitter_state = self._settings.splitter_state
        if splitter_state:
            self._splitter.restoreState(QByteArray.fromBase64(splitter_state.encode()))

        # 恢复侧栏文件夹
        file_folder = self._settings.file_folder
        if file_folder:
            self._side_panel.file_folder = file_folder
        script_folder = self._settings.script_folder
        if script_folder:
            self._side_panel.script_folder = script_folder

        self._update_status_all()

    # ==================================================================
    # 关闭事件
    # ==================================================================

    def closeEvent(self, event):
        """关闭前保存状态，检查未保存的修改。"""
        if self._model.is_dirty:
            msg = QMessageBox()
            msg.setWindowTitle('未保存的修改')
            msg.setText('当前文件有未保存的修改，是否保存？')
            msg.setIcon(QMessageBox.Icon.Question)
            save_btn = msg.addButton('保存', QMessageBox.ButtonRole.AcceptRole)
            discard_btn = msg.addButton('不保存', QMessageBox.ButtonRole.DestructiveRole)
            cancel_btn = msg.addButton('取消', QMessageBox.ButtonRole.RejectRole)
            msg.setEscapeButton(cancel_btn)
            msg.exec()
            clicked = msg.clickedButton()
            if clicked == save_btn:
                if not self._file_io.save_file():
                    event.ignore()
                    return
            elif clicked == cancel_btn:
                event.ignore()
                return

        # 保存状态到配置
        self._settings.window_geometry = self.saveGeometry().toBase64().data().decode()
        self._settings.window_state = self.saveState().toBase64().data().decode()
        self._settings.splitter_state = self._splitter.saveState().toBase64().data().decode()
        self._settings.file_folder = self._side_panel.file_folder
        self._settings.script_folder = self._side_panel.script_folder
        self._settings.save()

        event.accept()


# ======================================================================
# 帮助 → 教程：目录与章节内容
# ======================================================================

_TUTORIAL_SECTIONS = [
    ('1. 基本操作', """【新建表格】  文件 → 新建（Ctrl+N）
【打开文件】  文件 → 打开（Ctrl+O），支持 CSV / Excel / 文本
【保存】      Ctrl+S；另存为 Ctrl+Shift+S
【导出】      文件 → 导出为（CSV / Excel / 文本）
【退出】      文件 → 退出（Alt+F4）

菜单栏快捷键：Alt+F 文件、Alt+E 编辑、Alt+V 视图、Alt+H 帮助。"""),

    ('2. 表格编辑', """【鼠标操作】
   单击 = 选中单元格；按住左键拖动 = 框选（矩形多格选区）
   编辑模式下单击已选中的格 = 进入编辑
   单元格内右键 = 中文菜单（撤销/剪切/复制/粘贴/删除/全选）
   点列头 = 选中整列，点行头 = 选中整行（Shift 可扩展多选）
【整体平移】  多格选中时按方向键 ↑ ↓ ← → → 整个选区整体平移
   （不会收缩成单格；编辑模式下按方向键则在选中区内移动光标）
【工具栏】
   📄新建  📂打开  💾保存
   ✂️剪切  📋复制  📌粘贴
   ⬇️插入行  ➡️插入列
   🔟小数补齐  🚫取消选中
【小数补齐】🔟 按钮（表格界面功能，非脚本）：
   选择区域（自动识别 / 点选行 / 点选列 / 自行框选）
   → 选位数（默认自动或自定义 0-10）→ 执行
   仅对区域内纯数据格补齐，含字符的格跳过
【编辑模式】  视图 → 编辑模式（Ctrl+E）切换 可编辑/只读
【插入/删除行列】 编辑菜单或工具栏
【撤销】      Ctrl+Z（编辑菜单）
【其他】      状态栏右侧显示编辑模式、行列坐标、文件名、格式、维度"""),

    ('3. 左侧文件栏', """【表格库 / 脚本库】 顶部按钮切换浏览内容
【打开文件】   点击文件树中的文件即可打开
【自定义显示顺序】 右键文件或文件夹 → 上移 / 下移 / 置顶 / 置底
   顺序会保存，重启后保持；右键 → 恢复默认排序 可还原
【脚本库】     右键脚本 → 「▶ 运行」

积木配置文件（.json）不会显示在文件栏中，只能在自定义运算编辑器里打开。"""),

    ('4. 脚本系统', """脚本按类型分三类（对应脚本库子文件夹）：
【排序脚本】（排序脚本/）
   数值排序、日期排序：框选区域 + 参考列/行
【统计脚本】（统计脚本/）
   平均值：框选区域 → 选方向（对行/对列处理）→ 输出（结果垂直输出）
【运算脚本】（运算脚本/）
   加法 / 乘法 / 减法 / 除法 / 指数 / 对数 / 三角
   流程：选方向（以行/列为单位）→ 收集计算元（点选列/行、常数、剪贴板）
   → 可选保留小数位数 → 选择输出位置
   ★ 自定义运算脚本 也在运算脚本/ 中——可视化积木编程，
     详见本教程第 5 章。"""),

    ('5. 自定义运算（积木编辑器）', """可视化积木编程定义运算，仅针对纯数据。

【流程】运行「自定义运算脚本」→ 选运算方向（以行/列为单位）
   → 侧栏出现 打开编辑器 / 检查报错 / 确定

【积木】6 类：计算元（数元/指数/对数/三角）、符号元（运算+逻辑）、
   括号（数学优先级）、计数、检定、输出。

【数元输入】行/列、手动常数、剪贴板（一维/二维）、接入积木、
   整个表格（计数积木专用）、范围输入（计数积木：起始/结尾，
   逐行/列计数 → 对齐一维表）。

【计数/检定】逻辑符号比较；检定接受一维表 → 输出 0/1 对齐表。

【输出积木】剪贴板 / 输出到行 / 输出到列（结果方向须与输出方向一致）。

【检查报错】列出结构+数据级全部错误；有错时侧栏「确定」按钮不亮。

【积木配置】空选时「保存当前积木配置」「打开积木配置」可存/读方案
   （JSON，保存到脚本库/自定义运算积木配置/）。

【编辑技巧】撤销 Ctrl+Z / 重做 Ctrl+Y；右键复制/删除（自身或整体）；
   窗口可最大化。"""),

    ('6. 快捷键一览', """文件：新建 Ctrl+N、打开 Ctrl+O、保存 Ctrl+S、另存为 Ctrl+Shift+S、退出 Alt+F4
编辑：撤销 Ctrl+Z、剪切 Ctrl+X、复制 Ctrl+C、粘贴 Ctrl+V、删除 Delete
     插入行 Ctrl+Shift++、插入列 Ctrl+Shift+Ins、删除行 Ctrl+-、删除列 Ctrl+Shift+-
视图：编辑模式 Ctrl+E、刷新左侧面板 F5
菜单栏：Alt+F 文件、Alt+E 编辑、Alt+V 视图、Alt+H 帮助"""),
]
