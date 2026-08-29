"""文件操作控制器 — 新建/打开/保存/导出，含脏检查。

V1.1 起支持多 sheet 工作簿（xlsx）：一个文件对应多个 SpreadsheetModel，
以列表 _sheets 维护，_current_index 指向当前激活 sheet。
"""
from pathlib import Path

from PyQt6.QtWidgets import QFileDialog, QMessageBox, QInputDialog
from file_io.file_handler import FileHandler
from file_io import xlsx_handler
from config.settings import AppSettings
from models.spreadsheet_model import SpreadsheetModel


class FileIOController:
    """编排所有文件操作。"""

    def __init__(self, settings: AppSettings):
        self._settings = settings
        self._sheets: list[tuple[str, SpreadsheetModel]] = []  # (sheet名, model)
        self._current_index = 0
        self._current_model = None
        self._get_file_folder = lambda: ''  # 外部设置，返回表格库文件夹路径
        self._formula_provider = None       # 互译 P2：公式提供器（main_window 注入）

    def set_model(self, model):
        """初始化单 sheet 工作簿（保持旧 API：主窗口传入初始模型）。"""
        self._current_model = model
        self._sheets = [('Sheet1', model)]
        self._current_index = 0

    def set_file_folder_provider(self, provider):
        """provider 是一个返回表格库文件夹路径的可调用对象。"""
        self._get_file_folder = provider

    def set_sheets(self, sheets: list[tuple[str, SpreadsheetModel]],
                   activate: int = 0) -> None:
        """设置整个工作簿的 sheet 列表，激活指定索引（默认第一个）。"""
        self._sheets = list(sheets)
        self._current_index = 0 if not sheets else max(0, min(activate, len(sheets) - 1))
        self._current_model = self._sheets[self._current_index][1] if sheets else None

    def set_current_sheet(self, index: int) -> None:
        """切换当前激活的 sheet（越界忽略）。"""
        if 0 <= index < len(self._sheets):
            self._current_index = index
            self._current_model = self._sheets[index][1]

    # ------------------------------------------------------------------
    # 工作簿编辑（新增/重命名/删除 sheet，V1.1）
    # ------------------------------------------------------------------

    def add_sheet(self, name: str = '') -> int:
        """新增空 sheet 并激活，返回其索引。

        名称为空时自动生成（Sheet1/Sheet2/…避开重名）；
        名称含非法字符时按 xlsx 规则清理。
        """
        from file_io.xlsx_handler import _unique_sheet_name
        used = {n for n, _ in self._sheets}
        if not name.strip():
            n = 1
            while f'Sheet{n}' in used:
                n += 1
            name = f'Sheet{n}'
        title = _unique_sheet_name(name, used)
        model = SpreadsheetModel()
        if self._current_model:
            model.file_path = self._current_model.file_path
            model.file_format = self._current_model.file_format
        self._sheets.append((title, model))
        self._current_index = len(self._sheets) - 1
        self._current_model = model
        return self._current_index

    def rename_sheet(self, index: int, name: str) -> bool:
        """重命名 sheet（自动清理非法字符/重名）。越界或空名返回 False。"""
        if not (0 <= index < len(self._sheets)):
            return False
        if not name.strip():
            return False
        from file_io.xlsx_handler import _unique_sheet_name
        used = {n for i, (n, _) in enumerate(self._sheets) if i != index}
        title = _unique_sheet_name(name, used)
        self._sheets[index] = (title, self._sheets[index][1])
        return True

    def remove_sheet(self, index: int) -> bool:
        """删除 sheet（至少保留一个）。返回是否删除成功。"""
        if not (0 <= index < len(self._sheets)):
            return False
        if len(self._sheets) <= 1:
            return False
        self._sheets.pop(index)
        if self._current_index > index:
            self._current_index -= 1
        self._current_index = min(self._current_index, len(self._sheets) - 1)
        self._current_model = self._sheets[self._current_index][1]
        return True

    # ------------------------------------------------------------------
    # 工作簿查询
    # ------------------------------------------------------------------

    @property
    def sheet_names(self) -> list[str]:
        return [name for name, _ in self._sheets]

    @property
    def sheet_models(self) -> list[SpreadsheetModel]:
        return [m for _, m in self._sheets]

    @property
    def sheet_count(self) -> int:
        return len(self._sheets)

    @property
    def current_sheet_index(self) -> int:
        return self._current_index

    @property
    def current_sheet_name(self) -> str:
        return self._sheets[self._current_index][0] if self._sheets else ''

    @property
    def current_model(self) -> SpreadsheetModel | None:
        """当前激活 sheet 的模型。"""
        return self._current_model

    @property
    def any_dirty(self) -> bool:
        """任一 sheet 有未保存修改。"""
        return any(m.is_dirty for _, m in self._sheets)

    @property
    def _default_dir(self) -> str:
        """保存时的默认目录：优先表格库，其次设置中的路径。"""
        folder = self._get_file_folder() if callable(self._get_file_folder) else ''
        return folder or self._settings.file_folder

    # ------------------------------------------------------------------
    # 新建
    # ------------------------------------------------------------------

    def new_file(self, fmt: str = '') -> bool:
        """新建空表格。如果当前有未保存内容，先提示。

        fmt: 'csv'/'xlsx'/'txt' 指定新文件格式（影响默认扩展名与
        标签条显隐）；空字符串 = 无格式（旧行为）。
        """
        if not self._maybe_save():
            return False
        self._current_model.clear()
        self._current_model.file_format = fmt
        self._sheets = [('Sheet1', self._current_model)]
        self._current_index = 0
        return True

    # ------------------------------------------------------------------
    # 打开
    # ------------------------------------------------------------------

    def open_file_dialog(self) -> bool:
        """弹出文件选择对话框并打开文件。"""
        if not self._maybe_save():
            return False
        path, _ = QFileDialog.getOpenFileName(
            None,
            '打开文件',
            self._default_dir,
            '支持的文件 (*.csv *.xlsx *.xls *.txt *.tsv);;所有文件 (*)',
            options=QFileDialog.Option.DontUseNativeDialog
        )
        if not path:
            return False
        return self.open_file(path)

    def open_file(self, path: str) -> bool:
        """直接打开指定路径的文件。

        xlsx/xls：每个 sheet 一个 SpreadsheetModel，组成工作簿；
        其他格式：单 sheet 工作簿。打开后主窗口应调用 sheet_models
        重新绑定视图与控制器。
        """
        try:
            sheets = FileHandler.load_sheets(path)
            fmt = FileHandler.detect_format(path)
            models: list[tuple[str, SpreadsheetModel]] = []
            for name, raw_data in sheets:
                model = SpreadsheetModel()
                model.load_2d(raw_data)
                model.file_path = path
                model.file_format = fmt
                model.mark_clean()
                models.append((name, model))
            if not models:
                models = [('Sheet1', SpreadsheetModel())]
            self._sheets = models
            self._current_index = 0
            self._current_model = models[0][1]
            self._settings.add_recent_file(path)
            self._settings.save()
            return True
        except Exception as e:
            QMessageBox.critical(None, '打开失败', f'无法打开文件:\n{e}')
            return False

    # ------------------------------------------------------------------
    # 保存
    # ------------------------------------------------------------------

    def save_file(self) -> bool:
        """保存当前文件。无路径时弹出简易命名框，直接存到表格库。

        xlsx 整本写回（所有 sheet）；csv/txt 只写当前激活 sheet。
        """
        if not self._current_model.file_path:
            return self._quick_save_to_library()
        try:
            self._save_to_path(self._current_model.file_path)
            self._settings.add_recent_file(self._current_model.file_path)
            self._settings.save()
            return True
        except Exception as e:
            QMessageBox.critical(None, '保存失败', f'无法保存文件:\n{e}')
            return False

    def _save_to_path(self, path: str) -> None:
        """按目标路径的格式写文件，并清理全部 sheet 的脏标记。"""
        fmt = FileHandler.detect_format(path)
        if fmt == 'xlsx':
            # 互译 P2：公式写回（动态脚本翻译/外来公式保留 <f>）
            formulas = self._formula_provider() \
                if self._formula_provider is not None else None
            FileHandler.save_sheets(path, self._collect_sheets(), formulas)
            for _, m in self._sheets:
                m.mark_clean()
        else:
            FileHandler.save(self._current_model)

    def set_formula_provider(self, provider) -> None:
        """注入公式提供器（main_window 提供动态条目的公式收集）。"""
        self._formula_provider = provider

    def _collect_sheets(self) -> list[tuple[str, list[list[str]]]]:
        """收集全部 sheet 的 (名称, 二维数据)。"""
        return [(name, m.to_2d()) for name, m in self._sheets]

    def _quick_save_to_library(self) -> bool:
        """无路径文件：弹出输入框输入文件名，检测同名文件后保存到表格库。"""
        default_dir = self._default_dir
        name, ok = QInputDialog.getText(
            None, '保存到表格库', '输入文件名（不带扩展名则默认补当前格式扩展名）：'
        )
        if not ok or not name.strip():
            return False
        name = name.strip()
        # 自动补扩展名（按当前新建格式；无格式默认 .csv）
        if not Path(name).suffix:
            ext_map = {'csv': '.csv', 'xlsx': '.xlsx', 'txt': '.txt'}
            fmt = self._current_model.file_format
            name += ext_map.get(fmt, '.csv')
        # 检测表格库及其子文件夹内同名文件（含扩展名匹配）
        matches = self._find_duplicates(default_dir, name)
        if matches:
            choice, choice_path = self._show_duplicate_dialog(matches)
            if choice == 'cancel':
                return False
            if choice == 'update' and choice_path:
                # 覆盖选中的同名文件
                return self._do_save_as(choice_path)
            # 'save_as' → 打开另存为对话框
            return self.save_as_file()
        path = str(Path(default_dir) / name) if default_dir else name
        return self._do_save_as(path)

    def _find_duplicates(self, base_dir: str, filename: str) -> list[str]:
        """递归搜索 base_dir 及其子文件夹内的同名文件（含扩展名匹配）。"""
        if not base_dir or not Path(base_dir).is_dir():
            return []
        return [str(p) for p in Path(base_dir).rglob(filename)]

    def _show_duplicate_dialog(self, matches: list[str]) -> tuple[str, str | None]:
        """同名文件弹窗：列表（路径+日期）+ 更新/另存/取消。返回 (选择, 选中路径)。"""
        from PyQt6.QtWidgets import (
            QListWidget, QDialog, QDialogButtonBox, QVBoxLayout, QLabel)
        dlg = QDialog()
        dlg.setWindowTitle('发现同名文件')
        lay = QVBoxLayout(dlg)
        lay.addWidget(QLabel('表格库中存在同名文件，选择操作：'))
        lst = QListWidget(dlg)
        for p in sorted(matches):
            mtime = Path(p).stat().st_mtime
            from datetime import datetime
            date = datetime.fromtimestamp(mtime).strftime('%Y-%m-%d %H:%M')
            lst.addItem(f'{p}    [{date}]')
        if matches:
            lst.setCurrentRow(0)
        lay.addWidget(lst)
        btns = QDialogButtonBox()
        update_btn = btns.addButton('更新', QDialogButtonBox.ButtonRole.AcceptRole)
        save_as_btn = btns.addButton('另存', QDialogButtonBox.ButtonRole.ActionRole)
        cancel_btn = btns.addButton('取消', QDialogButtonBox.ButtonRole.RejectRole)
        lay.addWidget(btns)
        btns.rejected.connect(dlg.reject)
        update_btn.clicked.connect(dlg.accept)
        save_as_btn.clicked.connect(lambda: dlg.done(2))
        dlg.exec()
        # 判定选择
        sel = lst.currentItem().text().split('    [')[0] if lst.currentItem() else ''
        if dlg.result() == 1:
            return 'update', sel
        elif dlg.result() == 2:
            return 'save_as', sel
        return 'cancel', None

    def save_as_file(self) -> bool:
        """另存为对话框 — 默认打开表格库文件夹。"""
        default_dir = self._default_dir
        path, _ = QFileDialog.getSaveFileName(
            None,
            '另存为',
            default_dir,
            'CSV 文件 (*.csv);;Excel 文件 (*.xlsx);;文本文件 (*.txt)',
            options=QFileDialog.Option.DontUseNativeDialog
        )
        if not path:
            return False
        return self._do_save_as(path)

    def _do_save_as(self, path: str) -> bool:
        """执行实际写入。"""
        try:
            fmt = FileHandler.detect_format(path)
            if not fmt:
                if path.endswith('.csv'):
                    fmt = 'csv'
                elif path.endswith('.xlsx'):
                    fmt = 'xlsx'
                elif path.endswith('.txt'):
                    fmt = 'txt'
                else:
                    QMessageBox.warning(None, '不支持', '文件扩展名不支持，请使用 .csv/.xlsx/.txt')
                    return False

            if fmt == 'xlsx':
                FileHandler.save_sheets(path, self._collect_sheets())
                for _, m in self._sheets:
                    m.mark_clean()
            else:
                FileHandler.export_as(self._current_model, path, fmt)
                self._current_model.mark_clean()
            for _, m in self._sheets:
                m.file_path = path
                m.file_format = fmt
            self._settings.add_recent_file(path)
            self._settings.save()
            return True
        except Exception as e:
            QMessageBox.critical(None, '保存失败', f'无法保存文件:\n{e}')
            return False

    # ------------------------------------------------------------------
    # 导出
    # ------------------------------------------------------------------

    def export_file(self, fmt: str) -> bool:
        """导出为指定格式。xlsx 整本导出；csv/txt 只导出当前激活 sheet。"""
        ext_map = {'csv': '.csv', 'xlsx': '.xlsx', 'txt': '.txt'}
        ext = ext_map.get(fmt, '')
        path, _ = QFileDialog.getSaveFileName(
            None,
            f'导出为 {fmt.upper()}',
            self._default_dir,
            f'{fmt.upper()} 文件 (*{ext})',
            options=QFileDialog.Option.DontUseNativeDialog
        )
        if not path:
            return False
        try:
            if fmt == 'xlsx':
                FileHandler.save_sheets(path, self._collect_sheets())
            else:
                FileHandler.export_as(self._current_model, path, fmt)
            return True
        except Exception as e:
            QMessageBox.critical(None, '导出失败', f'无法导出文件:\n{e}')
            return False

    # ------------------------------------------------------------------
    # 单表保存 / 单表导出为（右键 sheet 标签，V1.1）
    # ------------------------------------------------------------------

    def save_sheet_only(self, index: int) -> bool:
        """单表保存：只把指定 sheet 的内存数据写回文件对应位置。

        其他 sheet 以磁盘原样保留（即使内存有未保存修改也不覆盖）；
        仅该 sheet 清除脏标记。
        """
        if not (0 <= index < len(self._sheets)):
            return False
        if not self._current_model.file_path:
            QMessageBox.warning(None, '无法单表保存', '文件尚未保存过，请先用「保存」命名保存。')
            return False
        path = self._current_model.file_path
        try:
            fmt = FileHandler.detect_format(path)
            if fmt == 'xlsx':
                # 读磁盘全部 sheet，替换目标索引的数据后整本写回
                on_disk = xlsx_handler.load_all(path)
                name, model = self._sheets[index]
                if index < len(on_disk):
                    on_disk[index] = (name, model.to_2d())
                else:
                    on_disk.append((name, model.to_2d()))
                FileHandler.save_sheets(path, on_disk)
            else:
                # 单表文件（csv/txt）：直接写当前 sheet
                FileHandler.save(self._sheets[index][1])
            self._sheets[index][1].mark_clean()
            return True
        except Exception as e:
            QMessageBox.critical(None, '单表保存失败', f'无法保存:\n{e}')
            return False

    def export_sheet_only_dialog(self, index: int, fmt: str) -> bool:
        """单表导出为：弹对话框选路径，只导出指定 sheet。"""
        if not (0 <= index < len(self._sheets)):
            return False
        ext_map = {'csv': '.csv', 'xlsx': '.xlsx', 'txt': '.txt'}
        ext = ext_map.get(fmt, '')
        name = self._sheets[index][0]
        default_name = f'{Path(name).stem}{ext}' if name else f'sheet{ext}'
        path, _ = QFileDialog.getSaveFileName(
            None,
            f'单表导出为 {fmt.upper()}',
            str(Path(self._default_dir) / default_name) if self._default_dir
            else default_name,
            f'{fmt.upper()} 文件 (*{ext})',
            options=QFileDialog.Option.DontUseNativeDialog
        )
        if not path:
            return False
        try:
            _, model = self._sheets[index]
            data = model.to_2d()
            if fmt == 'xlsx':
                xlsx_handler.write_all(path, [(name or 'Sheet1', data)])
            else:
                FileHandler.export_as(model, path, fmt)
            return True
        except Exception as e:
            QMessageBox.critical(None, '单表导出失败', f'无法导出文件:\n{e}')
            return False

    def import_sheet_dialog(self, index: int) -> bool:
        """单表导入：从表格库选择 csv/txt 文件，覆盖指定 sheet 的内容。

        交互：文件对话框（默认打开表格库目录）；仅接受 csv/txt/tsv，
        选择 xlsx 等其它格式报错并拒绝；覆盖后该 sheet 标记为脏
        （sheet 名保留）。
        """
        if not (0 <= index < len(self._sheets)):
            return False
        path, _ = QFileDialog.getOpenFileName(
            None,
            '单表导入',
            self._default_dir,
            'CSV / TXT 文件 (*.csv *.txt *.tsv);;所有文件 (*)',
            options=QFileDialog.Option.DontUseNativeDialog
        )
        if not path:
            return False
        ext = Path(path).suffix.lower()
        if ext not in ('.csv', '.txt', '.tsv'):
            QMessageBox.warning(None, '单表导入失败',
                                f'不支持 {ext} 格式：单表导入仅接受 CSV / TXT 文件。')
            return False
        try:
            sheets = FileHandler.load_sheets(path)
            if not sheets:
                QMessageBox.warning(None, '单表导入失败', '文件无数据。')
                return False
            _, data = sheets[0]
            _, model = self._sheets[index]
            model.load_2d(data)
            model.mark_dirty()   # 导入 = 内容变化，标记脏
            self._settings.add_recent_file(path)
            self._settings.save()
            return True
        except Exception as e:
            QMessageBox.critical(None, '单表导入失败', f'无法导入:\n{e}')
            return False

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _maybe_save(self) -> bool:
        """检查脏状态（任一 sheet），提示用户保存。返回 True 表示可以继续。"""
        if not self._current_model or not self.any_dirty:
            return True
        msg = QMessageBox()
        msg.setWindowTitle('未保存的修改')
        msg.setText('当前文件有未保存的修改，是否保存后再继续？')
        msg.setIcon(QMessageBox.Icon.Question)
        save_btn = msg.addButton('保存', QMessageBox.ButtonRole.AcceptRole)
        discard_btn = msg.addButton('不保存', QMessageBox.ButtonRole.DestructiveRole)
        cancel_btn = msg.addButton('取消', QMessageBox.ButtonRole.RejectRole)
        msg.setEscapeButton(cancel_btn)
        msg.exec()
        clicked = msg.clickedButton()
        if clicked == save_btn:
            return self.save_file()
        elif clicked == discard_btn:
            return True
        else:
            return False
