"""字符串加法脚本 — 按计算元顺序拼接文本，输出一行或一列结果。

流程：框选区域（可自动识别、可排除首行/首列）→ 选运算方向（以行/列为单位）
→ 输入计算元（点选列/行、手动输入文本、剪贴板单文本/多文本）→ 输出位置。
识别规则（字符串专用）：
- 尾部空格忽略、前导空格跳过；数据区空格 → 空文本 ''（占位，不报错）；
- 数字/文字一律当字符串，不区分。
计算元类型：
- 点选列/行：按方向取列或行，格值当字符串；
- 手动输入文本：任意字符串，作为单个值（广播）；
- 剪贴板单文本：整个剪贴板内容作为单个字符串；
- 剪贴板多文本：按方向切分（对行→Tab横排 / 对列→换行竖排）。
拼接逻辑：按面板中计算元从上到下的顺序拼接；空格=空文本；
不同长度按最长计算元对齐（短的补空文本）。
输出：与运算方向一致（对行→横排一行；对列→竖排一列），可输出剪贴板或点选列/行。
"""

from PyQt6.QtWidgets import QApplication

from scripts.base_script import (
    BaseScript, SelectRangeExStep, ChooseOptionStep, TextOperandStep,
    OutputTargetStep,
)


class StringAddScript(BaseScript):
    name = '字符串加法脚本'
    description = '按计算元顺序拼接文本（支持排除首行/首列、剪贴板单/多文本）'

    def steps(self):
        return [
            SelectRangeExStep('请框选处理区域（可排除首行/首列）'),
            ChooseOptionStep('选择运算方向', {
                'direction': ['以列为单位', '以行为单位'],
            }),
            TextOperandStep('输入计算元：每个框点右侧箭头选择 列/行/文本/剪贴板'),
            OutputTargetStep('选择结果输出位置'),
        ]

    def run(self, sheet, params):
        direction = params['direction']
        ops = params['operands']
        slots = ops['slots']
        data_len = ops['data_len']

        # 拼接：按槽位顺序；非常数计算元逐位取文本，单文本/常数广播
        result = [''] * data_len
        for s in slots:
            if s['kind'] in ('text',):
                # 单文本/手动文本：广播到所有位置
                txt = s.get('text', '')
                for i in range(data_len):
                    result[i] += txt
            else:
                # 列/行/剪贴板多文本：逐位拼接
                vals = s.get('values', [])
                for i in range(data_len):
                    txt = vals[i] if i < len(vals) else ''
                    result[i] += txt

        # 空文本显示为 ''
        def _fmt(v: str) -> str:
            return v

        output = params['output']
        if output['target'] == 'clipboard':
            if '行' in direction:
                text = '\t'.join(_fmt(v) for v in result)
            else:
                text = '\n'.join(_fmt(v) for v in result)
            QApplication.clipboard().setText(text)
        else:
            # 从框选区域起始位置开始写；跳过已有非空文本的格子（当作标题保留）
            rng = params.get('range')
            r1 = rng[0] if rng else 0
            c1 = rng[1] if rng else 0
            if output['target'] == 'column':
                col = output['index']
                start = r1
                for i, v in enumerate(result):
                    r = start + i
                    existing = sheet.value(r, col).strip()
                    if existing:
                        continue  # 已有文本 → 标题格，跳过不写
                    sheet.set_value(r, col, _fmt(v))
            else:  # row
                row = output['index']
                start = c1
                for i, v in enumerate(result):
                    c = start + i
                    existing = sheet.value(row, c).strip()
                    if existing:
                        continue  # 已有文本 → 标题格，跳过不写
                    sheet.set_value(row, c, _fmt(v))
        return None
