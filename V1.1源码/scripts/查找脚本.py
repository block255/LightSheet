"""查找脚本 — 按数据或文本条件筛选符合要求的行/列，输出其标题。

流程：框选区域 → 以行/列为单位 + 按数据/按文本查找 → 选参考列/行
+ 填条件 → 选输出位置（提示栏 / 以行剪贴板 / 以列剪贴板）。
识别规则（处理单位逻辑，参考平均值脚本）：
- 单位 = 一行或一列；标题 = 单位内非空格首格（文本→标题，纯数据→行号/列号）
- 按数据查找：参考格 vs 符号+常数（逻辑符号 = > < >= <= ≠ ≡）；参考格为空/非数字 → 报错拒绝
- 按文本查找：参考格文本**包含**输入文本；可忽略首格（跳过参考列/行首格对应单位）
"""

from PyQt6.QtWidgets import QApplication

from scripts.base_script import (
    BaseScript, SelectRangeStep, ChooseOptionStep, FindLookupStep,
    FindOutputStep,
)

_OP_FUNCS = {
    '=':  lambda a, b: a == b,
    '>':  lambda a, b: a > b,
    '<':  lambda a, b: a < b,
    '>=': lambda a, b: a >= b,
    '<=': lambda a, b: a <= b,
    '≠':  lambda a, b: a != b,
    '≡':  lambda a, b: a == b,
}


class FindScript(BaseScript):
    name = '查找脚本'
    description = '按数据或文本条件筛选符合要求的行/列，输出其标题'

    def steps(self):
        return [
            SelectRangeStep('请框选查找区域'),
            ChooseOptionStep('选择查找设置', {
                'unit': ['以行为单位', '以列为单位'],
                'lookup_type': ['按数据查找', '按文本查找'],
            }, labels={'unit': '单位:', 'lookup_type': '查找类型:'}),
            FindLookupStep('已选参考，请填写查找条件后点确定'),
            FindOutputStep('选择查找结果输出位置'),
        ]

    # ------------------------------------------------------------------
    # 执行
    # ------------------------------------------------------------------

    def run(self, sheet, params):
        r1, c1, r2, c2 = params['range']
        by_row = '行' in params['unit']
        lookup_type = params['lookup_type']
        ref = params['ref']
        output = params['find_output']

        if '数据' in lookup_type:
            op = params['operator']
            const = float(params['constant'])
            valid = params.get('_valid_indices')   # 控制器校验已排除标题单位
            try:
                results = self._match_by_data(
                    sheet, r1, c1, r2, c2, by_row, ref, op, const, valid)
            except ValueError as e:
                return f'❌ {e}'
        else:
            text = params['text']
            ignore_head = params.get('ignore_head', '') == '忽略首格'
            try:
                results = self._match_by_text(
                    sheet, r1, c1, r2, c2, by_row, ref, text, ignore_head)
            except ValueError as e:
                return f'❌ {e}'

        if output == 'row':
            QApplication.clipboard().setText('\t'.join(results))
        elif output == 'col':
            QApplication.clipboard().setText('\n'.join(results))
        else:  # hint：完成提示额外显示
            params['find_results'] = '、'.join(results) if results else '无符合'
        return None

    def _match_by_data(self, sheet, r1, c1, r2, c2, by_row, ref, op, const,
                       valid_indices=None):
        """按数据查找：只遍历有效单位（控制器校验已排除标题单位）。"""
        results = []
        if valid_indices is None:
            valid_indices = list(range(r2 - r1 + 1 if by_row else c2 - c1 + 1))
        for idx in valid_indices:
            if by_row:
                r = r1 + idx
                rv = sheet.value(r, ref).strip()
                if rv == '':
                    raise ValueError(f'参考列第{r + 1}行为空，无法判定')
                try:
                    v = float(rv)
                except ValueError:
                    raise ValueError(f'参考列第{r + 1}行非数字，无法判定')
                if _OP_FUNCS[op](v, const):
                    results.append(self._unit_title(sheet, r, r, c1, c2,
                                                    by_row=True))
            else:
                c = c1 + idx
                rv = sheet.value(ref, c).strip()
                if rv == '':
                    raise ValueError(f'参考行第{c + 1}列为空，无法判定')
                try:
                    v = float(rv)
                except ValueError:
                    raise ValueError(f'参考行第{c + 1}列非数字，无法判定')
                if _OP_FUNCS[op](v, const):
                    results.append(self._unit_title(sheet, r1, r2, c, c,
                                                    by_row=False))
        return results

    def _match_by_text(self, sheet, r1, c1, r2, c2, by_row, ref, text, ignore_head):
        results = []
        if by_row:
            start = r1 + 1 if ignore_head else r1
            for r in range(start, r2 + 1):
                rv = sheet.value(r, ref).strip()
                if rv == '':
                    raise ValueError(f'参考列第{r + 1}行为空，无法判定')
                if text in rv:
                    results.append(self._unit_title(sheet, r, r, c1, c2,
                                                    by_row=True))
        else:
            start = c1 + 1 if ignore_head else c1
            for c in range(start, c2 + 1):
                rv = sheet.value(ref, c).strip()
                if rv == '':
                    raise ValueError(f'参考行第{c + 1}列为空，无法判定')
                if text in rv:
                    results.append(self._unit_title(sheet, r1, r2, c, c,
                                                    by_row=False))
        return results

    @staticmethod
    def _unit_title(sheet, row_a, row_b, col_a, col_b, by_row: bool) -> str:
        """单位标题：框选区域内非空格首格；纯数据 → 行号/列号。

        by_row=True：第 row_a 行（遍历 col_a..col_b 找首格）；
        by_row=False：第 col_a 列（遍历 row_a..row_b 找首格）。
        """
        if by_row:
            for c in range(col_a, col_b + 1):
                v = sheet.value(row_a, c).strip()
                if v:
                    return v if not FindScript._is_pure_number(v) \
                        else f'第{row_a + 1}行'
        else:
            for r in range(row_a, row_b + 1):
                v = sheet.value(r, col_a).strip()
                if v:
                    return v if not FindScript._is_pure_number(v) \
                        else f'第{col_a + 1}列'
        return f'第{row_a + 1}行' if by_row else f'第{col_a + 1}列'

    @staticmethod
    def _is_pure_number(v: str) -> bool:
        try:
            float(v)
            return True
        except ValueError:
            return False
