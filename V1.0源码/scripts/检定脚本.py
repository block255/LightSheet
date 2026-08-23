"""检定脚本 — 对框选区域按行/列分组检定，输出通过/不通过结果（布尔二元输出）。

流程：框选区域（可自动识别）→ 选方向（对行/对列）+ 检定条件 + 检定类型
+ 输出结果 → 点选输出行/列（垂直输出）。
识别规则（与平均值脚本一致，空格不报错）：
- 数字格 → 有效数据（参与判定）；
- 文字格 → 标题格，跳过；空格 → 跳过；
- 整行/整列文字占比 >30% 或无数字 → 标题行/列，整组排除。
检定条件：数据 <符号> 常数（同计数脚本，= > < >= <= ≠ ≡）。
检定类型（通过条件）：
- 任意判定：所有纯数据格都满足条件才通过；
- 存在判定：至少一个纯数据格满足条件即通过；
- 存在型数量自定义：满足条件的格数 ≥ 自定义数量（自然数）；
- 存在型比例自定义：满足条件的格数 / 纯数据格总数 ≥ 自定义比例（[0,1]）。
输出结果（布尔二元）：
- 不通过 → 输出「不通过结果」（默认 0，可自定义任意文字）；
- 通过 → 输出「通过结果」（默认 1，可自定义任意文字）。
输出：输出轴与处理单位垂直（对列处理 → 输出到行；对行处理 → 输出到列），
标题行/列位置不写入（保留原内容）。
剪贴板方向：对行处理 → 竖排；对列处理 → 横排（Tab 分隔），与表格写入一致。
"""

from PyQt6.QtWidgets import QApplication

from scripts.base_script import (
    BaseScript, SelectRangeStep, ChooseInspectStep, OutputTargetStep,
)

_TITLE_RATIO = 0.3

_NUMERIC_OPS = {
    '=':  lambda v, c: v == c,
    '>':  lambda v, c: v > c,
    '<':  lambda v, c: v < c,
    '>=': lambda v, c: v >= c,
    '<=': lambda v, c: v <= c,
    '≠':  lambda v, c: v != c,
}


class InspectScript(BaseScript):
    name = '检定脚本'
    description = '按检定条件对行/列做布尔检定，输出通过/不通过结果'

    def steps(self):
        return [
            SelectRangeStep('请框选检定区域'),
            ChooseInspectStep(
                '选择处理方向并设置检定条件',
                direction_options=['对行处理', '对列处理'],
            ),
            OutputTargetStep('选择结果输出位置（输出轴与处理方向垂直）', invert=True),
        ]

    def run(self, sheet, params):
        r1, c1, r2, c2 = params['range']
        direction = params['direction']
        output = params['output']
        operator = params['operator']
        const_text = str(params['constant'])
        const_val = float(const_text)
        strict = (operator == '≡')
        inspect_type = params.get('inspect_type', '任意判定')
        type_value = params.get('type_value')   # 数量/比例自定义值（文本或 None）
        fail_result = str(params.get('fail_result', '0'))
        pass_result = str(params.get('pass_result', '1'))
        by_row = '行' in direction

        def _collect(cells: list[str]):
            """收集一组数据：返回 (数值列表, 原文列表, 文字格数, 非空格总数)。"""
            vals, origs = [], []
            text_count = 0
            total = 0
            for c in cells:
                v = str(c).strip()
                if v == '':
                    continue
                total += 1
                try:
                    vals.append(float(v))
                    origs.append(v)
                except ValueError:
                    text_count += 1
            return vals, origs, text_count, total

        def _is_title_group(text_count: int, total: int) -> bool:
            return (text_count > 1 and total > 0
                    and text_count / total > _TITLE_RATIO)

        def _satisfy_count(vals: list[float], origs: list[str]) -> int:
            """满足检定条件的纯数据格个数。"""
            if strict:
                return sum(1 for o in origs if o == const_text)
            op = _NUMERIC_OPS.get(operator, _NUMERIC_OPS['='])
            return sum(1 for v in vals if op(v, const_val))

        def _verdict(vals: list[float], origs: list[str]) -> str:
            """返回该组的通过/不通过结果文本。"""
            n_ok = _satisfy_count(vals, origs)
            total_pure = len(vals)
            if inspect_type == '存在判定':
                passed = n_ok >= 1
            elif inspect_type == '存在型数量自定义':
                passed = n_ok >= int(type_value)
            elif inspect_type == '存在型比例自定义':
                ratio = n_ok / total_pure if total_pure else 0.0
                passed = ratio >= float(type_value)
            else:  # 任意判定（默认）：全部满足
                passed = n_ok == total_pure
            return pass_result if passed else fail_result

        results: list[tuple[int, str]] = []
        if by_row:
            for r in range(r1, r2 + 1):
                cells = [sheet.value(r, c) for c in range(c1, c2 + 1)]
                vals, origs, text_count, total = _collect(cells)
                if not vals or _is_title_group(text_count, total):
                    continue
                results.append((r, _verdict(vals, origs)))
        else:
            for c in range(c1, c2 + 1):
                cells = [sheet.value(r, c) for r in range(r1, r2 + 1)]
                vals, origs, text_count, total = _collect(cells)
                if not vals or _is_title_group(text_count, total):
                    continue
                results.append((c, _verdict(vals, origs)))

        if not results:
            return '所选区域无有效统计数据'

        if output['target'] == 'clipboard':
            if by_row:
                text = '\n'.join(t for _, t in results)
            else:
                text = '\t'.join(t for _, t in results)
            QApplication.clipboard().setText(text)
        elif by_row:
            col = output['index']
            for r, t in results:
                sheet.set_value(r, col, t)
        else:
            row = output['index']
            for c, t in results:
                sheet.set_value(row, c, t)
        return None
