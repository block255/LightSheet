"""公式求值引擎（Formula Engine）— 我们软件自己计算 Excel 公式。

定位（互译 P3，2026-08-28）：
  1. 外来 xlsx 公式格 → 引擎算出结果显示（读方向融入统一条目）
  2. 我们脚本翻译的公式（P2）→ 引擎算出结果（写公式后我们也能显示）
纯 Python，桌面/Web 同源共享；坐标解析复用 formula_translate.py。

三段式：tokenizer（词法）→ parser（AST）→ evaluator（求值）。
表值语义对齐积木引擎：区域 → TableValue，标量与表广播，表与表按位置对齐。
错误值不抛异常，标记传播（显示 #DIV/0! 等）。
"""
from __future__ import annotations

import re
from typing import Optional

from models.formula_translate import (
    parse_cell_ref, parse_range_ref, col_letter_to_index, index_to_col_letter,
)


# ----------------------------------------------------------------------
# 错误值（不抛异常，求值结果可为错误标记，参与传播）
# ----------------------------------------------------------------------

class ErrorValue:
    """Excel 错误值标记（#DIV/0! 等）。"""

    _CODES = {'#DIV/0!', '#VALUE!', '#REF!', '#NAME?', '#N/A', '#NUM!', '#NULL!'}

    def __init__(self, code: str):
        self.code = code if code in self._CODES else '#VALUE!'

    def __str__(self):
        return self.code

    def __repr__(self):
        return f'ErrorValue({self.code})'

    def __eq__(self, other):
        return isinstance(other, ErrorValue) and other.code == self.code

    def __hash__(self):
        return hash(self.code)


ERR_DIV0 = ErrorValue('#DIV/0!')
ERR_VALUE = ErrorValue('#VALUE!')
ERR_REF = ErrorValue('#REF!')
ERR_NAME = ErrorValue('#NAME?')
ERR_NA = ErrorValue('#N/A')
ERR_NUM = ErrorValue('#NUM!')


def is_error(v) -> bool:
    return isinstance(v, ErrorValue)


# ----------------------------------------------------------------------
# 表值（区域求值结果：二维网格，对齐广播语义）
# ----------------------------------------------------------------------

class TableValue:
    """区域值：rows 二维列表。is_grid=True 表示二维网格；否则为一维方向表。

    对齐语义（对齐积木引擎 _align_tables_values 思路）：
    - 一维行表（1×N）与一维列表（N×1）可对齐（互为转置方向）
    - 尺寸完全一致的表格按位置逐元素
    - 尺寸不一致 → #VALUE!
    """

    def __init__(self, rows: list[list], is_grid: bool = False):
        self.rows = rows
        self.is_grid = is_grid

    @property
    def width(self) -> int:
        return max((len(r) for r in self.rows), default=0)

    @property
    def height(self) -> int:
        return len(self.rows)

    def as_scalar(self):
        """单格表值 → 标量（多格返回 None，调用方决定）。"""
        if self.height == 1 and self.width == 1 and self.rows:
            return self.rows[0][0] if self.rows[0] else None
        return None

    def __repr__(self):
        return f'TableValue({self.rows!r})'


def _scalar_of(v):
    """TableValue 单格 → 标量；其余原样返回。"""
    if isinstance(v, TableValue):
        s = v.as_scalar()
        if s is not None:
            return s
        return v
    return v


# ----------------------------------------------------------------------
# AST 节点
# ----------------------------------------------------------------------

class Num:
    def __init__(self, value): self.value = value
    def __repr__(self): return f'Num({self.value})'


class Str:
    def __init__(self, value): self.value = value
    def __repr__(self): return f'Str({self.value!r})'


class Ref:
    """单格引用。sheet=None 表示当前表。"""
    def __init__(self, sheet, r, c): self.sheet, self.r, self.c = sheet, r, c
    def __repr__(self): return f'Ref({self.sheet},{self.r},{self.c})'


class Range:
    """区域引用。sheet=None 表示当前表；整列/整行用大边界标记。"""
    def __init__(self, sheet, r1, c1, r2, c2):
        self.sheet, self.r1, self.c1, self.r2, self.c2 = sheet, r1, c1, r2, c2
    def __repr__(self): return f'Range({self.sheet},{self.r1},{self.c1},{self.r2},{self.c2})'


class Func:
    def __init__(self, name, args): self.name, self.args = name, args
    def __repr__(self): return f'Func({self.name},{self.args})'


class Binary:
    def __init__(self, op, left, right): self.op, self.left, self.right = op, left, right
    def __repr__(self): return f'Binary({self.op},{self.left},{self.right})'


class Unary:
    def __init__(self, op, operand): self.op, self.operand = op, operand
    def __repr__(self): return f'Unary({self.op},{self.operand})'


# ----------------------------------------------------------------------
# 词法（tokenizer）
# ----------------------------------------------------------------------

# 数字：12 / 3.5 / 1e3
_NUM_RE = re.compile(r'\d+(?:\.\d+)?(?:[eE][+-]?\d+)?')
# 引用/区域/函数名：字母开头
_REF_RE = re.compile(
    r"(?:(?P<sheet>[A-Za-z_\u4e00-\u9fff][\w\u4e00-\u9fff]*))?"
    r"!(?P<body>(?:[A-Za-z]+\d+:[A-Za-z]+\d+)|(?:[A-Za-z]+:[A-Za-z]+)"
    r"|(?:\d+:\d+)|(?:[A-Za-z]+\d+))"
)
_REF_NO_SHEET_RE = re.compile(
    r"(?P<body>(?:[A-Za-z]+\d+:[A-Za-z]+\d+)|(?:[A-Za-z]+:[A-Za-z]+)"
    r"|(?:\d+:\d+)|(?:[A-Za-z]+\d+))"
)
_OPS = {'+', '-', '*', '/', '^', '%', '&', '=', '<', '>', '<=', '>=', '<>'}
# 函数名（已知集合，用于区分 引用 vs 函数）
_FUNC_NAMES = {
    'SUM', 'AVERAGE', 'COUNT', 'COUNTA', 'MAX', 'MIN', 'VAR', 'STDEV',
    'MEDIAN', 'PERCENTILE.INC', 'PERCENTILE', 'MODE.SNGL', 'COUNTIF', 'SQRT', 'LOG10',
    'ABS', 'ROUND', 'INT', 'MOD', 'POWER', 'IF', 'AND', 'OR', 'NOT',
    'CONCATENATE', 'LEFT', 'RIGHT', 'MID', 'LEN', 'VALUE', 'SIN', 'COS',
    'TAN', 'ASIN', 'ACOS', 'ATAN', 'RADIANS', 'DEGREES',
}


class Token:
    __slots__ = ('kind', 'value', 'pos')

    def __init__(self, kind, value, pos):
        self.kind = kind    # 'num'/'str'/'ref'/'range'/'func'/'op'/'lparen'/'rparen'/'comma'/'percent'
        self.value = value
        self.pos = pos

    def __repr__(self):
        return f'Token({self.kind},{self.value!r}@{self.pos})'


def _parse_ref_body(body: str) -> tuple | None:
    """A1 / A1:B3 / A:A / 1:1 → (单格|区域) 描述（0-based）。"""
    body = body.replace(' ', '')
    if ':' in body:
        left, right = body.split(':')
        if left.isalpha() and right.isalpha():
            c = col_letter_to_index(left)
            return ('range', None, 0, c, 10**6, c)
        if left.isdigit() and right.isdigit():
            return ('range', None, int(left) - 1, 0, int(right) - 1, 10**6)
        rng = parse_range_ref(body)
        if rng:
            return ('range', None, *rng)
        return None
    p = parse_cell_ref(body)
    if p:
        return ('cell', None, p[0], p[1])
    return None


def tokenize(text: str) -> list[Token]:
    """公式文本（含或不含前导 =）→ token 列表。失败抛 ValueError。"""
    s = text.strip()
    if s.startswith('='):
        s = s[1:]
    tokens: list[Token] = []
    i = 0
    n = len(s)
    while i < n:
        ch = s[i]
        if ch in ' \t':
            i += 1
            continue
        # 字符串字面量（双引号）
        if ch == '"':
            j = s.find('"', i + 1)
            if j < 0:
                raise ValueError('字符串未闭合')
            tokens.append(Token('str', s[i + 1:j], i))
            i = j + 1
            continue
        # 数字
        m = _NUM_RE.match(s, i)
        if m and (i == 0 or (not s[i - 1].isalpha() and s[i - 1] != '_')):
            tokens.append(Token('num', float(m.group()), i))
            i = m.end()
            continue
        # 运算符（含双字符 <= >= <>）
        two = s[i:i + 2]
        if two in ('<=', '>=', '<>'):
            tokens.append(Token('op', two, i))
            i += 2
            continue
        if ch in _OPS:
            tokens.append(Token('op', ch, i))
            i += 1
            continue
        if ch == '(':
            tokens.append(Token('lparen', '(', i))
            i += 1
            continue
        if ch == ')':
            tokens.append(Token('rparen', ')', i))
            i += 1
            continue
        if ch == ',':
            tokens.append(Token('comma', ',', i))
            i += 1
            continue
        # 引用/函数名（字母开头）
        if ch.isalpha() or ch == '_' or ord(ch) > 127:
            # 先试函数名：字母数字序列后跟 '(' 即函数调用
            # （未知函数放行，求值时返回 #NAME?；避免 LOG10 被当引用）
            # 含点号（如 PERCENTILE.INC）
            j = i
            while j < n and (s[j].isalnum() or s[j] == '_' or s[j] == '.'):
                j += 1
            name = s[i:j].upper()
            if j < n and s[j] == '(':
                tokens.append(Token('func', name, i))
                i = j
                continue
            m2 = _REF_RE.match(s, i)
            if m2:
                sheet = m2.group('sheet') or None
                body = m2.group('body')
                parsed = _parse_ref_body(body)
                if parsed is None:
                    raise ValueError(f'无效引用 {body}')
                kind = 'cell' if parsed[0] == 'cell' else 'range'
                if kind == 'cell':
                    tokens.append(Token('cell', Ref(sheet, parsed[2], parsed[3]), i))
                else:
                    tokens.append(Token('range', Range(sheet, parsed[2], parsed[3], parsed[4], parsed[5]), i))
                i = m2.end()
                continue
            m3 = _REF_NO_SHEET_RE.match(s, i)
            if m3:
                parsed = _parse_ref_body(m3.group('body'))
                if parsed is None:
                    raise ValueError('无效引用')
                if parsed[0] == 'cell':
                    tokens.append(Token('cell', Ref(None, parsed[2], parsed[3]), i))
                else:
                    tokens.append(Token('range', Range(None, parsed[2], parsed[3], parsed[4], parsed[5]), i))
                i = m3.end()
                continue
            raise ValueError(f'无法识别 {s[i:j]}')
        raise ValueError(f'无法识别字符 {ch!r} 于位置 {i}')
    return tokens


# ----------------------------------------------------------------------
# 语法（parser，递归下降）
# ----------------------------------------------------------------------

class Parser:
    def __init__(self, tokens: list[Token]):
        self.tokens = tokens
        self.idx = 0

    def peek(self) -> Optional[Token]:
        return self.tokens[self.idx] if self.idx < len(self.tokens) else None

    def next(self) -> Token:
        t = self.peek()
        if t is None:
            raise ValueError('公式意外结束')
        self.idx += 1
        return t

    def expect(self, kind: str):
        t = self.next()
        if t.kind != kind:
            raise ValueError(f'期望 {kind}，得到 {t.kind}')
        return t

    def parse(self):
        expr = self.expr()
        if self.peek() is not None:
            raise ValueError(f'多余内容: {self.peek()}')
        return expr

    # 比较/逻辑层（= < > <= >= <>）
    def expr(self):
        left = self.additive()
        t = self.peek()
        while t and t.kind == 'op' and t.value in ('=', '<', '>', '<=', '>=', '<>'):
            self.next()
            right = self.additive()
            left = Binary(t.value, left, right)
            t = self.peek()
        return left

    # 加减
    def additive(self):
        left = self.multiplicative()
        t = self.peek()
        while t and t.kind == 'op' and t.value in ('+', '-', '&'):
            self.next()
            right = self.multiplicative()
            left = Binary(t.value, left, right)
            t = self.peek()
        return left

    # 乘除
    def multiplicative(self):
        left = self.unary()
        t = self.peek()
        while t and t.kind == 'op' and t.value in ('*', '/', '^'):
            self.next()
            right = self.unary()
            left = Binary(t.value, left, right)
            t = self.peek()
        return left

    def unary(self):
        t = self.peek()
        if t and t.kind == 'op' and t.value in ('+', '-'):
            self.next()
            return Unary(t.value, self.unary())
        return self.primary()

    def primary(self):
        t = self.next()
        if t.kind == 'num':
            return Num(t.value)
        if t.kind == 'str':
            return Str(t.value)
        if t.kind in ('cell', 'range'):
            node = t.value
            # 后缀百分号（A1%）
            if self.peek() and self.peek().kind == 'op' and self.peek().value == '%':
                self.next()
                return Binary('%', node, Num(100))
            return node
        if t.kind == 'func':
            self.expect('lparen')
            args = []
            if self.peek() and self.peek().kind != 'rparen':
                args.append(self.expr())
                while self.peek() and self.peek().kind == 'comma':
                    self.next()
                    args.append(self.expr())
            self.expect('rparen')
            return Func(t.value, args)
        if t.kind == 'lparen':
            inner = self.expr()
            self.expect('rparen')
            if self.peek() and self.peek().kind == 'op' and self.peek().value == '%':
                self.next()
                return Binary('%', inner, Num(100))
            return inner
        raise ValueError(f'意外的 {t.kind} ({t.value})')


def parse_formula(text: str):
    """公式文本 → AST。"""
    return Parser(tokenize(text)).parse()


# ----------------------------------------------------------------------
# 求值（evaluator）
# ----------------------------------------------------------------------

class EvalContext:
    """求值上下文：表格模型 + 当前 sheet（支持跨表引用）。

    model 需提供：value(r,c) / row_total / col_total
    （对齐积木引擎接口，TableData / SpreadsheetModel 均可）。

    sheet_models（互译跨表，可选）：{sheet名: model} 全表模型表；
    Ref/Range 带 sheet 时从对应模型取值（缺省用当前 model）。
    """

    def __init__(self, model, sheet: str = '', sheet_models: dict = None):
        self.model = model
        self.sheet = sheet
        self.sheet_models = sheet_models or {}

    def _model_for(self, ref_sheet):
        """引用目标模型：带 sheet 且在表内 → 对应模型；否则当前 model。"""
        if ref_sheet and ref_sheet != self.sheet \
                and ref_sheet in self.sheet_models:
            return self.sheet_models[ref_sheet]
        return self.model

    def cell_value(self, r: int, c: int, ref_sheet=None):
        try:
            return self._model_for(ref_sheet).value(r, c)
        except Exception:
            return None

    def cell_exists(self, r: int, c: int, ref_sheet=None) -> bool:
        try:
            m = self._model_for(ref_sheet)
            rt = m.row_total
            ct = m.col_total
            return 0 <= r < rt and 0 <= c < ct
        except Exception:
            return True

    # ------------------------------------------------------------------
    # 区域取值
    # ------------------------------------------------------------------

    def range_table(self, rng: Range) -> TableValue:
        """区域 → TableValue（大边界 10**6 按模型尺寸裁剪；跨表按 rng.sheet）。"""
        m = self._model_for(rng.sheet)
        r1, c1 = rng.r1, rng.c1
        r2 = min(rng.r2, m.row_total - 1) if rng.r2 >= 10**5 else rng.r2
        c2 = min(rng.c2, m.col_total - 1) if rng.c2 >= 10**5 else rng.c2
        if r1 > r2 or c1 > c2:
            return TableValue([])
        rows = []
        for r in range(r1, r2 + 1):
            row = []
            for c in range(c1, c2 + 1):
                row.append(self._norm(m.value(r, c)))
            rows.append(row)
        is_grid = (r2 - r1 > 0) and (c2 - c1 > 0)
        return TableValue(rows, is_grid)

    def ref_value(self, ref: Ref):
        """单格引用 → 值（越界 → #REF!；跨表按 ref.sheet）。"""
        m = self._model_for(ref.sheet)
        try:
            if not (0 <= ref.r < m.row_total and 0 <= ref.c < m.col_total):
                return ERR_REF
        except Exception:
            pass
        return self._norm(m.value(ref.r, ref.c))

    @staticmethod
    def _norm(v):
        """单元格原始值 → 数字/文本/None。"""
        if v is None:
            return None
        if isinstance(v, (int, float)):
            return float(v) if not isinstance(v, bool) else (1.0 if v else 0.0)
        s = str(v).strip()
        if s == '':
            return None
        try:
            return float(s)
        except ValueError:
            return s

    # ------------------------------------------------------------------
    # 二元运算（表/标量，对齐广播）
    # ------------------------------------------------------------------

    def binary(self, op, lv, rv):
        if is_error(lv):
            return lv
        if is_error(rv):
            return rv
        lt = isinstance(lv, TableValue)
        rt = isinstance(rv, TableValue)
        if lt and rt:
            return self._align_op(op, lv, rv)
        if lt:
            return self._table_scalar(op, lv, _scalar_of(rv))
        if rt:
            return self._table_scalar(op, rv, _scalar_of(lv), swap=True)
        return self._scalar_op(op, lv, rv)

    @staticmethod
    def _align_op(op, a: TableValue, b: TableValue):
        """表与表：按位置逐元素；尺寸不匹配 → #VALUE!（一维可转置对齐）。"""
        if a.height == b.height and a.width == b.width \
                and a.height > 0 and a.width > 0:
            rows = [[EvalContext._scalar_op(op, a.rows[i][j], b.rows[i][j])
                     for j in range(a.width)] for i in range(a.height)]
            if any(is_error(v) for row in rows for v in row):
                return ERR_VALUE
            return TableValue(rows, a.is_grid or b.is_grid)
        # 一维表转置对齐（行表 vs 列表）
        if a.height == 1 and b.width == 1 and a.width == b.height:
            rows = [[EvalContext._scalar_op(op, a.rows[0][j], b.rows[j][0])
                     for j in range(a.width)]]
            return TableValue(rows)
        if b.height == 1 and a.width == 1 and b.width == a.height:
            rows = [[EvalContext._scalar_op(op, a.rows[i][0], b.rows[0][i])
                     for i in range(a.height)]]
            return TableValue(rows)
        return ERR_VALUE

    @staticmethod
    def _table_scalar(op, t: TableValue, s, swap=False):
        """表与标量：广播（每元素与标量运算）。"""
        rows = []
        for row in t.rows:
            out = []
            for v in row:
                out.append(EvalContext._scalar_op(op, s, v) if swap
                           else EvalContext._scalar_op(op, v, s))
            rows.append(out)
        return TableValue(rows, t.is_grid)

    @staticmethod
    def _scalar_op(op, a, b):
        """标量二元运算（含文本连接 &、比较、百分比 %）。"""
        if op == '&':
            return _as_text(a) + _as_text(b)
        if op == '%':
            return _as_num(a) / _as_num(b)
        if isinstance(a, str) or isinstance(b, str):
            # 数字与文本比较：文本参与按数值尝试
            if op in ('=', '<>'):
                if isinstance(a, str) and isinstance(b, str):
                    return a == b if op == '=' else a != b
                return False if op == '=' else True
            return ERR_VALUE
        a, b = _as_num(a), _as_num(b)
        if a is None or b is None:
            if op in ('=', '<>'):
                na, nb = a is None, b is None
                return (na and nb) if op == '=' else (na != nb)
            return ERR_VALUE
        try:
            if op == '+':
                return a + b
            if op == '-':
                return a - b
            if op == '*':
                return a * b
            if op == '/':
                if b == 0:
                    return ERR_DIV0
                return a / b
            if op == '^':
                return a ** b
            if op == '=':
                return a == b
            if op == '<>':
                return a != b
            if op == '<':
                return a < b
            if op == '>':
                return a > b
            if op == '<=':
                return a <= b
            if op == '>=':
                return a >= b
        except (ZeroDivisionError, ValueError, OverflowError):
            return ERR_NUM
        return ERR_VALUE


def _as_num(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).strip())
    except (ValueError, TypeError):
        return None


def _as_text(v):
    if v is None:
        return ''
    if isinstance(v, float) and v == int(v):
        return str(int(v))
    return str(v)


# ----------------------------------------------------------------------
# 函数库（19 个，按我们脚本体系）
# ----------------------------------------------------------------------

def _args_values(ctx: EvalContext, args) -> list:
    """函数实参 → 值列表（Ref/Range 取值为标量或表值）。"""
    return [eval_ast(a, ctx) for a in args]


def _flatten(v) -> list:
    """标量/表值 → 值平铺列表（聚合函数用，跳过 None）。"""
    if isinstance(v, TableValue):
        out = []
        for row in v.rows:
            for x in row:
                if x is not None:
                    out.append(x)
        return out
    if v is None:
        return []
    return [v]


def _nums_of(v) -> list:
    """只取数值（COUNT/SUM 语义：文本忽略）。"""
    return [x for x in _flatten(v)
            if isinstance(x, (int, float)) and not isinstance(x, bool)]


def _func_aggregate(name, vals: list):
    """聚合函数：输入为实参值列表（每个可为标量/表值）。"""
    nums = []
    for v in vals:
        nums.extend(_nums_of(v))
    if name == 'SUM':
        return sum(nums) if nums else 0.0
    if name == 'AVERAGE':
        return sum(nums) / len(nums) if nums else ERR_DIV0
    if name == 'COUNT':
        return float(len(nums))
    if name == 'COUNTA':
        return float(sum(1 for v in vals for _ in _flatten(v)))
    if name == 'MAX':
        return max(nums) if nums else 0.0
    if name == 'MIN':
        return min(nums) if nums else 0.0
    if name == 'MEDIAN':
        if not nums:
            return ERR_DIV0
        s = sorted(nums)
        n = len(s)
        if n % 2:
            return s[n // 2]
        return (s[n // 2 - 1] + s[n // 2]) / 2
    if name == 'VAR':
        return _variance(nums, sample=True) if len(nums) >= 2 else ERR_DIV0
    if name == 'STDEV':
        return _variance(nums, sample=True) ** 0.5 if len(nums) >= 2 else ERR_DIV0
    return ERR_NAME


def _variance(nums, sample=True):
    m = sum(nums) / len(nums)
    d = sum((x - m) ** 2 for x in nums)
    return d / (len(nums) - 1 if sample else len(nums))


def _parse_condition(crit: str) -> tuple[str, object]:
    """COUNTIF 条件解析：">3" / "<>5" / ">=3" / "abc" → (比较符, 操作数)。"""
    crit = crit.strip()
    for op in ('<=', '>=', '<>'):
        if crit.startswith(op):
            rest = crit[len(op):].strip()
            return op, _as_num(rest)
    for op in ('=', '<', '>'):
        if crit.startswith(op):
            rest = crit[len(op):].strip()
            return op, _as_num(rest)
    return '=', _as_num(crit) if _as_num(crit) is not None else crit


def _cond_match(x, op, operand) -> bool:
    """单元格值 vs 条件。数值比较；文本仅 '=' 完全相等。"""
    if isinstance(x, (int, float)):
        if operand is None:
            return False
        n = float(x)
        if op == '=':
            return n == operand
        if op == '<>':
            return n != operand
        if op == '<':
            return n < operand
        if op == '>':
            return n > operand
        if op == '<=':
            return n <= operand
        if op == '>=':
            return n >= operand
        return False
    # 文本：只有 '=' 且操作数是文本时才完全相等
    return op == '=' and not isinstance(operand, (int, float)) \
        and str(x) == str(operand)


def _func_eval(name: str, args: list, ctx: EvalContext):
    """19 个函数求值。"""
    vals = _args_values(ctx, args)

    if name in ('SUM', 'AVERAGE', 'COUNT', 'COUNTA', 'MAX', 'MIN',
                'VAR', 'STDEV', 'MEDIAN'):
        return _func_aggregate(name, vals)

    if name == 'COUNTIF':
        if len(args) < 2:
            return ERR_NAME
        rng_v = eval_ast(args[0], ctx)
        crit = _scalar_of(eval_ast(args[1], ctx))
        # 条件解析：">3"、"<>5"、">=3"、无前缀 = 相等；文本无前缀 = 完全相等
        ccrit = _as_text(crit)
        op, operand = _parse_condition(ccrit)
        count = 0
        for x in _flatten(rng_v):
            if x is None:
                continue
            if _cond_match(x, op, operand):
                count += 1
        return float(count)

    # 众数（默认模式：数值比较取众数；多个并列取第一个；全单次 → #N/A）
    if name == 'MODE.SNGL':
        arr = _nums_of(vals[0])
        if not arr:
            return ERR_NA
        counts: dict = {}
        for x in arr:
            counts[x] = counts.get(x, 0) + 1
        mx = max(counts.values())
        if mx == 1:
            return ERR_NA   # 无众数（每个值只出现一次）
        for x in arr:
            if counts[x] == mx:
                return x    # 并列众数取第一个
        return ERR_NA

    # 分位数（与分位数脚本算法一致：pos = k*(n-1) 线性插值）
    if name in ('PERCENTILE.INC', 'PERCENTILE'):
        if len(args) < 2:
            return ERR_NAME
        arr = _nums_of(vals[0])
        k = _as_num(_scalar_of(vals[1]))
        if not arr or k is None or not (0 <= k <= 1):
            return ERR_DIV0
        s = sorted(arr)
        n = len(s)
        pos = k * (n - 1)
        lo = int(pos)
        hi = lo + 1 if lo < n - 1 else lo
        if lo == hi:
            return s[lo]
        frac = pos - lo
        return s[lo] + (s[hi] - s[lo]) * frac

    # 数学（标量或逐元素表）
    if name in ('SQRT', 'LOG10', 'ABS', 'ROUND', 'INT', 'SIN', 'COS', 'TAN',
                'ASIN', 'ACOS', 'ATAN', 'RADIANS', 'DEGREES'):
        if len(args) != 1:
            return ERR_NAME
        v = vals[0]

        def _f(x):
            if x is None:
                return None
            n = _as_num(x)
            if n is None:
                return ERR_VALUE
            try:
                if name == 'SQRT':
                    return n ** 0.5 if n >= 0 else ERR_NUM
                if name == 'LOG10':
                    return _log10(n) if n > 0 else ERR_NUM
                if name == 'ABS':
                    return abs(n)
                if name == 'ROUND':
                    return round(n)
                if name == 'INT':
                    return int(n)
                if name == 'SIN':
                    return _sin(n)
                if name == 'COS':
                    return _cos(n)
                if name == 'TAN':
                    return _tan(n)
                if name == 'ASIN':
                    return _asin(n)
                if name == 'ACOS':
                    return _acos(n)
                if name == 'ATAN':
                    return _atan(n)
                if name == 'RADIANS':
                    return n * 3.141592653589793 / 180
                if name == 'DEGREES':
                    return n * 180 / 3.141592653589793
            except (ValueError, OverflowError):
                return ERR_NUM
            return ERR_VALUE
        return _map_value(v, _f)

    if name == 'MOD':
        if len(args) != 2:
            return ERR_NAME
        a, b = _as_num(_scalar_of(vals[0])), _as_num(_scalar_of(vals[1]))
        if a is None or b is None:
            return ERR_VALUE
        if b == 0:
            return ERR_DIV0
        return a % b

    if name == 'POWER':
        if len(args) != 2:
            return ERR_NAME
        a, b = _as_num(_scalar_of(vals[0])), _as_num(_scalar_of(vals[1]))
        if a is None or b is None:
            return ERR_VALUE
        return a ** b

    if name == 'IF':
        if len(args) < 2:
            return ERR_NAME
        cond = _scalar_of(vals[0])
        cond_ok = False
        if isinstance(cond, (int, float)):
            cond_ok = cond != 0
        elif isinstance(cond, str):
            cond_ok = cond.lower() in ('true', '1')
        return eval_ast(args[1], ctx) if cond_ok \
            else (eval_ast(args[2], ctx) if len(args) > 2 else False)

    if name == 'AND':
        return all(bool(_scalar_of(v)) for v in vals) if vals else ERR_NAME
    if name == 'OR':
        return any(bool(_scalar_of(v)) for v in vals) if vals else ERR_NAME
    if name == 'NOT':
        return not bool(_scalar_of(vals[0])) if vals else ERR_NAME

    # 文本
    if name == 'CONCATENATE':
        return ''.join(_as_text(_scalar_of(v)) for v in vals)
    if name == 'LEN':
        return float(len(_as_text(_scalar_of(vals[0])))) if vals else ERR_NAME
    if name == 'VALUE':
        if not vals:
            return ERR_NAME
        n = _as_num(_scalar_of(vals[0]))
        return n if n is not None else ERR_VALUE
    if name == 'LEFT':
        s = _as_text(_scalar_of(vals[0]))
        k = int(_as_num(_scalar_of(vals[1]))) if len(vals) > 1 else 1
        return s[:max(k, 0)]
    if name == 'RIGHT':
        s = _as_text(_scalar_of(vals[0]))
        k = int(_as_num(_scalar_of(vals[1]))) if len(vals) > 1 else 1
        return s[-max(k, 0):] if k > 0 else ''
    if name == 'MID':
        s = _as_text(_scalar_of(vals[0]))
        start = int(_as_num(_scalar_of(vals[1]))) - 1
        k = int(_as_num(_scalar_of(vals[2]))) if len(vals) > 2 else len(s)
        return s[start:start + max(k, 0)]

    return ERR_NAME


def _map_value(v, f):
    """标量或表值 → 逐元素映射。"""
    if isinstance(v, TableValue):
        return TableValue([[f(x) for x in row] for row in v.rows], v.is_grid)
    return f(v)


def _log10(n):
    import math
    return math.log10(n)


def _sin(n):
    import math
    return math.sin(n)


def _cos(n):
    import math
    return math.cos(n)


def _tan(n):
    import math
    return math.tan(n)


def _asin(n):
    import math
    return math.asin(n)


def _acos(n):
    import math
    return math.acos(n)


def _atan(n):
    import math
    return math.atan(n)


# ----------------------------------------------------------------------
# 求值入口
# ----------------------------------------------------------------------

def eval_ast(node, ctx: EvalContext):
    """AST + 上下文 → 值。"""
    if isinstance(node, Num):
        return node.value
    if isinstance(node, Str):
        return node.value
    if isinstance(node, Ref):
        return ctx.ref_value(node)
    if isinstance(node, Range):
        return ctx.range_table(node)
    if isinstance(node, Func):
        if node.name not in _FUNC_NAMES:
            return ERR_NAME
        return _func_eval(node.name, node.args, ctx)
    if isinstance(node, Binary):
        lv = eval_ast(node.left, ctx)
        rv = eval_ast(node.right, ctx)
        return ctx.binary(node.op, lv, rv)
    if isinstance(node, Unary):
        v = eval_ast(node.operand, ctx)
        if is_error(v):
            return v
        if isinstance(v, TableValue):
            return TableValue([[_unary(op, x) for x in row] for row in v.rows],
                              v.is_grid)
        return _unary(node.op, v)
    return ERR_VALUE


def _unary(op, v):
    if op == '-':
        n = _as_num(v)
        return -n if n is not None else ERR_VALUE
    return v


def evaluate(formula: str, ctx: EvalContext):
    """公式文本（含 =）→ 值（标量/表值/错误值）。解析失败抛 ValueError。"""
    ast = parse_formula(formula)
    return eval_ast(ast, ctx)


# ----------------------------------------------------------------------
# 相对引用模板展开（P2 翻译输出用）
# ----------------------------------------------------------------------

def expand_template(template: str, out_r: int, out_c: int,
                    base_r: int = 0, base_c: int = 0) -> str:
    """把公式模板中的 {r}/{c} 占位替换为相对输出位置的实际坐标。

    template: 如 '=A{r}+B{r}'（{r} = 行号跟随输出行，{c} = 列号跟随输出列）
    out_r/out_c: 目标输出格（0-based）
    base_r/base_c: 模板基准格（模板录制时的参考格，默认 0,0）
    语义：占位替换为 base + 偏移（out - 基准）→ 相对引用跟随。
    """
    text = template
    text = text.replace('{r}', str(out_r - base_r + 1))
    text = text.replace('{c}', index_to_col_letter(out_c - base_c))
    return text


# 便捷：整列/整行输出的模板生成（P2 翻译用）
def column_template(sheet_letter: str, op: str = '+') -> str:
    """列引用模板：'=A{r}+B{r}' 形式（行号占位）。"""
    return f'={sheet_letter}{{r}}{op}'
