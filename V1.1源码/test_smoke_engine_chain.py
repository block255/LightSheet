# 引擎链式求值回归：数学优先级组合
import sys
sys.path.insert(0, r'D:\Cloude Code\自制表格软件\代码输出库\源码')
from models.table_data import TableData
from custom_calc.model import (BlockNode, BlockType, CalcSubtype, SymKind,
                               InputKind, DataDef, make_calc_num, make_symbol)
from custom_calc.engine import EvalContext, Evaluator


def make_chain(items):
    """items: [('v', 5), ('op', '+'), ('v', 2), ('op', '×'), ('v', 3)]"""
    children = []
    for kind, val in items:
        if kind == 'v':
            n = make_calc_num()
            n.data = DataDef(kind=InputKind.CONST, value=val)
            children.append(n)
        else:
            children.append(make_symbol(val, SymKind.OP))
    # 链尾补接口
    children.append(BlockNode(type=BlockType.CALC, state='pending_interface'))
    paren = BlockNode(type=BlockType.PAREN)
    paren.children = children
    return paren


def ev(items):
    t = TableData()
    paren = make_chain(items)
    ctx = EvalContext(t, '以列为单位')
    return Evaluator(ctx)._eval_chain(paren.children)


def check(name, items, expected):
    got = ev(items)
    ok = abs(got - expected) < 1e-9
    print(f'{"PASS" if ok else "FAIL"}: {name} = {got} (期望 {expected})')
    if not ok:
        raise AssertionError(name)


# 用户崩溃场景：a × b + c（乘除合并后加）
check('2×3+4', [('v', 2), ('op', '×'), ('v', 3), ('op', '+'), ('v', 4)], 10)
check('2+3×4', [('v', 2), ('op', '+'), ('v', 3), ('op', '×'), ('v', 4)], 14)
check('2×3×4', [('v', 2), ('op', '×'), ('v', 3), ('op', '×'), ('v', 4)], 24)
check('2+3+4', [('v', 2), ('op', '+'), ('v', 3), ('op', '+'), ('v', 4)], 9)
check('2+3×4+5', [('v', 2), ('op', '+'), ('v', 3), ('op', '×'),
                  ('v', 4), ('op', '+'), ('v', 5)], 19)
check('2×3+4×5', [('v', 2), ('op', '×'), ('v', 3), ('op', '+'),
                  ('v', 4), ('op', '×'), ('v', 5)], 26)
check('2+3×4×5', [('v', 2), ('op', '+'), ('v', 3), ('op', '×'),
                  ('v', 4), ('op', '×'), ('v', 5)], 62)
check('2×3+4+5×6', [('v', 2), ('op', '×'), ('v', 3), ('op', '+'),
                    ('v', 4), ('op', '+'), ('v', 5), ('op', '×'),
                    ('v', 6)], 40)
check('8÷2+2', [('v', 8), ('op', '÷'), ('v', 2), ('op', '+'), ('v', 2)], 6)
check('10+8÷2', [('v', 10), ('op', '+'), ('v', 8), ('op', '÷'), ('v', 2)], 14)
print('ALL ENGINE CHAIN TESTS PASSED')
