"""众数脚本 — 对框选区域按行/列分组求众数，输出一行或一列结果。

流程：框选区域（可自动识别）→ 选方向（对行/对列）+ 模式（默认/精确）→ 点选输出行/列。
识别规则（与平均值脚本一致，空格不报错）：
- 数字格 → 有效数据；
- 文字格 → 标题格，跳过（不参与统计）；
- 空格 → 跳过（不参与统计）；
- 整行/整列文字占比 >30% 或无数字 → 标题行/列，整组排除。
众数：出现次数最多的值。值相等即视为同一个（8 / 8.0 / 8.00 都算 8.0，数值比较）；
若同一数值有多个不同写法，输出时取保留小数位数最多的那个。
模式：
- 默认：输出第一个众数；全部只出现一次 → 输出第一个值；
- 精确：单众数 → 原格式输出；多众数 → 输出所有并列众数列表（如 [1、2]，顿号分隔）；
        无众数（全部只出现一次）→ 输出「无」。
输出：输出轴与处理单位垂直（对列处理 → 输出到行；对行处理 → 输出到列），
标题行/列位置不写入（保留原内容）。
剪贴板方向：对行处理 → 竖排；对列处理 → 横排（Tab 分隔），与表格写入一致。
"""

from PyQt6.QtWidgets import QApplication

from scripts.base_script import (
    BaseScript, SelectRangeStep, ChooseModeStep, OutputTargetStep,
)

_TITLE_RATIO = 0.3


class ModeScript(BaseScript):
    name = '众数脚本'
    description = '对框选区域按行/列求众数（默认/精确模式），输出一行或一列'

    def steps(self):
        return [
            SelectRangeStep('请框选统计区域'),
            ChooseModeStep(
                '选择处理方向并设置众数模式',
                direction_options=['对行处理', '对列处理'],
                mode_options=['默认', '精确'],
            ),
            OutputTargetStep('选择结果输出位置（输出轴与处理方向垂直）', invert=True),
        ]

    def run(self, sheet, params):
        r1, c1, r2, c2 = params['range']
        direction = params['direction']
        output = params['output']
        mode = params.get('mode', '默认')  # '默认' | '精确'
        by_row = '行' in direction  # 对行处理：每组数据是一行

        def _count_dec(text: str) -> int:
            t = text.strip()
            if '.' not in t:
                return 0
            return len(t.split('.', 1)[1])

        def _collect(cells: list[str]):
            """收集一组数据：返回 (数值列表, 位数列表, 原文列表, 文字格数, 非空格总数)。"""
            vals, decs, origs = [], [], []
            text_count = 0
            total = 0
            for c in cells:
                v = str(c).strip()
                if v == '':
                    continue
                total += 1
                try:
                    vals.append(float(v))
                    decs.append(_count_dec(v))
                    origs.append(v)
                except ValueError:
                    text_count += 1
            return vals, decs, origs, text_count, total

        def _is_title_group(text_count: int, total: int) -> bool:
            """整组是否为标题行/列（排除出统计）。

            白名单：仅 1 个文字格时豁免（单标题是正常表格结构）；
            2 个及以上文字格才按 30% 占比判定（与运算脚本识别规则一致）。
            """
            return (text_count > 1 and total > 0
                    and text_count / total > _TITLE_RATIO)

        def _best_repr(v: float, vals, decs, origs) -> str:
            """取该数值所有写法中保留小数位数最多的原文。"""
            best, best_d = origs[0], -1
            for i, val in enumerate(vals):
                if val == v and decs[i] > best_d:
                    best, best_d = origs[i], decs[i]
            return best

        def _mode_text(vals, decs, origs, mode) -> str:
            """求众数文本。值相等视为同一（数值比较）；取位数最多写法显示。"""
            from collections import Counter
            counts = Counter(vals)
            max_count = max(counts.values())
            # 所有众数值（按首次出现顺序去重）
            modes = []
            seen = set()
            for v in vals:
                if counts[v] == max_count and v not in seen:
                    seen.add(v)
                    modes.append(v)
            if mode == '精确':
                if max_count == 1:
                    return '无'  # 全部只出现一次，无众数
                if len(modes) == 1:
                    return _best_repr(modes[0], vals, decs, origs)
                return '[' + '、'.join(
                    _best_repr(m, vals, decs, origs) for m in modes) + ']'
            else:  # 默认
                if max_count == 1:
                    return origs[0]  # 全部只出现一次 → 第一个值
                return _best_repr(modes[0], vals, decs, origs)  # 第一个众数

        # 按处理方向分组统计，记录结果与目标位置
        results: list[tuple[int, str]] = []  # (行/列索引, 结果文本)
        if by_row:
            for r in range(r1, r2 + 1):
                cells = [sheet.value(r, c) for c in range(c1, c2 + 1)]
                vals, decs, origs, text_count, total = _collect(cells)
                if not vals or _is_title_group(text_count, total):
                    continue  # 标题行/无数据行，整组排除
                results.append((r, _mode_text(vals, decs, origs, mode)))
        else:
            for c in range(c1, c2 + 1):
                cells = [sheet.value(r, c) for r in range(r1, r2 + 1)]
                vals, decs, origs, text_count, total = _collect(cells)
                if not vals or _is_title_group(text_count, total):
                    continue  # 标题列/无数据列，整组排除
                results.append((c, _mode_text(vals, decs, origs, mode)))

        if not results:
            return '所选区域无有效统计数据'

        if output['target'] == 'clipboard':
            if by_row:
                # 对行处理 → 结果输出为列（竖排）
                text = '\n'.join(t for _, t in results)
            else:
                # 对列处理 → 结果输出为行（横排，Tab 分隔）
                text = '\t'.join(t for _, t in results)
            QApplication.clipboard().setText(text)
        elif by_row:
            # 对行处理 → 输出到点选列，跳过标题行位置（不写入）
            col = output['index']
            for r, t in results:
                sheet.set_value(r, col, t)
        else:
            # 对列处理 → 输出到点选行，跳过标题列位置（不写入）
            row = output['index']
            for c, t in results:
                sheet.set_value(row, c, t)
        return None
