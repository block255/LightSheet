"""分位数脚本 — 对框选区域按行/列分组求分位数，输出一行或一列结果。

流程：框选区域（可自动识别）→ 选方向（对行/对列）+ 分位数（默认中位数0.5，可手动输入
任意 0-1 之间的小数）→ 点选输出行/列（垂直输出）。
识别规则（与平均值脚本一致，空格不报错）：
- 数字格 → 有效数据；
- 文字格 → 标题格，跳过（不参与统计）；
- 空格 → 跳过（不参与统计）；
- 整行/整列文字占比 >30% 或无数字 → 标题行/列，整组排除。
分位数算法（线性定义规则，线性插值）：排序后位置 pos = p*(n-1)，
取 x[floor(pos)] 与 x[ceil(pos)] 线性插值；p=0.5 即标准中位数。
输出：输出轴与处理单位垂直（对列处理 → 输出到行；对行处理 → 输出到列），
标题行/列位置不写入（保留原内容）。
精度：每组数据最大小数位数 + 2，除尽不补零。
"""

from PyQt6.QtWidgets import QApplication

from scripts.base_script import (
    BaseScript, SelectRangeStep, ChooseQuantileStep, OutputTargetStep,
)

_TITLE_RATIO = 0.3


class QuantileScript(BaseScript):
    name = '分位数脚本'
    description = '对框选区域按行/列求分位数（默认中位数，可输入任意 0-1 分位）'

    def steps(self):
        return [
            SelectRangeStep('请框选统计区域'),
            ChooseQuantileStep(
                '选择处理方向并设置分位数',
                direction_options=['对行处理', '对列处理'],
            ),
            OutputTargetStep('选择结果输出位置（输出轴与处理方向垂直）', invert=True),
        ]

    def run(self, sheet, params):
        r1, c1, r2, c2 = params['range']
        direction = params['direction']
        output = params['output']
        p = params['quantile']  # 0.5（中位数）或用户输入的分位数
        by_row = '行' in direction  # 对行处理：每组数据是一行

        def _fmt(v: float) -> str:
            """整数显示为 3，小数显示为 3.5（不出现 3.0）。"""
            if v == int(v):
                return str(int(v))
            return str(v)

        def _count_dec(text: str) -> int:
            t = text.strip()
            if '.' not in t:
                return 0
            return len(t.split('.', 1)[1])

        def _collect(cells: list[str]):
            """收集一组数据：返回 (数值列表, 位数列表, 文字格数, 非空格总数)。"""
            vals, decs = [], []
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
                except ValueError:
                    text_count += 1
            return vals, decs, text_count, total

        def _is_title_group(text_count: int, total: int) -> bool:
            """整组是否为标题行/列（排除出统计）。

            白名单：仅 1 个文字格时豁免（单标题是正常表格结构）；
            2 个及以上文字格才按 30% 占比判定（与运算脚本识别规则一致）。
            """
            return (text_count > 1 and total > 0
                    and text_count / total > _TITLE_RATIO)

        def _quantile_text(vals: list[float], decs: list[int], p: float) -> str:
            """线性插值分位数 + 精度（组内最大位数 + 2，除尽不补零）。"""
            s = sorted(vals)
            n = len(s)
            pos = p * (n - 1)
            lo = int(pos)
            hi = lo + 1
            frac = pos - lo
            if lo >= n - 1:
                q = s[-1]
            else:
                q = s[lo] + frac * (s[hi] - s[lo])
            digits = max(decs) + 2
            return _fmt(round(round(q, digits), 10))

        # 按处理方向分组统计，记录结果与目标位置
        results: list[tuple[int, str]] = []  # (行/列索引, 结果文本)
        if by_row:
            for r in range(r1, r2 + 1):
                cells = [sheet.value(r, c) for c in range(c1, c2 + 1)]
                vals, decs, text_count, total = _collect(cells)
                if not vals or _is_title_group(text_count, total):
                    continue  # 标题行/无数据行，整组排除
                results.append((r, _quantile_text(vals, decs, p)))
        else:
            for c in range(c1, c2 + 1):
                cells = [sheet.value(r, c) for r in range(r1, r2 + 1)]
                vals, decs, text_count, total = _collect(cells)
                if not vals or _is_title_group(text_count, total):
                    continue  # 标题列/无数据列，整组排除
                results.append((c, _quantile_text(vals, decs, p)))

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
