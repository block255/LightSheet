"""三角脚本 — 对单个计算元施加三角函数，输出一列或一行结果。

计算元：单个槽位（点选列/行、手动常数、剪贴板）。
函数选择：下拉 9 个三角/反三角函数（sin/cos/tan/sec/csc/cot/arcsin/arccos/arctan）。
角度单位：互斥按钮（弧度/度，默认弧度）。
定义域校验：确定时遍历计算元所有值，越界即拒绝并报错（不推进）：
- arcsin/arccos：输入须在 [-1,1]；
- tan/sec 在 cos=0 处无定义；cot/csc 在 sin=0 处无定义（弧度按公式，
  角度制按 90°/180° 整数倍）。
保留小数位数（面板可选手动或默认）：
- 默认（自动）：取计算元该位置小数位数的最大值，再 +2 位（同除法）；
- 手动：全局固定 0-10 位；整数结果不补零。
输出规则：标题格永远不写结果 ——
- 输出到剪贴板：首行空出标题格，结果逐行排列；
- 输出到点选列/行：有标题保留原标题，无标题留白，结果从标题下方对齐接入。
"""

import math

from PyQt6.QtWidgets import QApplication

from scripts.base_script import (
    BaseScript, ChooseOptionStep, OutputTargetStep, TrigFunctionStep,
)

# 函数名（下拉显示）→ (执行函数, 参数是否需要转换角度)
_FUNCTIONS = {
    'sin':   lambda v: math.sin(v),
    'cos':   lambda v: math.cos(v),
    'tan':   lambda v: math.tan(v),
    'sec':   lambda v: 1 / math.cos(v),
    'csc':   lambda v: 1 / math.sin(v),
    'cot':   lambda v: math.cos(v) / math.sin(v),
    'arcsin': lambda v: math.asin(v),
    'arccos': lambda v: math.acos(v),
    'arctan': lambda v: math.atan(v),
}

_FUNC_NAMES = ['sin', 'cos', 'tan', 'sec', 'csc', 'cot',
               'arcsin', 'arccos', 'arctan']


class TrigScript(BaseScript):
    name = '三角脚本'
    description = '对数据施加 sin/cos/tan/sec/csc/cot/反三角，弧度/度可选'

    def steps(self):
        return [
            ChooseOptionStep('选择运算方向', {
                'direction': ['以列为单位', '以行为单位'],
            }),
            TrigFunctionStep(
                '选择函数并输入计算元（默认弧度制，点确定时校验定义域）',
                functions=_FUNC_NAMES,
                units=['弧度制', '角度制'],
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

        function = params.get('function', 'sin')
        unit = params.get('unit', '弧度制')
        is_deg = ('角度' in unit)
        fn = _FUNCTIONS.get(function, _FUNCTIONS['sin'])

        slot = slots[0]
        if slot['kind'] == 'constant':
            values = [slot['value']] * data_len
        else:
            values = slot['values']

        # 反三角不转角度；sin/cos/tan/sec/csc/cot 在角度制下需把度转弧度
        if is_deg and function not in ('arcsin', 'arccos', 'arctan'):
            rad_values = [math.radians(v) for v in values]
        else:
            rad_values = values

        result = [fn(v) for v in rad_values]

        # 小数位数
        def _round_value(v: float, n: int) -> float:
            return round(round(v, n), 10)

        if mode == 'manual':
            n = digits if digits is not None else 10
            result = [_round_value(v, n) for v in result]
        else:
            # 自动：逐位取计算元该位置小数位数的最大值，再 +2
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