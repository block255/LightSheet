"""CSV 文件读写。自动检测编码（utf-8 → gbk → latin-1）。"""
import csv


def load(file_path: str) -> list[list[str]]:
    """读取 CSV 文件，返回二维列表。"""
    encoding = _detect_encoding(file_path)
    rows: list[list[str]] = []
    with open(file_path, 'r', encoding=encoding, newline='') as f:
        reader = csv.reader(f)
        for row in reader:
            rows.append(list(row))
    return rows


def write(file_path: str, data: list[list[str]]) -> None:
    """写入 CSV 文件。"""
    with open(file_path, 'w', encoding='utf-8', newline='') as f:
        writer = csv.writer(f)
        writer.writerows(data)


def _detect_encoding(file_path: str) -> str:
    """尝试编码序列，返回第一个不报错的编码。"""
    for enc in ('utf-8', 'gbk', 'utf-16'):
        try:
            with open(file_path, 'r', encoding=enc) as f:
                f.read(64 * 1024)  # 读 64KB 测试
            return enc
        except (UnicodeDecodeError, UnicodeError):
            continue
    return 'latin-1'
