"""状态栏构建。"""
from PyQt6.QtWidgets import QStatusBar, QLabel
from PyQt6.QtCore import Qt


class StatusBar(QStatusBar):
    """应用状态栏 — 显示状态消息、行列坐标、文件信息。"""

    def __init__(self, parent=None):
        super().__init__(parent)

        self._status_label = QLabel('')
        self._mode_label = QLabel('✏️ 编辑')
        self._cell_label = QLabel('行: 1  列: A')
        self._file_label = QLabel('')
        self._format_label = QLabel('')
        self._dim_label = QLabel('26 × 100')

        self.addWidget(self._status_label, 1)
        self.addPermanentWidget(self._mode_label)
        self.addPermanentWidget(self._cell_label)
        self.addPermanentWidget(self._file_label)
        self.addPermanentWidget(self._format_label)
        self.addPermanentWidget(self._dim_label)

        for lbl in [self._mode_label, self._cell_label, self._file_label,
                     self._format_label, self._dim_label]:
            lbl.setStyleSheet('padding: 0 8px;')

    # ------------------------------------------------------------------
    # 公开方法
    # ------------------------------------------------------------------

    def set_status(self, text: str) -> None:
        self._status_label.setText(text)

    def set_cell_position(self, row: int, col: int) -> None:
        from models.spreadsheet_model import SpreadsheetModel
        letter = SpreadsheetModel.col_letter(col)
        self._cell_label.setText(f'行: {row + 1}  列: {letter}')

    def set_file_info(self, name: str | None, dirty: bool = False) -> None:
        if not name:
            self._file_label.setText('')
            return
        suffix = ' (已修改)' if dirty else ''
        self._file_label.setText(f'{name}{suffix}')

    def set_format(self, fmt: str) -> None:
        self._format_label.setText(fmt.upper() if fmt else '')

    def set_dimensions(self, rows: int, cols: int) -> None:
        from models.spreadsheet_model import SpreadsheetModel
        letters = SpreadsheetModel.col_letter(cols - 1)
        self._dim_label.setText(f'{letters} × {rows}')

    def set_edit_mode(self, enabled: bool) -> None:
        self._mode_label.setText('✏️ 编辑' if enabled else '👁 浏览')
