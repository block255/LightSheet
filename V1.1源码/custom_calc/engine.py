"""自定义运算 — 运算引擎（表达式求值）。

设计要点（参考信息库/自定义运算/04-接口规则.md、06-运算引擎、09-引擎位置对齐改造计划）：
- 数学优先级：嵌套结构决定顺序，四则按乘除 > 加减
- 函数/括号/计数/检定积木语义都是"一个值"
- 表 + 常数：广播（逐位置）；表 + 表：**按表格位置严格对齐**（位置集合完全相等，
  对不齐报错）；剪贴板一维表：格数相同顺序对齐；剪贴板二维表：与表对拒绝
- 数据源：跳过含字符格/空格（不产生值但占位置），取纯数据格（不用框选）
"""
from __future__ import annotations

import math
from typing import Optional

from custom_calc.model import (
    BlockType, CalcSubtype, SymKind, InputKind, OutputTarget,
    OP_FUNCS, LOGIC_FUNCS, TRIG_FUNCS,
)


class CalcError(Exception):
    """运算错误（含用户可读信息）。"""


class TableValue:
    """带位置的表格数据。

    - positions: 位置键列表
        列 → [行号...]；行 → [列号...]；全表/二维 → [(r, c)...]
    - values: 与 positions 一一对应的值
    - kind: 'col' | 'row' | 'grid'(二维/全表) | 'clipboard1d'
    - origin: 来源描述（如 '列B'）用于报错
    - 空格/文本不产生值但占位置（位置键只收录纯数据格）
    """

    def __init__(self, positions, values, kind: str, origin: str = ''):
        self.positions = list(positions)
        self.values = list(values)
        self.kind = kind
        self.origin = origin

    def __len__(self) -> int:
        return len(self.values)

    @property
    def is_clipboard_1d(self) -> bool:
        return self.kind == 'clipboard1d'

    @property
    def is_grid(self) -> bool:
        return self.kind == 'grid'

    def describe(self) -> str:
        return self.origin or f'{self.kind}表'

    def align_positions(self, other: 'TableValue') -> str | None:
        """检查位置集合是否完全相等；不等返回差异描述，相等返回 None。"""
        if self.is_clipboard_1d or other.is_clipboard_1d:
            return None   # 剪贴板一维：顺序对齐，格数另查
        a = set(self.positions)
        b = set(other.positions)
        if a == b:
            return None
        only_a = sorted(a - b)
        only_b = sorted(b - a)
        return (f'表格位置未对齐：{self.describe()} 独有位置 {only_a[:6]}'
                f'；{other.describe()} 独有位置 {only_b[:6]}')


class EvalContext:
    """求值上下文：提供表格数据访问（带位置）。"""

    def __init__(self, model, direction: str):
        """
        model: 表格模型（提供 value(r, c)）
        direction: '行' 或 '列'（脚本第一步选的运算方向）
        """
        self.model = model  # 公开属性：输出积木写回表格用
        self._model = model  # 内部别名（兼容旧代码）
        self._by_row = ('行' in direction)

    # ------------------------------------------------------------------
    # 数据获取（返回 TableValue，带位置）
    # ------------------------------------------------------------------

    def get_row(self, index: int) -> TableValue:
        """第 index 行的纯数据格（跳过含字符格，位置 = 列号）。"""
        pos, vals = [], []
        for c in range(self._model.col_total):
            v = self._model.value(index, c).strip()
            if v == '':
                continue
            try:
                vals.append(float(v))
                pos.append(c)
            except ValueError:
                continue  # 跳过含字符格（占位置不产生值）
        return TableValue(pos, vals, 'row', origin=f'行{index + 1}')

    def get_col(self, index: int) -> TableValue:
        """第 index 列的纯数据格（跳过含字符格，位置 = 行号）。"""
        pos, vals = [], []
        for r in range(self._model.row_total):
            v = self._model.value(r, index).strip()
            if v == '':
                continue
            try:
                vals.append(float(v))
                pos.append(r)
            except ValueError:
                continue
        return TableValue(pos, vals, 'col', origin=f'列{self._col_letter(index)}')

    def get_whole_table(self) -> TableValue:
        """整个表格的纯数据格（位置 = (r, c)）。

        识别范围（用户确认 2026-08-22）：**从左上到最右下有纯数据的外接矩形**
        （data_bounds）；矩形内的空格/文本**不产生值但占位置**（跳过不入
        positions——对齐检测以位置集合为准，缺位 → 位置集合不同 → 报错）。
        """
        bounds = self._model.data_bounds()
        if bounds is None:
            return TableValue([], [], 'grid', origin='整个表格')
        min_r, min_c, max_r, max_c = bounds
        pos, vals = [], []
        for r in range(min_r, max_r + 1):
            for c in range(min_c, max_c + 1):
                v = self._model.value(r, c).strip()
                if v == '':
                    continue
                try:
                    vals.append(float(v))
                    pos.append((r, c))
                except ValueError:
                    continue
        return TableValue(pos, vals, 'grid', origin='整个表格')

    @staticmethod
    def _col_letter(index: int) -> str:
        """列索引 → 字母（0→A）。"""
        s = ''
        i = index + 1
        while i:
            i, r = divmod(i - 1, 26)
            s = chr(ord('A') + r) + s
        return s

    # ------------------------------------------------------------------
    # 剪贴板解析（识别一维/二维）
    # ------------------------------------------------------------------

    @staticmethod
    def parse_clipboard(text: str, by_row: bool) -> TableValue:
        """解析剪贴板文本为 TableValue。

        - 仅 Tab（单行）→ 横排一维表（clipboard1d）
        - 仅换行（单列）→ 竖排一维表（clipboard1d）
        - Tab + 换行 → 二维表（grid）
        by_row: 是否以行为单位（决定剪贴板形态校验由编辑器做，这里只解析）
        """
        norm = text.replace('\r\n', '\n').replace('\r', '\n').strip()
        lines = norm.split('\n')
        has_tab = any('\t' in ln for ln in lines)
        has_nl = len(lines) > 1

        def _to_float(s):
            try:
                return float(s.strip())
            except ValueError:
                return None

        if has_nl and has_tab:
            # 二维表（grid）：所有纯数字格，位置 (r, c)
            pos, vals = [], []
            for r, ln in enumerate(lines):
                for c, cell in enumerate(ln.split('\t')):
                    v = _to_float(cell)
                    if v is not None:
                        pos.append((r, c))
                        vals.append(v)
            return TableValue(pos, vals, 'grid', origin='剪贴板(二维)')
        # 一维表：横向或纵向
        cells = []
        if has_tab:
            cells = norm.split('\t')       # 横排
        else:
            cells = lines if has_nl else norm.split('\t')   # 竖排
        pos, vals = [], []
        for i, cell in enumerate(cells):
            v = _to_float(cell)
            if v is not None:
                pos.append(i)
                vals.append(v)
        return TableValue(pos, vals, 'clipboard1d', origin='剪贴板(一维)')

    # ------------------------------------------------------------------
    # 广播与对齐
    # ------------------------------------------------------------------

    @staticmethod
    def broadcast(a, b):
        """广播：标量与表逐位置；表与表对齐。返回 (values, is_table)。

        设计记录（09 改造计划）：表+表按位置严格对齐（剪贴板一维顺序对齐）。
        """
        a_tbl = isinstance(a, TableValue)
        b_tbl = isinstance(b, TableValue)
        if not a_tbl and not b_tbl:
            return a, False
        if a_tbl and b_tbl:
            return EvalContext._align_tables(a, b)
        if a_tbl:
            return a, True
        return b, True

    @staticmethod
    def _align_tables(a: TableValue, b: TableValue):
        """表+表对齐：位置严格相等（剪贴板一维格数相同顺序对齐）。"""
        vals = EvalContext._align_tables_values(a, b)
        return [x for x in vals], True

    @staticmethod
    def _align_tables_values(a: TableValue, b: TableValue) -> list:
        """表+表对齐返回逐格值列表（按 a 的位置顺序取 b 对应值）。

        剪贴板一维：顺序对齐，返回 b 的值列表（a 是主表用其位置，
        b 是剪贴板一维时按顺序取 b.values）。
        """
        if a.is_clipboard_1d and b.is_clipboard_1d:
            if len(a) != len(b):
                raise CalcError(f'表格未对齐（{a.describe()} 长度 {len(a)} vs '
                                f'{b.describe()} 长度 {len(b)}）')
            return [x for x in b.values]
        if a.is_clipboard_1d:
            if b.is_grid:
                raise CalcError('剪贴板一维不能与二维表混算')
            # a 是剪贴板一维、b 是表：顺序对齐，返回 b 前 len(a) 个
            if len(a) != len(b):
                raise CalcError(f'表格未对齐（{a.describe()} 长度 {len(a)} vs '
                                f'{b.describe()} 长度 {len(b)}）')
            return [x for x in b.values]
        if b.is_clipboard_1d:
            if a.is_grid:
                raise CalcError('剪贴板一维不能与二维表混算')
            # b 是剪贴板一维：按 a 位置顺序取 b 值（顺序对应）
            if len(a) != len(b):
                raise CalcError(f'表格未对齐（{a.describe()} 长度 {len(a)} vs '
                                f'{b.describe()} 长度 {len(b)}）')
            return [x for x in b.values]
        # 二维 vs 一维：维度不同，明确拒绝（审计 2026-08-22）
        if a.is_grid != b.is_grid:
            raise CalcError(f'二维表不能与一维表混算（{a.describe()} 与 '
                            f'{b.describe()}）')
        # 一维表方向检测（10 计划）：列表 vs 行表 → 拒绝（明确报错）
        if (a.kind, b.kind) in (('col', 'row'), ('row', 'col')):
            raise CalcError(f'一维表方向不同：{a.describe()} 与 {b.describe()} '
                            '（列方向表与行方向表不能混算）')
        # 普通表：位置集合完全相等
        diff = a.align_positions(b)
        if diff:
            raise CalcError(diff)
        # 按 a 的位置顺序逐格（b 的位置集合相同，但顺序可能不同）
        b_map = dict(zip(b.positions, b.values))
        return [b_map[p] for p in a.positions]


class Evaluator:
    """递归求值器。"""

    def __init__(self, ctx: EvalContext):
        self._ctx = ctx

    # ------------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------------

    def evaluate(self, node) -> float | list[float]:
        """求值积木节点，返回单值或表格值列表。"""
        t = node.type
        if t == BlockType.CALC:
            return self._eval_calc(node)
        if t == BlockType.SYMBOL:
            raise CalcError('符号不能独立求值')
        if t == BlockType.PAREN:
            return self._eval_chain(node.children)
        if t == BlockType.COUNT:
            return self._eval_count(node)
        if t == BlockType.CHECK:
            return self._eval_check(node)
        if t == BlockType.OUTPUT:
            raise CalcError('输出积木不应参与表达式求值')
        raise CalcError(f'未知积木类型: {t}')

    # ------------------------------------------------------------------
    # 计算元
    # ------------------------------------------------------------------

    def _eval_calc(self, node):
        st = node.calc_subtype
        if st == CalcSubtype.NUM:
            return self._eval_data(node.data)
        if st == CalcSubtype.EXP:
            base = self.evaluate(node.children[0])
            exp = self.evaluate(node.children[1])
            return self._binop('^', base, exp)
        if st == CalcSubtype.LOG:
            base = self.evaluate(node.children[0])
            arg = self.evaluate(node.children[1])
            return self._binop('log', base, arg)
        if st == CalcSubtype.TRIG:
            if not node.trig_func:
                raise CalcError('三角函数未定义')
            val = self.evaluate(node.children[0])
            return self._unary_func(node.trig_func, val)
        raise CalcError('计算元未选择数据类型')

    def _eval_data(self, data):
        """数元接口求值：单值或表格（带位置）。"""
        if data is None or not data.is_defined:
            raise CalcError('数元接口未定义')
        k = data.kind
        if k == InputKind.ROW:
            return self._ctx.get_row(data.index)
        if k == InputKind.COL:
            return self._ctx.get_col(data.index)
        if k == InputKind.CONST:
            return data.value
        if k == InputKind.CLIPBOARD:
            # 剪贴板：解析成 TableValue（一维/二维）
            from PyQt6.QtWidgets import QApplication
            text = QApplication.clipboard().text()
            if not text:
                raise CalcError('剪贴板为空')
            return EvalContext.parse_clipboard(text, self._ctx._by_row)
        if k == InputKind.BLOCK:
            return self.evaluate(data.block)
        if k == InputKind.WHOLE_TABLE:
            return self._ctx.get_whole_table()
        if k == InputKind.RANGE:
            # 范围输入是计数积木原生子数元的特化（10 计划 v2）：
            # 单独求值无意义（需在计数积木内逐行/列处理）
            raise CalcError('范围输入仅用于计数积木（需在计数积木内使用）')
        raise CalcError(f'未知数据定义: {k}')

    # ------------------------------------------------------------------
    # 二元运算（支持广播）
    # ------------------------------------------------------------------

    def _binop(self, op, a, b):
        """对 a, b 应用二元运算：标量直接算；表广播/位置对齐。结果带位置。"""
        a_tbl = isinstance(a, TableValue)
        b_tbl = isinstance(b, TableValue)
        if not a_tbl and not b_tbl:
            return self._apply_binop(op, a, b)
        if a_tbl and b_tbl:
            # 表+表：位置严格对齐（剪贴板一维顺序对齐），逐位置运算
            b_vals = EvalContext._align_tables_values(a, b)
            vals = [self._apply_binop(op, x, y)
                    for x, y in zip(a.values, b_vals)]
            return TableValue(a.positions, vals, a.kind,
                              origin=f'({a.describe()} {op} {b.describe()})')
        if a_tbl:
            return TableValue(a.positions,
                              [self._apply_binop(op, x, b) for x in a.values],
                              a.kind, origin=a.describe())
        return TableValue(b.positions,
                          [self._apply_binop(op, a, y) for y in b.values],
                          b.kind, origin=b.describe())

    def _apply_binop(self, op, x, y):
        if op == '^':
            return x ** y
        if op == 'log':
            if x <= 0 or x == 1:
                raise CalcError(f'对数底数无效: {x}')
            if y <= 0:
                raise CalcError(f'对数真数无效: {y}')
            return math.log(y) / math.log(x)
        if op in OP_FUNCS:
            return OP_FUNCS[op](x, y)
        raise CalcError(f'未知运算符号: {op}')

    # ------------------------------------------------------------------
    # 一元函数（三角）
    # ------------------------------------------------------------------

    def _unary_func(self, name, val):
        tbl = isinstance(val, TableValue)
        if tbl:
            return TableValue(val.positions,
                              [self._apply_unary(name, v) for v in val.values],
                              val.kind, origin=val.describe())
        return self._apply_unary(name, val)

    def _apply_unary(self, name, v):
        if name == 'sin':
            return math.sin(v)
        if name == 'cos':
            return math.cos(v)
        if name == 'tan':
            return math.tan(v)
        if name == 'sec':
            return 1 / math.cos(v)
        if name == 'csc':
            return 1 / math.sin(v)
        if name == 'cot':
            return math.cos(v) / math.sin(v)
        if name == 'arcsin':
            if not (-1 <= v <= 1):
                raise CalcError(f'arcsin 输入越界: {v}')
            return math.asin(v)
        if name == 'arccos':
            if not (-1 <= v <= 1):
                raise CalcError(f'arccos 输入越界: {v}')
            return math.acos(v)
        if name == 'arctan':
            return math.atan(v)
        raise CalcError(f'未知函数: {name}')

    # ------------------------------------------------------------------
    # 链式求值（数学优先级：乘除 > 加减）
    # ------------------------------------------------------------------

    def _eval_chain(self, children):
        """对链式子积木求值：计算元/括号与符号交替，按数学优先级。

        编辑器在链尾恒补一个占位接口（pending_interface），
        用于继续添加——占位不参与求值（跳过）；链中空缺由 validate 拦截。
        """
        # 收集 token 序列：数值 与 符号
        tokens = []  # [(kind, value)]  kind: 'val' | 'op'
        for node in children:
            if node.is_interface:
                continue   # 占位接口（链尾可继续添加处）：不参与求值
            if node.type == BlockType.SYMBOL:
                if node.sym_value is None:
                    raise CalcError('链式表达式中有未定义符号')
                if node.sym_kind == SymKind.OP:
                    tokens.append(('op', node.sym_value))
                else:
                    raise CalcError('链式表达式中不能出现逻辑符号')
            elif node.type in (BlockType.CALC, BlockType.PAREN,
                               BlockType.COUNT, BlockType.CHECK):
                tokens.append(('val', self.evaluate(node)))
            else:
                raise CalcError(f'链式表达式中不能出现 {node.type}')
        if not tokens:
            raise CalcError('表达式为空')
        # 拆出数值序列与符号序列
        vals = [v for k, v in tokens if k == 'val']
        ops = [v for k, v in tokens if k == 'op']
        if not vals:
            raise CalcError('表达式缺少计算元')
        if len(ops) != len(vals) - 1:
            raise CalcError('表达式结构不完整（符号与计算元数量不匹配）')
        # 第一趟：乘除（× ÷ %）
        merged = [vals[0]]
        for i, op in enumerate(ops):
            if op in ('×', '÷', '%'):
                left = merged.pop()
                merged.append(self._binop(op, left, vals[i + 1]))
            else:
                merged.append(vals[i + 1])
        # 第二趟：加减（+ -）——merged 里被乘除合并的项已压缩，
        # 需要用独立索引指向下一个未合并的值
        result = merged[0]
        mi = 1
        for op in ops:
            if op not in ('×', '÷', '%'):
                result = self._binop(op, result, merged[mi])
                mi += 1
            # 乘除已在第一趟处理，跳过（不推进 mi）
        return result

    # ------------------------------------------------------------------
    # 计数 / 检定
    # ------------------------------------------------------------------

    def _eval_count(self, node):
        """计数积木：等式/不等式 左 逻辑符号 右，逐位置检定计数。

        设计记录（09 计划）：
        - 数元可接受 列/行/剪贴板（一维表）/全表输入
        - 一方全表输入 → 另一方只接受单值常数（广播逐格）
        - 表表判定 → 位置严格对齐
        - 剪贴板二维 + 全表数元 → 位置对齐计数，否则拒绝
        左数元范围特化（10 计划 v2）：data.kind==RANGE → 逐行/列计数。
        """
        if len(node.children) != 3:
            raise CalcError('计数积木需 计算元 逻辑符号 计算元')
        left_node = node.children[0]
        d = getattr(left_node, 'data', None)
        if d is not None and d.kind == InputKind.RANGE:
            return self._eval_count_range(node, d)
        left = self.evaluate(left_node)
        logic = node.children[1].sym_value
        right = self.evaluate(node.children[2])
        left_tbl = isinstance(left, TableValue)
        right_tbl = isinstance(right, TableValue)
        if left_tbl and right_tbl:
            # 表+表：位置对齐（剪贴板二维+全表 → 位置对齐；否则拒绝二维）
            if left.is_grid and right.is_grid:
                diff = left.align_positions(right)
                if diff:
                    raise CalcError(diff)
                b_map = dict(zip(right.positions, right.values))
                return sum(1 for p, x in zip(left.positions, left.values)
                           if LOGIC_FUNCS[logic](x, b_map[p]))
            if left.is_grid or right.is_grid:
                # 一方全表、另一方全表(已处理) → 这里只剩一方全表，需常数
                raise CalcError('计数积木：全表输入只能与单值常数比较')
            vals = EvalContext._align_tables_values(left, right)
            return sum(1 for x, y in zip(left.values, vals)
                       if LOGIC_FUNCS[logic](x, y))
        if left_tbl:
            return sum(1 for x in left.values
                       if LOGIC_FUNCS[logic](x, right))
        if right_tbl:
            return sum(1 for y in right.values
                       if LOGIC_FUNCS[logic](left, y))
        return 1 if LOGIC_FUNCS[logic](left, right) else 0

    def _eval_count_range(self, node, d):
        """计数积木·左数元范围特化：对 起始..结尾 逐行/逐列计数。

        每行/列取该行/列纯数据表，与右单值常数按逻辑比较 → 计数值；
        输出**对齐一维表**（10 计划 v2）：
        - 行范围 → 垂直表 kind='col'，positions=[起始行..结尾行]
        - 列范围 → 水平表 kind='row'，positions=[起始列..结尾列]
        """
        if d.range_start is None or d.range_end is None:
            raise CalcError('数元范围未完整定义（起始/结尾）')
        if d.range_start > d.range_end:
            raise CalcError('数元范围顺序错误（起始应 ≤ 结尾）')
        if len(node.children) != 3:
            raise CalcError('计数积木需 计算元 逻辑符号 计算元')
        logic = node.children[1].sym_value
        right = self.evaluate(node.children[2])
        if isinstance(right, TableValue):
            raise CalcError('计数积木范围输入：右侧只接受单值常数')
        positions, vals = [], []
        if d.range_axis == 'row':
            for r in range(d.range_start, d.range_end + 1):
                row = self._ctx.get_row(r)
                positions.append(r)
                vals.append(sum(1 for x in row.values
                                if LOGIC_FUNCS[logic](x, right)))
            return TableValue(positions, vals, 'col', origin='计数(行范围)')
        for c in range(d.range_start, d.range_end + 1):
            col = self._ctx.get_col(c)
            positions.append(c)
            vals.append(sum(1 for x in col.values
                            if LOGIC_FUNCS[logic](x, right)))
        return TableValue(positions, vals, 'row', origin='计数(列范围)')

    def _eval_check(self, node):
        """检定积木：等式/不等式，输出布尔。

        10 计划：接受一维表输入 → 逐元素检定 → 0/1 对齐表
        （单值模式现状：拒绝表格；现在表输入逐元素输出 0/1 表）。
        """
        if len(node.children) != 3:
            raise CalcError('检定积木需 计算元 逻辑符号 计算元')
        left = self.evaluate(node.children[0])
        logic = node.children[1].sym_value
        right = self.evaluate(node.children[2])
        left_tbl = isinstance(left, TableValue)
        right_tbl = isinstance(right, TableValue)
        if not left_tbl and not right_tbl:
            return 1 if LOGIC_FUNCS[logic](left, right) else 0
        # 接受一维表：逐元素检定 → 0/1 对齐表（positions 继承输入表）
        if left_tbl and right_tbl:
            vals = EvalContext._align_tables_values(left, right)
            return TableValue(left.positions,
                              [1 if LOGIC_FUNCS[logic](x, y) else 0
                               for x, y in zip(left.values, vals)],
                              left.kind, origin='检定')
        if left_tbl:
            return TableValue(left.positions,
                              [1 if LOGIC_FUNCS[logic](x, right) else 0
                               for x in left.values],
                              left.kind, origin='检定')
        return TableValue(right.positions,
                          [1 if LOGIC_FUNCS[logic](left, y) else 0
                           for y in right.values],
                          right.kind, origin='检定')
