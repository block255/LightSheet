"""计数脚本 — 对框选区域按行/列分组，统计满足计数条件的纯数据个数。

流程：框选区域（可自动识别）→ 选方向（对行/对列）+ 计数条件
（符号下拉 + 常数输入）→ 点选输出行/列（垂直输出）。
识别规则（与平均值脚本一致，空格不报错）：
- 数字格 → 有效数据（参与判定）；
- 文字格 → 标题格，跳过（不参与判定）；
- 空格 → 跳过（不参与判定）；
- 整行/整列文字占比 >30% 或无数字 → 标题行/列，整组排除。
计数条件：数据 <符号> 常数，如「数据 > 2」——把组内每个纯数据代入判定，
满足条件的计入；输出满足条件的个数（整数）。
符号（7 种）：=  >  <  >=  <=  ≠  ≡
- 除 ≡ 外：只对数值判定（8 / 8.0 / 8.00 视为同一值）；
- ≡（严格等于）：不仅值相同，文本写法也要相同
  （如常数 2，数据 2.0 → 严格不相等；数据 2 → 严格相等）。
输出：输出轴与处理单位垂直（对列处理 → 输出到行；对行处理 → 输出到列），
标题行/列位置不写入（保留原内容）。
剪贴板方向：对行处理 → 竖排；对列处理 → 横排（Tab 分隔），与表格写入一致。
"""

from PyQt6.QtWidgets import QApplication

from scripts.base_script import (
    BaseScript, SelectRangeStep, ChooseCountStep, OutputTargetStep,
)

_TITLE_RATIO = 0.3

# 符号 → 判定函数（数值比较；const_val 为 float）
_NUMERIC_OPS = {
    '=':  lambda v, c: v == c,
    '>':  lambda v, c: v > c,
    '<':  lambda v, c: v < c,
    '>=': lambda v, c: v >= c,
    '<=': lambda v, c: v <= c,
    '≠':  lambda v, c: v != c,
}


class CountScript(BaseScript):
    name = '计数脚本'
    description = '统计框选区域中满足条件（数据 op 常数）的个数，按行/列输出'

    def steps(self):
        return [
            SelectRangeStep('请框选统计区域'),
            ChooseCountStep(
                '选择处理方向并设置计数条件',
                direction_options=['对行处理', '对列处理'],
            ),
            OutputTargetStep('选择结果输出位置（输出轴与处理方向垂直）', invert=True),
        ]

    def run(self, sheet, params):
        r1, c1, r2, c2 = params['range']
        direction = params['direction']
        output = params['output']
        operator = params['operator']      # '=' '>' '<' '>=' '<=' '≠' '≡'
        const_text = str(params['constant'])  # 常数原文文本
        const_val = float(const_text)
        strict = (operator == '≡')         # 严格相等：值和写法都相同
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
            """整组是否为标题行/列（排除出统计）。"""
            return (text_count > 1 and total > 0
                    and text_count / total > _TITLE_RATIO)

        def _count_ok(vals: list[float], origs: list[str]) -> int:
            """统计满足条件的个数。"""
            if strict:
                # 严格相等：值和写法都相同（原文 vs 常数原文）
                return sum(1 for o in origs if o == const_text)
            op = _NUMERIC_OPS.get(operator, _NUMERIC_OPS['='])
            return sum(1 for v in vals if op(v, const_val))

        # 按处理方向分组统计，记录结果与目标位置
        results: list[tuple[int, str]] = []
        if by_row:
            for r in range(r1, r2 + 1):
                cells = [sheet.value(r, c) for c in range(c1, c2 + 1)]
                vals, origs, text_count, total = _collect(cells)
                if not vals or _is_title_group(text_count, total):
                    continue
                results.append((r, str(_count_ok(vals, origs))))
        else:
            for c in range(c1, c2 + 1):
                cells = [sheet.value(r, c) for r in range(r1, r2 + 1)]
                vals, origs, text_count, total = _collect(cells)
                if not vals or _is_title_group(text_count, total):
                    continue
                results.append((c, str(_count_ok(vals, origs))))

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
            col = output['index']
            for r, t in results:
                sheet.set_value(r, col, t)
        else:
            row = output['index']
            for c, t in results:
                sheet.set_value(row, c, t)
        return None
