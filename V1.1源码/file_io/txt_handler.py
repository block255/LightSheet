"""TXT 文件读写。默认使用制表符分隔。"""


def load(file_path: str, delimiter: str = '\t') -> list[list[str]]:
    """读取制表符分隔的文本文件。"""
    rows: list[list[str]] = []
    with open(file_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.rstrip('\n\r')
            if line:
                rows.append(line.split(delimiter))
            else:
                rows.append([''])  # 空行保留为一行空单元格
    return rows


def write(file_path: str, data: list[list[str]], delimiter: str = '\t') -> None:
    """写入制表符分隔的文本文件。"""
    with open(file_path, 'w', encoding='utf-8') as f:
        for row_data in data:
            f.write(delimiter.join(str(v) for v in row_data))
            f.write('\n')
