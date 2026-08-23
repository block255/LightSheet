"""文件操作控制器 — 新建/打开/保存/导出，含脏检查。"""
from pathlib import Path

from PyQt6.QtWidgets import QFileDialog, QMessageBox, QInputDialog
from file_io.file_handler import FileHandler
from config.settings import AppSettings


class FileIOController:
    """编排所有文件操作。"""

    def __init__(self, settings: AppSettings):
        self._settings = settings
        self._current_model = None
        self._get_file_folder = lambda: ''  # 外部设置，返回表格库文件夹路径

    def set_model(self, model):
        self._current_model = model

    def set_file_folder_provider(self, provider):
        """provider 是一个返回表格库文件夹路径的可调用对象。"""
        self._get_file_folder = provider

    @property
    def _default_dir(self) -> str:
        """保存时的默认目录：优先表格库，其次设置中的路径。"""
        folder = self._get_file_folder() if callable(self._get_file_folder) else ''
        return folder or self._settings.file_folder

    # ------------------------------------------------------------------
    # 新建
    # ------------------------------------------------------------------

    def new_file(self) -> bool:
        """新建空表格。如果当前有未保存内容，先提示。"""
        if not self._maybe_save():
            return False
        self._current_model.clear()
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
            '支持的文件 (*.csv *.xlsx *.xls *.txt *.tsv);;所有文件 (*)'
        )
        if not path:
            return False
        return self.open_file(path)

    def open_file(self, path: str) -> bool:
        """直接打开指定路径的文件。"""
        try:
            model = FileHandler.load(path)
            # 替换当前模型数据
            self._current_model.load_2d(model.to_2d())
            self._current_model.file_path = path
            self._current_model.file_format = FileHandler.detect_format(path)
            self._current_model.mark_clean()
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
        """保存当前文件。无路径时弹出简易命名框，直接存到表格库。"""
        if not self._current_model.file_path:
            return self._quick_save_to_library()
        try:
            FileHandler.save(self._current_model)
            self._settings.add_recent_file(self._current_model.file_path)
            self._settings.save()
            return True
        except Exception as e:
            QMessageBox.critical(None, '保存失败', f'无法保存文件:\n{e}')
            return False

    def _quick_save_to_library(self) -> bool:
        """无路径文件：弹出输入框输入文件名，检测同名文件后保存到表格库。"""
        default_dir = self._default_dir
        name, ok = QInputDialog.getText(
            None, '保存到表格库', '输入文件名（不带扩展名则默认 .csv）：'
        )
        if not ok or not name.strip():
            return False
        name = name.strip()
        # 自动补扩展名
        if not Path(name).suffix:
            name += '.csv'
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
            'CSV 文件 (*.csv);;Excel 文件 (*.xlsx);;文本文件 (*.txt)'
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

            FileHandler.export_as(self._current_model, path, fmt)
            self._current_model.file_path = path
            self._current_model.file_format = fmt
            self._current_model.mark_clean()
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
        """导出为指定格式。"""
        ext_map = {'csv': '.csv', 'xlsx': '.xlsx', 'txt': '.txt'}
        ext = ext_map.get(fmt, '')
        path, _ = QFileDialog.getSaveFileName(
            None,
            f'导出为 {fmt.upper()}',
            self._default_dir,
            f'{fmt.upper()} 文件 (*{ext})'
        )
        if not path:
            return False
        try:
            FileHandler.export_as(self._current_model, path, fmt)
            return True
        except Exception as e:
            QMessageBox.critical(None, '导出失败', f'无法导出文件:\n{e}')
            return False

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _maybe_save(self) -> bool:
        """检查脏状态，提示用户保存。返回 True 表示可以继续。"""
        if not self._current_model or not self._current_model.is_dirty:
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
