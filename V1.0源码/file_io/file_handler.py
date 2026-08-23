"""文件 I/O 门面 — 格式检测与分发。"""
from pathlib import Path

from models.spreadsheet_model import SpreadsheetModel
from file_io import csv_handler, xlsx_handler, txt_handler


class FileHandler:
    """统一入口：检测格式 → 分发给对应 handler → 返回/写入数据。"""

    # 扩展名 → (handler, format_label)
    _registry: dict[str, tuple] = {
        '.csv':  (csv_handler,  'csv'),
        '.xlsx': (xlsx_handler, 'xlsx'),
        '.xls':  (xlsx_handler, 'xlsx'),  # 旧格式也用 openpyxl 读
        '.txt':  (txt_handler,  'txt'),
        '.tsv':  (txt_handler,  'txt'),
    }

    # ------------------------------------------------------------------
    # 公开方法
    # ------------------------------------------------------------------

    @classmethod
    def detect_format(cls, file_path: str) -> str:
        """根据扩展名返回格式标签 ('csv'/'xlsx'/'txt'/空字符串)。"""
        ext = Path(file_path).suffix.lower()
        _, fmt = cls._registry.get(ext, (None, ''))
        return fmt

    @classmethod
    def load(cls, file_path: str) -> SpreadsheetModel:
        """加载文件 → 新建并填充 SpreadsheetModel。"""
        handler, fmt = cls._get_handler(file_path)
        raw_data = handler.load(file_path)
        model = SpreadsheetModel()
        model.load_2d(raw_data)
        model.file_path = file_path
        model.file_format = fmt
        model.mark_clean()
        return model

    @classmethod
    def save(cls, model: SpreadsheetModel) -> None:
        """保存到 model 已有的 _file_path。"""
        if not model.file_path:
            raise ValueError('无法保存：模型没有关联文件路径。')
        handler, _ = cls._get_handler(model.file_path)
        data = model.to_2d()
        handler.write(model.file_path, data)
        model.mark_clean()

    @classmethod
    def export_as(cls, model: SpreadsheetModel, file_path: str, fmt: str) -> None:
        """导出为指定格式的文件。"""
        handler = cls._handler_for_format(fmt)
        data = model.to_2d()
        handler.write(file_path, data)

    @classmethod
    def is_supported(cls, file_path: str) -> bool:
        ext = Path(file_path).suffix.lower()
        return ext in cls._registry

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    @classmethod
    def _get_handler(cls, file_path: str) -> tuple:
        ext = Path(file_path).suffix.lower()
        entry = cls._registry.get(ext)
        if not entry:
            raise ValueError(f'不支持的文件格式: {ext}')
        return entry

    @classmethod
    def _handler_for_format(cls, fmt: str):
        for _, (handler, label) in cls._registry.items():
            if label == fmt:
                return handler
        raise ValueError(f'不支持的导出格式: {fmt}')
