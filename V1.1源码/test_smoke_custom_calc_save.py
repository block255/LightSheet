"""自定义运算 — 保存/环检测/拖接口/拖出结构 回归测试。

覆盖 2026-08-28 修复的 4 个隐蔽 bug：
1. 数元接入积木后保存失败（data.kind 字符串 vs 枚举）
2. 循环嵌套卡死（Qt 图形父子环）
3. 拖到自己第 2/3 接口误报"循环嵌套"
4. 拖"接口数元外层框"破坏容器结构（_build_child_items 误建 BlockItem + 拖出不补槽）

运行：offscreen；python test_smoke_custom_calc_save.py
"""
import os
import sys

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
sys.path.insert(0, r'D:\Cloude Code\自制表格软件\代码输出库\源码')

from PyQt6.QtWidgets import QApplication
app = QApplication([])

from custom_calc.model import (
    BlockType, CalcSubtype, InputKind, SymKind, OutputTarget,
    DataDef, make_count, make_check, make_output, make_calc_num,
    block_to_dict,
)
from custom_calc.editor import CustomCalcEditor, BlockItem, InterfaceItem, _node_to_dict
from PyQt6.QtCore import QPointF


def check(name, cond):
    if not cond:
        raise AssertionError(f'FAIL: {name}')
    print('PASS:', name)


def make_range_num(start, end):
    """数元：范围输入（列）。"""
    n = make_calc_num()
    n.data = DataDef(kind=InputKind.RANGE, range_axis='col',
                     range_start=start, range_end=end)
    return n


def make_const_num(v):
    n = make_calc_num()
    n.data = DataDef(kind=InputKind.CONST, value=v)
    return n


def build_crash1():
    """构造与「崩溃配置1」相同的计数积木（范围:列B-G >= 常数3）。"""
    c = make_count()
    c.children[0] = make_range_num(1, 6)
    c.children[1] = make_symbol_ge()
    c.children[2] = make_const_num(3.0)
    return c


def make_symbol_ge():
    from custom_calc.model import BlockNode
    return BlockNode(type=BlockType.SYMBOL, sym_kind=SymKind.LOGIC,
                     sym_value='>=')


def fresh_editor(roots):
    ed = CustomCalcEditor()
    ed._direction = '以列为单位'
    ed._scene.clear_blocks()
    for node in roots:
        item = ed._scene.add_block(node, QPointF(node.x, node.y))
        ed._build_child_items(node, item)
    return ed


# ======================================================================
# Bug1：数元接入积木后保存（序列化）
# ======================================================================
print('--- Bug1: 保存（接入积木后序列化） ---')
count_node = build_crash1()
ed = fresh_editor([count_node])
count_item = next(i for i in ed._scene._items if i.node is count_node)
check_item = ed._scene.add_block(make_check(), QPointF(400, 0))
ed._build_child_items(check_item.node, check_item)
# 检定嵌入计数积木数元2（用户操作路径：崩溃配置2 结构，
# refresh=数元2 接口，与真实"点接口→接入积木"一致）
iface2 = next(i for i in count_item.interfaces if i.slot == ('children', 2))
ed._attach_block_to_num(count_node.children[2], check_item, refresh=iface2)
# kind 应为枚举
check('接入后 kind 是枚举 InputKind.BLOCK',
      count_node.children[2].data.kind == InputKind.BLOCK)
check('嵌入成功：数元2.data.block 是检定',
      count_node.children[2].data.block is check_item.node)
# 序列化（编辑器路径）不崩
payload = {'version': 1, 'direction': '以列为单位',
           'blocks': [_node_to_dict(r) for r in [count_node]]}
import json
try:
    s = json.dumps(payload, ensure_ascii=False)
    ok = True
except Exception:
    ok = False
check('接入后 _node_to_dict 序列化成功', ok)
# 动态脚本记录路径（model.block_to_dict）不崩
try:
    s2 = json.dumps({'custom_blocks': [block_to_dict(count_node)]},
                    ensure_ascii=False)
    ok2 = True
except Exception:
    ok2 = False
check('接入后 block_to_dict 序列化成功', ok2)

# 脏数据容错：字符串 kind / output_target 也能序列化（历史脏数据）
count_node.children[2].data.kind = 'block'   # 模拟旧脏数据
out = make_output()
out.children[0] = count_node
out.output_target = 'row'                     # 模拟字符串枚举
try:
    s3 = json.dumps({'blocks': [_node_to_dict(out)]}, ensure_ascii=False)
    ok3 = True
except Exception:
    ok3 = False
check('脏数据(字符串kind/output_target)序列化容错', ok3)

# 保存的 JSON 可重新加载
from custom_calc.editor import _node_from_dict
roots2 = [_node_from_dict(d) for d in json.loads(s)['blocks']]
check('序列化后可重新加载', len(roots2) == 1
      and roots2[0].children[2].data.kind == InputKind.BLOCK)
ed.close()

# ======================================================================
# Bug2：循环嵌套检测（不再卡死）
# ======================================================================
print('--- Bug2: 循环嵌套拦截 ---')
count_node = build_crash1()
ed = fresh_editor([count_node])
count_item = next(i for i in ed._scene._items if i.node is count_node)
check_item = ed._scene.add_block(make_check(), QPointF(400, 0))
ed._build_child_items(check_item.node, check_item)
# 步骤1：计数嵌入检定数元1（正常，refresh=检定数元1 接口）
check_iface0 = next(i for i in check_item.interfaces
                    if i.slot == ('children', 0))
ed._attach_block_to_num(check_item.node.children[0], count_item,
                        refresh=check_iface0)
check('步骤1 正常嵌入', check_item.node.children[0].data.block is count_node)
# 步骤2：检定嵌回计数数元2 → 应被拦截（不再卡死）
import unittest.mock as _mock
warned = []
with _mock.patch('PyQt6.QtWidgets.QMessageBox.warning',
                 side_effect=lambda *a, **k: warned.append(1)):
    ed._attach_block_to_num(count_node.children[2], check_item)
check('步骤2 循环被拦截', len(warned) == 1)
check('步骤2 后计数数元2.data.block 为 None',
      count_node.children[2].data.block is None)
check('步骤2 后检定数元1.data.block 仍为计数（原嵌入未被破坏）',
      check_item.node.children[0].data.block is count_node)
ed.close()

# ======================================================================
# Bug3：拖到自己接口不再误判（多接口积木）
# ======================================================================
print('--- Bug3: 拖到自己接口 ---')
count_node = build_crash1()
ed = fresh_editor([count_node])
count_item = next(i for i in ed._scene._items if i.node is count_node)
check('计数积木有 3 个接口', len(count_item.interfaces) == 3)
# 拖到自己第 3 个接口（数元2）
iface2 = count_item.interfaces[2]
scene_pos = iface2.mapToScene(iface2.boundingRect().center())
# 判定函数
check('_is_own_interface 识别自己的接口',
      ed._scene._is_own_interface(count_item, iface2))
drop_events = []
ed._scene.drop_on_interface.connect(lambda i, f: drop_events.append(f.slot))
ed._scene._on_drag_finished(count_item, scene_pos)
check('拖到自己接口不触发 drop（期望 0 次）', len(drop_events) == 0)
check('计数 children 仍为 3 槽', len(count_node.children) == 3)
ed.close()

# ======================================================================
# Bug4：接口数元无独立 BlockItem + 拖出补槽
# ======================================================================
print('--- Bug4: 接口数元显示与拖出结构 ---')
count_node = build_crash1()
check_node = make_check()   # 未定义检定
ed = fresh_editor([count_node])
count_item = next(i for i in ed._scene._items if i.node is count_node)
check_item = ed._scene.add_block(check_node, QPointF(400, 0))
ed._build_child_items(check_node, check_item)
iface2 = next(i for i in count_item.interfaces if i.slot == ('children', 2))
ed._attach_block_to_num(count_node.children[2], check_item, refresh=iface2)
# 渲染结构：计数积木子图形项应只有 符号 + 检定（接口数元无 BlockItem）
child_blocks = [c for c in count_item.childItems() if isinstance(c, BlockItem)] \
    if False else None
# 重新获取 count_item（fresh_editor 返回后）
count_item = next(i for i in ed._scene._items if i.node is count_node)
num_items = [c for c in count_item.childItems()
             if isinstance(c, BlockItem)
             and c.node.type == BlockType.CALC
             and c.node.calc_subtype == CalcSubtype.NUM]
check('接口数元无独立 BlockItem（期望 0 个数元框）', len(num_items) == 0)
check_items = [c for c in count_item.childItems()
               if isinstance(c, BlockItem) and c.node.type == BlockType.CHECK]
check('内嵌检定有 BlockItem（期望 1）', len(check_items) == 1)
# 拖出检定 → 计数保持 3 槽 + 数元2 恢复未定义
ed._scene._on_drag_finished(check_items[0], QPointF(900, 900))
check('拖出检定后计数仍 3 槽', len(count_node.children) == 3)
check('拖出后数元2.data.block 清空',
      count_node.children[2].data.block is None)
check('拖出后数元2.data.kind 清空',
      count_node.children[2].data.kind is None)
# 顶层：计数 + 检定
tops = [it.node for it in ed._scene._items if it.parentItem() is None]
check('顶层为 计数 + 检定', sorted(t.type.value for t in tops) == ['check', 'count'])
ed.close()

# ======================================================================
# Bug4b：拖出符号 → 计数/检定补回符号槽
# ======================================================================
print('--- Bug4b: 拖出符号补槽 ---')
count_node = build_crash1()
ed = fresh_editor([count_node])
count_item = next(i for i in ed._scene._items if i.node is count_node)
sym_item = next(c for c in count_item.childItems()
                if isinstance(c, BlockItem) and c.node.type == BlockType.SYMBOL)
ed._scene._on_drag_finished(sym_item, QPointF(900, 900))
check('拖出符号后计数仍 3 槽', len(count_node.children) == 3)
check('补回的符号槽是未定义符号占位',
      count_node.children[1].type == BlockType.SYMBOL
      and count_node.children[1].sym_value is None)
ed.close()

print()
print('ALL CUSTOM-CALC SAVE TESTS PASSED')
print('ALL CUSTOM-CALC SAVE TESTS PASSED')
print('ALL CUSTOM-CALC SAVE TESTS PASSED')
