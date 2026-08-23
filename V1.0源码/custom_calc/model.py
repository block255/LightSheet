"""自定义运算 — 数据模型（积木树形结构）。

积木是嵌套结构，用树形 Node 表示，递归求值天然支持数学优先级。
设计文档见 参考信息库/自定义运算/。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class BlockType(str, Enum):
    """积木类型（6 种）。"""
    CALC = 'calc'        # 计算元（数元/指数/对数/三角）
    SYMBOL = 'symbol'    # 符号元（运算/逻辑）
    PAREN = 'paren'      # 括号（容器）
    COUNT = 'count'      # 计数积木（判定型）
    CHECK = 'check'      # 检定积木（判定型）
    OUTPUT = 'output'    # 输出积木（终点）


class CalcSubtype(str, Enum):
    """计算元子类型。"""
    NUM = 'num'          # 数元
    EXP = 'exp'          # 指数（底数^指数）
    LOG = 'log'          # 对数（log底数(真数)）
    TRIG = 'trig'        # 三角函数


class SymKind(str, Enum):
    """符号元类别。"""
    OP = 'op'            # 运算符号 + - × ÷ %
    LOGIC = 'logic'      # 逻辑符号 = > < >= <= ≠ ≡


class InputKind(str, Enum):
    """数元接口的数据定义方式。"""
    ROW = 'row'          # 输入行（行1）
    COL = 'col'          # 输入列（列A）
    CONST = 'const'      # 常数（单个值，广播）
    CLIPBOARD = 'clipboard'  # 剪贴板（表需方向校验）
    BLOCK = 'block'      # 接入积木（移走原积木）
    WHOLE_TABLE = 'whole_table'  # 整个表格（计数积木专用，09 计划步骤 5）
    RANGE = 'range'      # 范围输入（计数积木原生子数元特化，10 计划 v2：
                         #   对 起始..结尾 逐行/列计数，配合 range_axis/start/end）


class OutputTarget(str, Enum):
    """输出位置。"""
    CLIPBOARD = 'clipboard'
    ROW = 'row'
    COL = 'col'


# 运算符号 → 对应操作
OP_FUNCS = {
    '+': lambda a, b: a + b,
    '-': lambda a, b: a - b,
    '×': lambda a, b: a * b,
    '÷': lambda a, b: a / b,
    '%': lambda a, b: a % b,
}

# 逻辑符号 → 对应判定
LOGIC_FUNCS = {
    '=':  lambda a, b: a == b,
    '>':  lambda a, b: a > b,
    '<':  lambda a, b: a < b,
    '>=': lambda a, b: a >= b,
    '<=': lambda a, b: a <= b,
    '≠':  lambda a, b: a != b,
    '≡':  lambda a, b: a == b,  # 严格相等：值相等（语义同 =，文本层面另行处理）
}

# 三角函数 → math 函数名（引擎层映射）
TRIG_FUNCS = ['sin', 'cos', 'tan', 'sec', 'csc', 'cot',
              'arcsin', 'arccos', 'arctan']


@dataclass
class DataDef:
    """数元接口的数据定义。"""
    kind: Optional[InputKind] = None
    index: Optional[int] = None    # 行/列索引（ROW/COL）
    value: Optional[float] = None  # 常数（CONST）
    block: Optional['BlockNode'] = None  # 接入的积木（BLOCK）
    # 范围输入（RANGE，计数积木原生子数元特化）：对范围内逐行/列计数
    range_axis: Optional[str] = None   # 'row' | 'col'
    range_start: Optional[int] = None  # 起始行/列索引（0-based）
    range_end: Optional[int] = None    # 结尾行/列索引（0-based，含）

    @property
    def is_defined(self) -> bool:
        return self.kind is not None

    @property
    def is_table(self) -> bool:
        """是否为表格形式（行/列/剪贴板表/整个表格/范围）。"""
        return self.kind in (InputKind.ROW, InputKind.COL, InputKind.CLIPBOARD,
                             InputKind.WHOLE_TABLE, InputKind.RANGE)

    @property
    def is_scalar(self) -> bool:
        """是否为单个值（常数）。"""
        return self.kind == InputKind.CONST


@dataclass(eq=False)
class BlockNode:
    """积木节点（树形，多级嵌套）。

    eq=False：== 按对象身份比较（非字段值）。
    原因：dataclass 默认 __eq__ 按所有字段值比较，两个未定义的同类积木
    （如两个 make_check() 胚）字段完全相同会被判相等，导致链式查找
    （in / == / .index()）误判"新积木已在链里"而踢出旧积木。
    积木节点必须用身份（is）区分。
    """
    type: BlockType
    x: float = 0.0
    y: float = 0.0
    state: str = 'normal'   # 'normal' | 'pending_interface' | 'temp_connect'(红色虚线)
    updated_seq: int = 0    # 更新时间戳（重叠层级/执行顺序）

    # 计算元
    calc_subtype: Optional[CalcSubtype] = None
    # 符号元
    sym_kind: Optional[SymKind] = None
    sym_value: Optional[str] = None   # '+', '>', ...
    # 三角函数名（TRIG）
    trig_func: Optional[str] = None   # None = 未定义状态
    # 括号/计数/检定/输出：子积木链（children 列表顺序 = 链式顺序）
    children: list['BlockNode'] = field(default_factory=list)
    # 数元接口（NUM 计算元内嵌）
    data: Optional[DataDef] = None
    # 计数/检定：等式两侧（[左, 逻辑符号, 右] 存在 children 里）
    # 输出积木
    output_target: Optional[OutputTarget] = None
    output_index: Optional[int] = None

    # ------------------------------------------------------------------
    # 便捷判断
    # ------------------------------------------------------------------

    @property
    def is_interface(self) -> bool:
        """是否为待定义接口。"""
        return self.state == 'pending_interface'

    @property
    def is_temp_connect(self) -> bool:
        """是否为临时连接（红色虚线）。"""
        return self.state == 'temp_connect'

    def clone(self, deep: bool = True) -> 'BlockNode':
        """复制积木。默认深拷贝（含嵌套子积木）。"""
        import copy
        return copy.deepcopy(self) if deep else copy.copy(self)


def make_calc_num() -> BlockNode:
    """创建数元计算元（1 个数元接口，未定义）。"""
    return BlockNode(type=BlockType.CALC, calc_subtype=CalcSubtype.NUM,
                     data=DataDef())


def make_calc_exp() -> BlockNode:
    """创建指数计算元（底数/指数 2 个接口）。"""
    n = BlockNode(type=BlockType.CALC, calc_subtype=CalcSubtype.EXP)
    n.children = [make_calc_num(), make_calc_num()]  # [底数, 指数]
    return n


def make_calc_log() -> BlockNode:
    """创建对数计算元（底数/真数 2 个接口）。"""
    n = BlockNode(type=BlockType.CALC, calc_subtype=CalcSubtype.LOG)
    n.children = [make_calc_num(), make_calc_num()]  # [底数, 真数]
    return n


def make_calc_trig() -> BlockNode:
    """创建三角函数计算元（默认 sin + 1 个数元接口）。"""
    n = BlockNode(type=BlockType.CALC, calc_subtype=CalcSubtype.TRIG)
    n.trig_func = 'sin'  # 默认 sin（设计文档 01：默认 sin，可清除定义）
    n.children = [make_calc_num()]
    return n


def make_symbol(op: str, kind: SymKind) -> BlockNode:
    """创建符号元积木。"""
    return BlockNode(type=BlockType.SYMBOL, sym_kind=kind, sym_value=op)


def make_paren() -> BlockNode:
    """创建空括号积木（1 个计算元接口，待填入）。"""
    n = BlockNode(type=BlockType.PAREN)
    n.children = [BlockNode(type=BlockType.CALC,
                            state='pending_interface')]  # 空接口
    return n


def make_count() -> BlockNode:
    """创建计数积木胚：左计算元(数元) + 逻辑符号 + 右计算元(数元)，均未定义。"""
    n = BlockNode(type=BlockType.COUNT)
    n.children = [
        BlockNode(type=BlockType.CALC, calc_subtype=CalcSubtype.NUM,
                  data=DataDef()),
        BlockNode(type=BlockType.SYMBOL),
        BlockNode(type=BlockType.CALC, calc_subtype=CalcSubtype.NUM,
                  data=DataDef()),
    ]
    return n


def make_check() -> BlockNode:
    """创建检定积木胚：左计算元(数元) + 逻辑符号 + 右计算元(数元)，均未定义。"""
    n = BlockNode(type=BlockType.CHECK)
    n.children = [
        BlockNode(type=BlockType.CALC, calc_subtype=CalcSubtype.NUM,
                  data=DataDef()),
        BlockNode(type=BlockType.SYMBOL),
        BlockNode(type=BlockType.CALC, calc_subtype=CalcSubtype.NUM,
                  data=DataDef()),
    ]
    return n


def make_output() -> BlockNode:
    """创建输出积木（1 个计算元接口 + 输出位置未选）。"""
    n = BlockNode(type=BlockType.OUTPUT)
    n.children = [BlockNode(type=BlockType.CALC,
                            state='pending_interface')]  # 空接口
    n.output_target = None
    return n
