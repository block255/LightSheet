"""计算元识别与组装 —— 桌面版控制器与本地 Web 版共享（单源码）。

从 ScriptController 抽出的纯逻辑（2026-08-24）：
- parse_numeric_cells：一列/一行数值识别（标题/数值/小数位数/错误）
- build_operands：把计算元槽位（列/行/常数）组装成脚本 run 所需的
  params['operands'] = {slots, data_len, title_idx, has_title}

桌面版与 Web 版用同一份逻辑，保证两端识别结果一致。
"""
from __future__ import annotations

TITLE_RATIO_THRESHOLD = 0.3
INVALID_RATIO_THRESHOLD = 0.3


def is_numeric(s: str) -> bool:
    try:
        float(s)
        return True
    except ValueError:
        return False


def validate_numeric_reference(cells: list) -> tuple[list[int], str | None]:
    """参考列/行校验（排序脚本）：返回 (有效索引列表, 错误)。

    规则：非空格格中非数字占比 >30% 报错；有效索引 = 非空格且数字的索引。
    """
    non_empty = [(i, c) for i, c in enumerate(cells) if str(c).strip()]
    if not non_empty:
        return [], '参考区域无数据'
    invalid = [(i, c) for i, c in non_empty if not is_numeric(str(c))]
    ratio = len(invalid) / len(non_empty)
    if ratio > INVALID_RATIO_THRESHOLD:
        examples = ', '.join(f'[{v}]' for _, v in invalid[:3])
        return [], f'无效数据过多 ({len(invalid)}/{len(non_empty)}): {examples}'
    bad_idx = {i for i, _ in invalid}
    valid = [i for i in range(len(cells))
             if i not in bad_idx and str(cells[i]).strip()]
    return valid, None


def validate_find_reference(cells: list) -> tuple[list[int], str | None]:
    """查找脚本参考校验（文本格=标题单位跳过，单标题豁免，>30% 报错）。"""
    non_empty = [(i, c) for i, c in enumerate(cells) if str(c).strip()]
    if not non_empty:
        return [], '参考区域无数据'
    text_idx = [i for i, c in non_empty if not is_numeric(str(c))]
    if len(text_idx) > 1 and len(text_idx) / len(non_empty) > 0.3:
        return [], f'无效数据过多（标题占比 >30%，共 {len(text_idx)} 个）'
    text_set = set(text_idx)
    valid = [i for i in range(len(cells))
             if i not in text_set and str(cells[i]).strip()]
    return valid, None


def count_decimals(text: str) -> int:
    """从原始文本数小数位数：'2.50' → 2；'3' → 0；'-1.25' → 2。"""
    t = text.strip().lower()
    if 'e' in t:
        t = format(float(t), 'f')
    if '.' not in t:
        return 0
    return len(t.split('.', 1)[1])


def max_decimals_in_area(matrix: list[list], r1, c1, r2, c2) -> int | None:
    """区域内纯数据格的最大小数位数；无纯数据格返回 None。"""
    max_d = -1
    found = False
    for r in range(r1, r2 + 1):
        for c in range(c1, c2 + 1):
            v = str(matrix[r][c]).strip() if r < len(matrix) and c < len(matrix[r]) else ''
            if v == '':
                continue
            try:
                float(v)
            except ValueError:
                continue
            found = True
            d = count_decimals(v)
            if d > max_d:
                max_d = d
    return max_d if found else None


def pad_decimals_in_area(matrix: list[list], r1, c1, r2, c2,
                         target: int | None = None) -> tuple[int, int | None, str | None]:
    """对区域内纯数据格补齐小数位数（与桌面版 decimal_pad 一致）。

    target=None 时用区域内最大位数。返回 (处理格数, 目标位数, 错误)。
    """
    if target is None:
        target = max_decimals_in_area(matrix, r1, c1, r2, c2)
    if target is None:
        return 0, None, '区域内无纯数据格，未执行补齐'
    count = 0
    for r in range(r1, r2 + 1):
        for c in range(c1, c2 + 1):
            v = str(matrix[r][c]).strip() if r < len(matrix) and c < len(matrix[r]) else ''
            if v == '':
                continue
            try:
                num = float(v)
            except ValueError:
                continue
            padded = f'{num:.{target}f}'
            if matrix[r][c] != padded:
                matrix[r][c] = padded
                count += 1
    return count, target, None


def parse_text_cells(cells: list) -> tuple[list[str], str | None]:
    """识别一列/一行字符串数据：返回 (文本列表, 错误)。

    规则（字符串运算）：尾部空格忽略；前导空格跳过；
    数据区空格 → 空文本 ''（占位，不报错）；数字/文字一律当字符串。
    """
    raw = [str(c) for c in cells]
    while raw and raw[-1].strip() == '':
        raw.pop()
    if not raw:
        return [], '所选内容为空'
    start = 0
    while start < len(raw) and raw[start].strip() == '':
        start += 1
    return [c.strip() for c in raw[start:]], None


def build_text_operands(raw_slots: list, matrix: list[list], direction: str = '') -> dict | str:
    """文本计算元组装（字符串加法）。raw_slots 元素：
        {'kind': 'column'/'row', 'index': n} → 文本 values（parse_text_cells）
        {'kind': 'text', 'value': 文本} → 广播
        {'kind': 'clipboard_single', 'value': 文本} → 广播
        {'kind': 'clipboard_multi', 'value': 文本} → 按方向切分（对行→Tab/对列→换行）
    对齐检查：column/row/text_multi 的 values 长度必须一致（与桌面版一致）。
    """
    slots = []
    for s in raw_slots:
        kind = s['kind']
        if kind in ('column', 'row'):
            idx = s['index']
            if kind == 'column':
                cells = [matrix[r][idx] if idx < len(matrix[r]) else ''
                         for r in range(len(matrix))]
            else:
                cells = list(matrix[idx]) if idx < len(matrix) else []
            vals, err = parse_text_cells(cells)
            if err:
                return err
            slots.append({'kind': kind, 'index': idx, 'values': vals})
        elif kind == 'text' or kind == 'clipboard_single':
            slots.append({'kind': 'text', 'text': str(s.get('value', ''))})
        elif kind == 'clipboard_multi':
            text = str(s.get('value', ''))
            cells = text.split('\t') if '行' in direction else text.split('\n')
            vals, err = parse_text_cells(cells)
            if err:
                return err
            slots.append({'kind': 'text_multi', 'values': vals})
        else:
            return f'未知计算元类型: {kind}'
    if not slots:
        return '没有计算元'
    lengths = [len(s['values']) for s in slots
               if s['kind'] in ('column', 'row', 'text_multi')]
    if lengths and len(set(lengths)) > 1:
        return f'计算元未对齐（数据长度 {lengths}），请调整后重试'
    data_len = lengths[0] if lengths else 1
    return {'slots': slots, 'data_len': data_len, 'has_title': False}


def parse_numeric_cells(cells: list) -> tuple[str | None, int, list[float], list[int], str | None]:
    """识别一列/一行数据：返回 (标题, 标题索引, 数值列表, 逐位小数位数列表, 错误)。"""
    raw = [str(c) for c in cells]
    while raw and raw[-1].strip() == '':
        raw.pop()
    if not raw:
        return None, 0, [], [], '所选内容为空'
    start = 0
    while start < len(raw) and raw[start].strip() == '':
        start += 1
    title: str | None = None
    title_idx = 0
    values: list[float] = []
    decimals: list[int] = []
    text_count = 0
    for i in range(start, len(raw)):
        v = raw[i].strip()
        if v == '':
            return None, 0, [], [], f'第 {i + 1} 格为空，拒绝'
        try:
            values.append(float(v))
        except ValueError:
            text_count += 1
            if title is None:
                title = v
                title_idx = i
            continue
        decimals.append(count_decimals(v))
    total = len(raw) - start
    if text_count > 1 and total > 0 and text_count / total > TITLE_RATIO_THRESHOLD:
        return None, 0, [], [], f'标题/文字格过多 ({text_count}/{total})'
    return title, title_idx, values, decimals, None


def build_slot_from_column(matrix: list[list], index: int) -> dict | str:
    """整列 → 计算元槽位。返回槽位 dict 或错误字符串。"""
    cells = [matrix[r][index] if index < len(matrix[r]) else ''
             for r in range(len(matrix))]
    title, title_idx, values, decimals, err = parse_numeric_cells(cells)
    if err:
        return f'列 {index + 1}：{err}'
    return {'kind': 'column', 'index': index, 'title': title,
            'title_idx': title_idx, 'values': values, 'decimals': decimals}


def build_slot_from_row(matrix: list[list], index: int) -> dict | str:
    """整行 → 计算元槽位。返回槽位 dict 或错误字符串。"""
    cells = list(matrix[index]) if index < len(matrix) else []
    title, title_idx, values, decimals, err = parse_numeric_cells(cells)
    if err:
        return f'行 {index + 1}：{err}'
    return {'kind': 'row', 'index': index, 'title': title,
            'title_idx': title_idx, 'values': values, 'decimals': decimals}


def build_operands(raw_slots: list, matrix: list[list], direction: str = '',
                   decimals: dict | None = None) -> dict | str:
    """组装 params['operands']。raw_slots 元素：
        {'kind': 'column', 'index': n} / {'kind': 'row', 'index': n} /
        {'kind': 'constant', 'value': 数字文本} /
        {'kind': 'clipboard', 'value': 剪贴板文本}
    direction 含'行'时剪贴板按 Tab 横排切分，否则按换行竖排（与桌面版一致）。
    decimals：保留小数位数设置 {mode: 'auto'|'manual', digits: int|None}，
    桌面版由面板组装进 operands（脚本 run 读 ops.get('decimals')）。
    返回 operands dict 或错误字符串。
    """
    slots = []
    for s in raw_slots:
        if s['kind'] == 'column':
            built = build_slot_from_column(matrix, s['index'])
        elif s['kind'] == 'row':
            built = build_slot_from_row(matrix, s['index'])
        elif s['kind'] == 'constant':
            try:
                built = {'kind': 'constant', 'value': float(s['value'])}
            except (TypeError, ValueError):
                return f'常数无效: {s.get("value")}'
        elif s['kind'] == 'clipboard':
            text = str(s.get('value', ''))
            cells = text.split('\t') if '行' in direction else text.split('\n')
            title, title_idx, values, decimals, err = parse_numeric_cells(cells)
            if err:
                return f'剪贴板：{err}'
            built = {'kind': 'clipboard', 'title': title, 'title_idx': title_idx,
                     'values': values, 'decimals': decimals}
        else:
            return f'未知计算元类型: {s.get("kind")}'
        if isinstance(built, str):
            return built
        slots.append(built)

    if not slots:
        return '没有计算元'

    lengths = [len(s['values']) for s in slots if s['kind'] != 'constant']
    if lengths:
        if len(set(lengths)) > 1:
            return f'计算元长度不一致（对齐失败）: {lengths}'
        data_len = lengths[0]
    else:
        data_len = 1
    first_data = next((s for s in slots if s['kind'] != 'constant'), None)
    operands = {
        'slots': slots,
        'data_len': data_len,
        'title_idx': first_data.get('title_idx', 0) if first_data else 0,
        'has_title': any(s.get('title') is not None for s in slots),
    }
    if decimals:
        operands['decimals'] = decimals
    return operands
