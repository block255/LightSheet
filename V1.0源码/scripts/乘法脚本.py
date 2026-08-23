"""乘法脚本 — 将多个计算元逐位置相乘，输出一列或一行结果。

计算元：点选列/行、手动输入常数、从剪贴板接入（可添加多个）。
识别规则：纯数字有效；空格子报错拒绝；含文字格识别为标题（占比 >30% 拒绝）。
保留小数位数（步骤 2 面板可选手动或默认）：
- 默认（自动）：逐位置取各计算元在该位置小数位数的最大值（常数取自身位数）；
- 手动：全局固定 0-10 位；整数结果不补零（3 显示 3，3.14159 保留 2 位显示 3.14）。
输出规则：标题格永远不写结果 ——
- 输出到剪贴板：首行空出标题格，结果逐行排列；
- 输出到点选列/行：有标题保留原标题，无标题留白，结果从标题下方对齐接入。
"""

from PyQt6.QtWidgets import QApplication

from scripts.base_script import (
    BaseScript, ChooseOptionStep, OperandInputStep, OutputTargetStep,
)


class MultiplyScript(BaseScript):
    name = '乘法脚本'
    description = '多个计算元（列/行/常数/剪贴板）逐位置相乘，输出一列或一行'

    def steps(self):
        return [
            ChooseOptionStep('选择运算方向', {
                'direction': ['以列为单位', '以行为单位'],
            }),
            OperandInputStep('输入计算元：每个框点右侧箭头选择 列/行/常数/剪贴板',
                             decimals=True),
            OutputTargetStep('选择结果输出位置'),
        ]

    def run(self, sheet, params):
        direction = params['direction']
        ops = params['operands']
        slots = ops['slots']
        data_len = ops['data_len']
        title_idx = ops['title_idx']
        has_title = ops['has_title']
        dec = ops.get('decimals', {'mode': 'auto', 'digits': None})
        mode = dec.get('mode', 'auto')
        digits = dec.get('digits') if mode == 'manual' else None

        result = [1.0] * data_len
        for s in slots:
            if s['kind'] == 'constant':
                for i in range(data_len):
                    result[i] *= s['value']
            else:
                for i, v in enumerate(s['values']):
                    result[i] *= v

        def _round_value(v: float, n: int) -> float:
            """按 n 位舍入；再 round 10 位消除浮点累计误差。"""
            return round(round(v, n), 10)

        if mode == 'manual':
            n = digits if digits is not None else 10
            result = [_round_value(v, n) for v in result]
        else:
            # 自动：逐位置取各计算元（常数取自身唯一位数）小数位数的最大值
            rounded = []
            for i in range(data_len):
                n = 0
                for s in slots:
                    ds = s.get('decimals') or []
                    d = ds[0] if s['kind'] == 'constant' else (ds[i] if i < len(ds) else 0)
                    if d > n:
                        n = d
                rounded.append(_round_value(result[i], n))
            result = rounded

        def _fmt(v: float) -> str:
            """整数显示为 3，小数显示为 3.5（不出现 3.0）。"""
            if v == int(v):
                return str(int(v))
            return str(v)

        output = params['output']
        if output['target'] == 'clipboard':
            # 输出形态与运算方向一致；全部无标题时不空标题格
            if '行' in direction:
                text = '\t'.join(_fmt(v) for v in result)
                if has_title:
                    text = '\t' + text  # 开头空出标题格
            else:
                lines = [_fmt(v) for v in result]
                if has_title:
                    lines = [''] + lines  # 首行空出标题格
                text = '\n'.join(lines)
            QApplication.clipboard().setText(text)
        else:
            # 有标题：标题格保留/留白，结果从标题下方接入；无标题：从头开始
            start = (title_idx + 1) if has_title else 0
            if output['target'] == 'column':
                col = output['index']
                for i, v in enumerate(result):
                    sheet.set_value(start + i, col, _fmt(v))
            else:  # row
                row = output['index']
                for i, v in enumerate(result):
                    sheet.set_value(row, start + i, _fmt(v))
        return None
