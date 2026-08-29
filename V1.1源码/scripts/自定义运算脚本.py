"""自定义运算脚本 — 可视化积木编程定义运算，仅针对纯数据。

流程：选择运算方向 → 打开积木编辑器构建表达式 → 确定执行输出。
编辑器内用积木（计算元/符号/括号/计数/检定/输出）自由搭建数学表达式，
支持数学优先级（嵌套决定顺序，四则乘除>加减）。
仅针对纯数据：跳过含字符格，顺位取纯数据格；表+常数广播、表+表对齐。
"""

from scripts.base_script import (
    BaseScript, ChooseOptionStep, CustomCalcStep,
)


class CustomCalcScript(BaseScript):
    name = '自定义运算脚本'
    description = '可视化积木编程定义运算（仅纯数据），支持数学优先级'

    def steps(self):
        return [
            ChooseOptionStep('选择运算方向', {
                'direction': ['以列为单位', '以行为单位'],
            }),
            CustomCalcStep('打开编辑器构建自定义运算表达式'),
        ]

    def run(self, sheet, params):
        """执行：从 params 取积木树 + 方向，调用引擎求值并输出。"""
        direction = params.get('direction', '')
        blocks = params.get('custom_blocks', [])

        if not blocks:
            return '未构建自定义运算表达式'

        # 找到输出积木，逐棵执行
        try:
            from custom_calc.engine import EvalContext, Evaluator, CalcError
            ctx = EvalContext(sheet, direction)
            ev = Evaluator(ctx)
            return self._execute_outputs(ev, blocks)
        except CalcError as e:
            return f'❌ {e}'
        except Exception as e:
            return f'❌ 执行异常: {e}'

    def _execute_outputs(self, ev, blocks) -> str | None:
        """执行所有输出积木，把结果写到对应位置。

        重叠判定：**按实际写回位置**（先求值全部，收集各自写回的单元格，
        有交集才算重叠）——目标相同但表结果写不同列不算重叠（2026-08-22 优化）。
        """
        from custom_calc.model import BlockType, OutputTarget
        from custom_calc.engine import TableValue
        outputs = []
        for root in blocks:
            self._collect(root, outputs)
        if not outputs:
            return '未找到输出积木'

        # 先求值全部输出（错误优先返回）
        results = []
        for out in outputs:
            if out.output_target is None:
                return '输出积木未选择输出位置'
            if not out.children or out.children[0].is_interface:
                return '输出积木未连接计算元'
            val = ev.evaluate(out.children[0])
            results.append((out, val))

        # 重叠判定：实际写回单元格集合
        cell_owners = {}
        clipboard_count = 0
        for out, val in results:
            tgt = out.output_target
            if tgt == OutputTarget.CLIPBOARD:
                clipboard_count += 1
                continue
            cells = []
            if tgt == OutputTarget.COL:
                col = out.output_index
                cells = [(pos, col) for pos in val.positions] \
                    if isinstance(val, TableValue) else [(0, col)]
            elif tgt == OutputTarget.ROW:
                row = out.output_index
                cells = [(row, pos) for pos in val.positions] \
                    if isinstance(val, TableValue) else [(row, 0)]
            for r, c in cells:
                if (r, c) in cell_owners:
                    return f'多个输出积木输出位置重叠（行{r + 1} 列{c + 1}）'
                cell_owners[(r, c)] = out
        if clipboard_count > 1:
            return '多个输出积木输出到剪贴板（后者会覆盖前者）'

        # 写入输出位置（按原位置写回）
        from PyQt6.QtWidgets import QApplication
        from PyQt6.QtGui import QGuiApplication
        model = ev._ctx.model  # EvalContext 公开表格模型
        for out, val in results:
            tgt = out.output_target
            if tgt == OutputTarget.CLIPBOARD:
                self._to_clipboard(val, ev._ctx._by_row)
                continue
            # 输出方向一致性（10 计划）：行目标=水平表、列目标=垂直表
            if isinstance(val, TableValue):
                if val.is_grid:
                    return '二维结果（全表/剪贴板二维）只能输出到剪贴板'
                if tgt == OutputTarget.COL and val.kind not in ('col',
                                                                'clipboard1d'):
                    return '输出到列 与结果一维表方向不一致（结果为水平表）'
                if tgt == OutputTarget.ROW and val.kind not in ('row',
                                                                'clipboard1d'):
                    return '输出到行 与结果一维表方向不一致（结果为垂直表）'
            if tgt == OutputTarget.COL:
                col = out.output_index
                if isinstance(val, TableValue):
                    for pos, v in zip(val.positions, val.values):
                        model.set_value(pos, col, self._fmt(v))
                else:
                    model.set_value(0, col, self._fmt(val))
            elif tgt == OutputTarget.ROW:
                row = out.output_index
                if isinstance(val, TableValue):
                    for pos, v in zip(val.positions, val.values):
                        model.set_value(row, pos, self._fmt(v))
                else:
                    model.set_value(row, 0, self._fmt(val))
        return None

    @staticmethod
    def _collect(node, outputs: list):
        from custom_calc.model import BlockType
        if node.type == BlockType.OUTPUT:
            outputs.append(node)
        for c in node.children:
            CustomCalcScript._collect(c, outputs)
        if node.data is not None and node.data.block is not None:
            CustomCalcScript._collect(node.data.block, outputs)

    @staticmethod
    def _fmt(v) -> str:
        """数值格式化：整数不补零。"""
        if isinstance(v, float) and v == int(v):
            return str(int(v))
        return str(v)

    @staticmethod
    def _to_clipboard(val, by_row: bool):
        """剪贴板输出（规格七）：一维结果按方向——行→Tab 横排、列→换行竖排。"""
        from PyQt6.QtWidgets import QApplication
        from custom_calc.engine import TableValue
        if isinstance(val, TableValue):
            vals = val.values
        elif isinstance(val, list):
            vals = val
        else:
            vals = [val]
        sep = '\t' if by_row else '\n'
        text = sep.join(CustomCalcScript._fmt(v) for v in vals)
        QApplication.clipboard().setText(text)
