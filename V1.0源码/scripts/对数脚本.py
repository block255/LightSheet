"""对数脚本 — log_底数(真数)，逐位置计算，输出一列或一行结果。

计算元：固定 2 个槽位 —— 底数（第 1 个）、真数（第 2 个）。
每个槽位支持点选列/行、手动输入常数、从剪贴板接入。
底数约束：必须 >0 且 ≠1（点选/剪贴时整列拦截）；底数=0 放行，由 run 结合真数判断。
真数约束：必须 >0（点选/剪贴时整列拦截）。
特殊取值：
- 真数 = 1 → 结果恒为 0（log_a(1) = 0，任何合法底数都成立）；
- 底数 = 0 且真数 = 1 → 结果 0（用户定义：0 的 0 次方为 1，log₀(1) = 0）；
- 底数 = 0 且真数 ≠ 1 → 报错中止（run 内跨槽位判断）。
保留小数位数（面板可选手动或默认）：
- 默认（自动）：逐位置取底数和真数在该位置小数位数的最大值，再 +2 位
  （同除法策略）；
- 手动：全局固定 0-10 位；整数结果不补零。
输出规则：标题格永远不写结果 ——
- 输出到剪贴板：首行空出标题格，结果逐行排列；
- 输出到点选列/行：有标题保留原标题，无标题留白，结果从标题下方对齐接入。
"""

import math

from PyQt6.QtWidgets import QApplication

from scripts.base_script import (
    BaseScript, ChooseOptionStep, OperandInputStep, OutputTargetStep,
)


def _validate_base(values: list[float]) -> str | None:
    """底数校验：必须 >0 且 ≠1。点选列/行/常数时立即调用。

    底数=0 放行（可能搭配真数=1 的合法情形），由 run 内结合真数判断。
    """
    for i, v in enumerate(values):
        if v < 0:
            return f'底数必须大于 0（第 {i + 1} 格为 {v}）'
        if v == 0:
            continue  # 放行，留给 run 判断
        if v == 1:
            return f'底数不能为 1（第 {i + 1} 格为 1）'
    return None


def _validate_arg(values: list[float]) -> str | None:
    """真数校验：必须 >0。点选列/行/常数时立即调用。"""
    for i, v in enumerate(values):
        if v <= 0:
            return f'真数必须大于 0（第 {i + 1} 格为 {v}）'
    return None


class LogarithmScript(BaseScript):
    name = '对数脚本'
    description = 'log_底数(真数)（底数≠1，真数>0），逐位置运算，输出一列或一行'

    def steps(self):
        return [
            ChooseOptionStep('选择运算方向', {
                'direction': ['以列为单位', '以行为单位'],
            }),
            OperandInputStep(
                '输入底数和真数（底数≠1，真数>0，点选时校验）',
                decimals=True,
                fixed_count=2,
                slot_labels=['底数', '真数'],
                slot_validators=[_validate_base, _validate_arg],
            ),
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

        base_slot = slots[0]  # 底数
        arg_slot = slots[1]   # 真数

        # 构建底数/真数数组：常数广播为 data_len 长度
        def _broadcast(slot):
            if slot['kind'] == 'constant':
                return [slot['value']] * data_len
            return slot['values']

        bases = _broadcast(base_slot)
        args = _broadcast(arg_slot)

        # 逐位计算（底数<0、=1 与真数≤0 已在点选时整列拦截）：
        # - 真数=1 → 0（log_a(1)=0 恒成立，含底数=0 情形）
        # - 底数=0 且真数≠1 → 报错（run 内跨槽位判断）
        unit = '列' if '行' in direction else '行'
        result: list[float] = []
        for i in range(data_len):
            b = bases[i]
            a = args[i]
            if a == 1:
                result.append(0.0)
                continue
            if b == 0:
                return (f'❌ 第 {i + 1} {unit}：底数为 0 且真数不为 1'
                        f'（真数 {a}），已中止')
            # 换底公式：log_b(a) = ln(a) / ln(b)
            result.append(math.log(a) / math.log(b))

        # 小数位数
        def _round_value(v: float, n: int) -> float:
            """按 n 位舍入；再 round 10 位消除浮点累计误差。"""
            return round(round(v, n), 10)

        if mode == 'manual':
            n = digits if digits is not None else 10
            result = [_round_value(v, n) for v in result]
        else:
            # 自动：逐位取底数/真数该位置小数位数的最大值，再 +2（同除法）
            rounded = []
            for i in range(data_len):
                n = 0
                for s in slots:
                    ds = s.get('decimals') or []
                    d = ds[0] if s['kind'] == 'constant' else (
                        ds[i] if i < len(ds) else 0)
                    if d > n:
                        n = d
                rounded.append(_round_value(result[i], n + 2))
            result = rounded

        # 输出格式化
        def _fmt(v: float) -> str:
            """整数显示为 3，小数显示为 3.5（不出现 3.0）。"""
            if v == int(v):
                return str(int(v))
            return str(v)

        output = params['output']
        if output['target'] == 'clipboard':
            if '行' in direction:
                text = '\t'.join(_fmt(v) for v in result)
                if has_title:
                    text = '\t' + text
            else:
                lines = [_fmt(v) for v in result]
                if has_title:
                    lines = [''] + lines
                text = '\n'.join(lines)
            QApplication.clipboard().setText(text)
        else:
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