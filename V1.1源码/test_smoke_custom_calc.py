"""自定义运算冒烟测试 — 步骤集成（确认按钮联动）+ 引擎求值 + 数学优先级 + 输出。"""
import os
import sys

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
sys.path.insert(0, r'D:\Cloude Code\自制表格软件\代码输出库\源码')

from PyQt6.QtWidgets import QApplication
app = QApplication([])

from models.spreadsheet_model import SpreadsheetModel
from views.side_panel import SidePanel
from views.spreadsheet_grid import SpreadsheetGrid
from views.status_bar import StatusBar
from controllers.script_controller import ScriptController
from scripts.base_script import ChooseOptionStep, CustomCalcStep
from scripts.自定义运算脚本 import CustomCalcScript
from custom_calc.model import (
    BlockType, SymKind, OutputTarget, make_paren, make_symbol,
)
from custom_calc.engine import EvalContext, Evaluator


def check(name, cond):
    if not cond:
        raise AssertionError(f'FAIL: {name}')
    print('PASS:', name)


def make_calc_num_const(v: float):
    from custom_calc.model import CalcSubtype, DataDef, InputKind, make_calc_num
    n = make_calc_num()
    n.data = DataDef(kind=InputKind.CONST, value=v)
    return n


def make_output_node():
    from custom_calc.model import make_output
    n = make_output()
    n.output_target = OutputTarget.CLIPBOARD
    return n


def make_paren2(*nodes):
    p = make_paren()
    p.children = list(nodes)
    return p


# ---------- 1. 脚本结构 ----------
s = CustomCalcScript()
check('script name', s.name == '自定义运算脚本')
steps = s.steps()
check('steps structure', [type(x).__name__ for x in steps]
      == ['ChooseOptionStep', 'CustomCalcStep'])
check('direction key', steps[0].groups == {'direction': ['以列为单位', '以行为单位']})
check('blocks key', steps[1].key == 'custom_blocks')

# ---------- 2. 引擎：数学优先级 2+3×4=14 ----------
model = SpreadsheetModel()
model.load_2d([['1'], ['2'], ['3']])
ctx = EvalContext(model, '对列处理')
ev = Evaluator(ctx)
paren = make_paren()
paren.children = [
    make_calc_num_const(2.0),
    make_symbol('+', SymKind.OP),
    make_calc_num_const(3.0),
    make_symbol('×', SymKind.OP),
    make_calc_num_const(4.0),
]
check('数学优先级 2+3×4=14', ev.evaluate(paren) == 14)

# ---------- 3. 引擎：括号改变顺序 (2+3)×4=20 ----------
paren2 = make_paren2(
    make_paren2(make_calc_num_const(2.0), make_symbol('+', SymKind.OP),
                make_calc_num_const(3.0)),
    make_symbol('×', SymKind.OP),
    make_calc_num_const(4.0),
)
check('括号 (2+3)×4=20', ev.evaluate(paren2) == 20)


# ---------- 4. 控制器：无积木点确定 → 提示先打开编辑器，不推进 ----------
grid = SpreadsheetGrid()
grid.setModel(model)
status = StatusBar()
panel = SidePanel()
ctrl = ScriptController(model, grid, status, panel)
ctrl._running = True
ctrl._script = s
ctrl._steps = list(s.steps())
ctrl._step_idx = 1  # 停在 CustomCalcStep
ctrl._custom_calc_step = ctrl._steps[1]
ctrl._params = {'direction': '以列为单位'}
ctrl._panel.show_confirm_button(enabled=True)
ctrl._panel.confirm_clicked.connect(ctrl._on_custom_calc_confirmed)
ctrl._panel.confirm_clicked.emit()
check('无积木确认 → 提示构建', '尚未构建积木' in panel._script_prompt.text())
check('无积木确认 → 步骤不推进', ctrl._step_idx == 1)

# ---------- 5. 控制器：有积木点确定 → 推进并执行（输出到剪贴板） ----------
out = make_output_node()
out.children[0] = make_paren2(
    make_calc_num_const(2.0), make_symbol('+', SymKind.OP),
    make_calc_num_const(3.0), make_symbol('×', SymKind.OP),
    make_calc_num_const(4.0))
ctrl._params['custom_blocks'] = [out]
ctrl._panel.confirm_clicked.emit()
check('有积木确认 → 执行完成（脚本跑完清理）', not ctrl._running)
check('执行完成提示', '完成' in panel._script_prompt.text())
check('剪贴板输出 14', QApplication.clipboard().text() == '14')

# ---------- 6. run 直接调用：列数据 + 常数广播输出到行 ----------
model2 = SpreadsheetModel()
model2.load_2d([
    ['A', 'B'],
    ['1', 'x'],
    ['2', ''],
    ['3', 'y'],
])
out2 = make_output_node()
out2.output_target = OutputTarget.COL
out2.output_index = 3   # 列D（10 计划：垂直表输出到列，方向一致）
col_a = make_calc_num_const(0.0)
col_a.data.kind = 'col'
col_a.data.index = 0
out2.children[0] = make_paren2(
    col_a, make_symbol('+', SymKind.OP), make_calc_num_const(10.0))
p = {'direction': '以列为单位', 'custom_blocks': [out2]}
check('列+常数广播 run ok', s.run(model2, p) is None)
# 列A 纯数据在行1,2,3（位置1,2,3），输出到列D 按位置写回行1,2,3
check('A 列纯数据 1,2,3 +10 → 11,12,13（按位置写回列D）',
      model2.value(1, 3) == '11' and model2.value(2, 3) == '12'
      and model2.value(3, 3) == '13')
# 垂直表输出到行 → 方向不一致 → 拒绝（10 计划）
out2b = make_output_node()
out2b.output_target = OutputTarget.ROW
out2b.output_index = 4
out2b.children[0] = make_paren2(
    col_a, make_symbol('+', SymKind.OP), make_calc_num_const(10.0))
p2c = {'direction': '以列为单位', 'custom_blocks': [out2b]}
r2c = s.run(model2, p2c)
check('垂直表输出到行方向不一致 → 拒绝', r2c is not None
      and '方向不一致' in r2c)

# ---------- 7. 输出位置重叠检测（按实际写回位置） ----------
# out2 表结果写列D 行1,2,3；out3 单值写行4 列0 → 实际不重叠 → 不报错
out3 = make_output_node()
out3.output_target = OutputTarget.ROW
out3.output_index = 4
out3.children[0] = make_calc_num_const(1.0)
p2 = {'direction': '以列为单位', 'custom_blocks': [out2, out3]}
check('表(列)+单值(行)实际不重叠', s.run(model2, p2) is None)
check('单值落到行4列0', model2.value(4, 0) == '1')
# 两个单值输出到同一行 → 都写列0 → 实际重叠 → 报错
out3b = make_output_node()
out3b.output_target = OutputTarget.ROW
out3b.output_index = 4
out3b.children[0] = make_calc_num_const(2.0)
p2b = {'direction': '以列为单位', 'custom_blocks': [out3, out3b]}
check('两单值同目标行重叠 → 报错', s.run(model2, p2b) is not None)
# 行方向表（水平）输出到行4 写列0,1 + 单值写行4 列0 → 实际重叠 → 报错
from custom_calc.model import make_calc_num as _mkn7, InputKind as _IK7, DataDef as _DD7
outA = make_output_node()
outA.output_target = OutputTarget.ROW
outA.output_index = 4
rowA = _mkn7(); rowA.data = _DD7(kind=_IK7.ROW, index=1)   # 行2 = ['1','x'] → 纯数据 [1] positions [0]
outA.children[0] = rowA
outB = make_output_node()
outB.output_target = OutputTarget.ROW
outB.output_index = 4
outB.children[0] = make_calc_num_const(9.0)
p7b = {'direction': '以列为单位', 'custom_blocks': [outA, outB]}
s7 = CustomCalcScript()
m7b = SpreadsheetModel()
m7b.load_2d([['1'], ['2'], ['3']])
r7 = s7.run(m7b, p7b)
check('表列0与单值列0重叠 → 报错', r7 is not None and '重叠' in r7)

# ---------- 8. 三按钮流程：选方向后不自动弹窗，侧栏显示三按钮 ----------
from PyQt6.QtWidgets import QMessageBox
# 屏蔽弹窗（offscreen 测试不触发真实弹窗）
QMessageBox.information = staticmethod(lambda *a, **k: None)
QMessageBox.warning = staticmethod(lambda *a, **k: None)

model3 = SpreadsheetModel()
model3.load_2d([['1'], ['2']])
grid3 = SpreadsheetGrid()
grid3.setModel(model3)
panel3 = SidePanel()
ctrl3 = ScriptController(model3, grid3, StatusBar(), panel3)
ctrl3._running = True
ctrl3._script = s
ctrl3._steps = list(s.steps())
ctrl3._step_idx = 1
ctrl3._params = {'direction': '以列为单位'}
ctrl3._begin_custom_calc(ctrl3._steps[1])
check('选方向后不自动打开编辑器', ctrl3._custom_editor is None)
check('三按钮：打开编辑器', getattr(panel3, '_open_editor_btn', None) is not None)
check('三按钮：检查报错', getattr(panel3, '_check_errors_btn', None) is not None)
check('三按钮：确定默认禁用',
      panel3._confirm_btn is not None and not panel3._confirm_btn.isEnabled())

# 点「检查报错」无积木 → 弹窗提示（不崩溃）
ctrl3._on_check_custom_errors()
check('检查报错无积木不崩溃', True)

# 打开编辑器（exec 模态无法 offscreen 测试，改验证编辑器的模块级校验函数）
from custom_calc.editor import validate_blocks
check('validate 空积木区', '空白' in validate_blocks([])[0])
check('validate 无输出积木', '没有输出积木' in validate_blocks(
    [make_calc_num_const(1.0)]))

# ---------- 9. 6 大类创建列表（胚积木） ----------
from custom_calc.editor import CustomCalcEditor
ed = CustomCalcEditor()
names = [n for n, _ in ed._creation_types()]
check('创建列表 6 大类', names == ['计算元类', '符号元类', '括号积木',
                                  '计数积木', '检定积木', '输出积木'])
calc_bud, sym_bud = ed._creation_types()[0][1], ed._creation_types()[1][1]
check('计算元胚：未选子类', calc_bud.calc_subtype is None)
check('符号元胚：未选符号', sym_bud.sym_value is None)
from custom_calc.model import BlockType, CalcSubtype, SymKind, BlockNode
cnt = ed._creation_types()[3][1]
check('计数胚：左计算元+符号+右计算元',
      cnt.type == BlockType.COUNT and len(cnt.children) == 3
      and cnt.children[0].calc_subtype == CalcSubtype.NUM
      and cnt.children[1].type == BlockType.SYMBOL
      and cnt.children[2].calc_subtype == CalcSubtype.NUM)
ed.close()

# 回归：编辑器检查报错按钮路径（validate 复用模块函数）
ed2 = CustomCalcEditor()
ed2._scene.add_block(make_calc_num_const(5.0))
errs = ed2.validate()
check('编辑器 validate 无输出 → 报错', '没有输出积木' in errs)
ed2.close()

# ---------- 10. 方向校验：数元定义面板文字 + 只接受对应方向 ----------
from PyQt6.QtWidgets import QInputDialog, QMessageBox, QLabel, QPushButton
# 屏蔽 QInputDialog / QMessageBox（不真实弹窗）
QInputDialog.getText = staticmethod(lambda *a, **k: ('列A', True))
QMessageBox.warning = staticmethod(lambda *a, **k: None)

# 以列为单位 → 按钮显示「输入列」，接受 列A
ed3 = CustomCalcEditor(direction='以列为单位')
ed3._show_num_define_panel.__self__  # 确保存在
# 直接检查 _show_num_define_panel 生成的按钮文字较复杂，
# 改测 rowcol 分支的接受逻辑：
num_item = None
from custom_calc.model import make_calc_num
num_node = make_calc_num()
ed3._direction = '以列为单位'
# 模拟输入 列A → 接受
from custom_calc.model import DataDef, InputKind
ed3._num_define = ed3._num_define  # noop 保引用
# 直接调 _num_define 前先注入一个假 item
class _FakeItem:
    def __init__(self, node):
        self.node = node
    def update(self):
        pass
fi = _FakeItem(num_node)
# 列方向：输入 行1 → 应拒绝（弹窗，不设 data）
QInputDialog.getText = staticmethod(lambda *a, **k: ('行1', True))
ed3._num_define(num_node, 'rowcol')
check('列方向拒绝 行1（kind 未设）', num_node.data.kind is None)
# 列方向：输入 列A → 接受
QInputDialog.getText = staticmethod(lambda *a, **k: ('列A', True))
ed3._num_define(num_node, 'rowcol')
check('列方向接受 列A', num_node.data.kind == InputKind.COL
      and num_node.data.index == 0)

# 行方向：只接受 行N
ed4 = CustomCalcEditor(direction='以行为单位')
num_node4 = make_calc_num()
QInputDialog.getText = staticmethod(lambda *a, **k: ('列A', True))
ed4._num_define(num_node4, 'rowcol')
check('行方向拒绝 列A（kind 未设）', num_node4.data.kind is None)
QInputDialog.getText = staticmethod(lambda *a, **k: ('行3', True))
ed4._num_define(num_node4, 'rowcol')
check('行方向接受 行3', num_node4.data.kind == InputKind.ROW
      and num_node4.data.index == 2)

# ---------- 11. 子接口渲染：按积木结构生成接口 ----------
ed5 = CustomCalcEditor()
from custom_calc.model import make_calc_exp, make_calc_trig, make_paren, \
    make_output, make_count
exp_item = ed5._scene.add_block(make_calc_exp())
check('指数积木 2 个接口', len(exp_item.interfaces) == 2)
check('指数接口 slot 正确',
      exp_item.interfaces[0].slot == ('children', 0)
      and exp_item.interfaces[1].slot == ('children', 1))
check('指数接口已注册进场景',
      len(ed5._scene._interfaces) >= 2)
trig_item = ed5._scene.add_block(make_calc_trig())
check('三角积木 1 个接口', len(trig_item.interfaces) == 1
      and trig_item.interfaces[0].slot == ('children', 0))
paren_item = ed5._scene.add_block(make_paren())
check('括号积木 1 个链式接口', len(paren_item.interfaces) == 1
      and paren_item.interfaces[0].slot == ('children', 0))
out_item = ed5._scene.add_block(make_output())
check('输出积木 1 个接口', len(out_item.interfaces) == 1
      and out_item.interfaces[0].slot == ('output',))
cnt_item = ed5._scene.add_block(make_count())
check('计数积木 3 个接口', len(cnt_item.interfaces) == 3)
# 清除后接口注销
total = len(ed5._scene._interfaces)
ed5._scene.remove_block(cnt_item)
check('移除积木后接口注销', len(ed5._scene._interfaces) == total - 3)
# 类型切换重建接口：数元胚 → 指数
bud_item = ed5._scene.add_block(
    BlockNode(type=BlockType.CALC))   # 胚计算元：无接口
check('胚计算元无接口', len(bud_item.interfaces) == 0)
ed5._set_calc_type(bud_item, CalcSubtype.EXP)
check('胚 → 指数后重建 2 个接口', len(bud_item.interfaces) == 2)

# ---------- 12. 接口点击：数元接口 → 定义面板；积木接口 → 添加/嵌入 ----------
# 数元接口（kind='num'）：指数积木的子接口，node_ref 指向 children[0]
exp_iface0 = exp_item.interfaces[0]
check('数元接口 kind=num', exp_iface0.kind == 'num')
check('数元接口 node_ref 指向子节点',
      exp_iface0.node_ref is exp_item.node.children[0])
# 点击数元接口 → 操作栏显示定义按钮（模拟 scene 信号）
ed5._on_interface_clicked(exp_iface0)
# 检查左侧面板有「定义数元:」标签
found_define = any(
    isinstance(ed5._left_panel.itemAt(i).widget(), QLabel)
    and '定义数元' in ed5._left_panel.itemAt(i).widget().text()
    for i in range(ed5._left_panel.count())
) if ed5._left_panel.count() else False
check('点击数元接口 → 操作栏数元定义', found_define)

# 积木接口（kind='slot'）：输出积木的接口
out_iface = out_item.interfaces[0]
check('积木接口 kind=slot', out_iface.kind == 'slot')
ed5._on_interface_clicked(out_iface)
texts = []
for i in range(ed5._left_panel.count()):
    w = ed5._left_panel.itemAt(i).widget()
    if isinstance(w, (QLabel, QPushButton)):
        texts.append(w.text())
check('点击积木接口 → 提示添加/嵌入',
      any('添加积木' in t or '嵌入积木' in t for t in texts))

# 嵌入积木：右键目标积木 → 嵌入输出积木接口
ed5._slot_pick_mode = True
ed5._pending_slot_iface = out_iface
ed5._on_item_clicked(exp_item, 'right')   # 右键指数积木嵌入输出
check('嵌入后输出积木 children[0] 是指数', out_item.node.children[0] is exp_item.node)

# 接口内部位置：数元接口在积木内部（x < 积木宽）
check('指数数元接口内嵌（x 在积木内部）',
      exp_iface0.pos().x() < exp_item._layout_width())

# ---------- 13. 父子嵌套：嵌入后母积木扩尺寸包住子积木 ----------
# 指数积木嵌入输出积木接口后，应成为输出积木的子项
check('嵌入后子积木成为母积木子项', exp_item.parentItem() is out_item)
# 母积木 boundingRect 应包住子积木（宽度 >= 子积木右边界）
out_rect = out_item.boundingRect()
exp_rect = exp_item.boundingRect()
child_right = exp_item.pos().x() + exp_rect.width()
check('母积木扩尺寸包住子积木', out_rect.width() >= child_right - 0.01)
# 母积木移动 → 子积木跟随（相对坐标不变）
out_pos_before = out_item.pos()
exp_scene_before = exp_item.scenePos()
out_item.setPos(out_pos_before.x() + 50, out_pos_before.y() + 30)
check('母积木移动子积木跟随',
      abs((exp_item.scenePos().x() - exp_scene_before.x()) - 50) < 0.01
      and abs((exp_item.scenePos().y() - exp_scene_before.y()) - 30) < 0.01)
# 拖出：解除父子，回到画布顶层，母积木收缩
ed5._on_detach(exp_item, out_item)
check('拖出后子积木回画布顶层', exp_item.parentItem() is None)
check('拖出后输出积木 children 恢复占位',
      out_item.node.children[0].is_interface)

# ---------- 14. 计数/检定：中间是逻辑符号接口（非数元） ----------
from custom_calc.model import make_count, make_check
cnt_item2 = ed5._scene.add_block(make_count())
ifaces = cnt_item2.interfaces
check('计数 3 个接口', len(ifaces) == 3)
check('计数左右是数元接口', ifaces[0].kind == 'num'
      and ifaces[2].kind == 'num')
check('计数中间是符号接口', ifaces[1].kind == 'sym')
check('计数中间符号初始 ?', ifaces[1]._sym_label() == '?')
# 点击中间符号接口 → 操作栏符号表
ed5._on_interface_clicked(ifaces[1])
texts = []
for i in range(ed5._left_panel.count()):
    w = ed5._left_panel.itemAt(i).widget()
    if isinstance(w, (QLabel, QPushButton)):
        texts.append(w.text())
check('点击符号接口 → 显示符号表', any(t in texts for t in
      ['=', '>', '<', '≠']))
# 设置符号 → 显示更新
ed5._set_symbol(cnt_item2.node.children[1], '>', refresh=ifaces[1])
check('符号接口显示 >', ifaces[1]._sym_label() == '>')
check('符号节点 sym_kind 逻辑', cnt_item2.node.children[1].sym_kind == SymKind.LOGIC)

# ---------- 15. 对数/三角：数元接口接入积木后显示嵌入积木标签 ----------
from custom_calc.editor import _node_short_label
from custom_calc.model import make_calc_log, make_calc_trig, make_calc_num, \
    DataDef, InputKind
log_item2 = ed5._scene.add_block(make_calc_log())
check('对数 2 个数元接口', all(i.kind == 'num' for i in log_item2.interfaces))
check('对数接口未定义显示 数元?',
      log_item2.interfaces[0]._num_label() == '数元?')
# 给对数底数接口定义常数 3 → 显示 3
log_item2.node.children[0].data = DataDef(kind=InputKind.CONST, value=3.0)
ed5._refresh_interface(log_item2.interfaces[0])
check('对数底数定义后显示 3', log_item2.interfaces[0]._num_label() == '3')
# 嵌入积木到数元接口（data.block）→ 显示嵌入积木标签
embedded = make_calc_num()
embedded.data = DataDef(kind=InputKind.CONST, value=7.0)
log_item2.node.children[1].data = DataDef(kind=InputKind.BLOCK, block=embedded)
ed5._refresh_interface(log_item2.interfaces[1])
check('接入积木后显示嵌入积木标签（7 而非“积木”）',
      log_item2.interfaces[1]._num_label() == '7')
check('_node_short_label 数元', _node_short_label(embedded) == '7')

# ---------- 16. 输出积木接口内收 + 母积木高度 ----------
out_item2 = ed5._scene.add_block(make_output())
out_iface2 = out_item2.interfaces[0]
check('输出接口内收（x 在积木内部右侧）',
      out_iface2.pos().x() < out_item2._layout_width() - 10)
check('输出积木高度较高（容器型）', out_item2._height == out_item2._H_TALL)
check('指数积木高度随内容（接口高+留白）', exp_item._height == 46)
# 嵌入后母积木上下露出（母高 > 子积木高）
exp_item2 = ed5._scene.add_block(make_calc_exp())
exp_item2.setParentItem(out_item2)
exp_item2.setPos(8, 0)
check('母积木高于子积木（上下露出）',
      out_item2._height > exp_item2._height)

# ---------- 17. 括号链式：接入自动插符号 + 拖出留对应占位 ----------
ed6 = CustomCalcEditor()
paren6 = ed6._scene.add_block(make_paren())
check('空括号 1 个占位接口', len(paren6.interfaces) == 1
      and paren6.interfaces[0].slot == ('children', 0))
# 空括号 children = [计算元占位]
check('空括号 children 结构', len(paren6.node.children) == 1
      and paren6.node.children[0].is_interface)

# 拖入第一个值积木 → 链尾
val_a = make_calc_num_const(1.0)
val_a_item = ed6._scene.add_block(val_a)
iface0 = paren6.interfaces[0]
ed6._on_drop_interface(val_a_item, iface0)
check('接入 A 后链 = [A, 计算元占位]',
      len(paren6.node.children) == 2
      and paren6.node.children[0] is val_a
      and paren6.node.children[1].is_interface)
check('接入 A 后接口移到链尾',
      paren6.interfaces[0].slot == ('children', 1))

# 再拖入第二个值积木 → 自动插符号占位
val_b = make_calc_num_const(2.0)
val_b_item = ed6._scene.add_block(val_b)
iface1 = paren6.interfaces[0]
ed6._on_drop_interface(val_b_item, iface1)
check('接入 B 后链 = [A, 符号占位, B, 计算元占位]',
      len(paren6.node.children) == 4
      and paren6.node.children[0] is val_a
      and paren6.node.children[1].type == BlockType.SYMBOL
      and paren6.node.children[2] is val_b
      and paren6.node.children[3].is_interface)
check('B 接入后接口数 2（符号接口+计算元接口）',
      len(paren6.interfaces) == 2)
kinds = sorted(i.kind for i in paren6.interfaces)
check('接口含符号接口+计算元接口', kinds == ['slot', 'sym'])
# 符号接口 node_ref 指向符号占位
sym_iface = [i for i in paren6.interfaces if i.kind == 'sym'][0]
check('符号接口指向符号占位', sym_iface.node_ref is paren6.node.children[1])

# 拖出 B（值积木）→ 原 B 位留计算元接口
ed6._on_detach(val_b_item, paren6)
check('拖出 B 后链 = [A, 符号占位, 计算元占位]',
      len(paren6.node.children) == 3
      and paren6.node.children[0] is val_a
      and paren6.node.children[1].type == BlockType.SYMBOL
      and paren6.node.children[2].is_interface)
check('拖出值积木 → 留计算元接口', paren6.node.children[2].is_interface)
# 拖出后 B 回画布顶层
check('拖出后 B 解除父子', val_b_item.parentItem() is None)
ed6.close()

# ---------- 18. 问题1：空括号接口在右侧（不在左边缘） ----------
ed7 = CustomCalcEditor()
paren7 = ed7._scene.add_block(make_paren())
check('空括号 1 个接口', len(paren7.interfaces) == 1)
check('空括号接口在右侧（x >= 宽-50）',
      paren7.interfaces[0].pos().x() >= paren7._layout_width() - 50)
ed7.close()

# ---------- 19. 问题2：输出嵌入后接口隐藏 + 问题3：输出不能做子积木 ----------
ed8 = CustomCalcEditor()
out8 = ed8._scene.add_block(make_output())
a8 = make_calc_num_const(4.0)
ai8 = ed8._scene.add_block(a8)
ed8._on_drop_interface(ai8, out8.interfaces[0])
check('输出嵌入后接口隐藏', not out8.interfaces[0].isVisible())
# 输出积木拖入括号 → 拒绝
paren8 = ed8._scene.add_block(make_paren())
out_b = ed8._scene.add_block(make_output())
out_iface = paren8.interfaces[0]
ed8._on_drop_interface(out_b, out_iface)
check('输出积木不能作为子积木', len(paren8.node.children) == 1
      and paren8.node.children[0].is_interface)
ed8.close()

# ---------- 20. 问题4：数元接口接入积木 → 接口隐藏+积木内嵌 ----------
ed9 = CustomCalcEditor()
exp9 = ed9._scene.add_block(make_calc_exp())
b9 = make_calc_num_const(5.0)
bi9 = ed9._scene.add_block(b9)
# 模拟接口点击进入接入流程：refresh=iface（旧接口对象会在 relayout 重建，
# 用重建后的接口断言）
ed9._pick_block_target = exp9.node.children[0]
ed9._pick_block_refresh = exp9.interfaces[0]
ed9._on_item_clicked(bi9, 'right')
check('数元接口接入后接口隐藏',
      not exp9.interfaces[0].isVisible())
check('数元接口接入后积木内嵌',
      bi9.parentItem() is exp9 and exp9.node.children[0].data.block is b9)
ed9.close()

# ---------- 21. 问题5：类型切换后尺寸收缩 + 旧子积木释放 ----------
from custom_calc.editor import CustomCalcEditor, BlockItem
ed10 = CustomCalcEditor()
calc10 = ed10._scene.add_block(
    BlockNode(type=BlockType.CALC))   # 胚计算元
ed10._set_calc_type(calc10, CalcSubtype.EXP)   # → 指数（宽）
w_exp = calc10.boundingRect().width()
ed10._set_calc_type(calc10, CalcSubtype.TRIG)  # → 三角（窄）
check('类型切换后尺寸收缩（三角 < 指数）',
      calc10.boundingRect().width() < w_exp)
check('类型切换后子积木无残留',
      len([c for c in calc10.childItems()
           if isinstance(c, BlockItem)]) == 0)
ed10.close()

# ---------- 22. 同类型积木重复嵌入（BlockNode eq=False 身份比较） ----------
# 回归：两个未定义的检定积木字段相同，必须按身份区分，不能互相踢出
ed11 = CustomCalcEditor()
paren11 = ed11._scene.add_block(make_paren())
# 连续嵌入两个检定积木（同类型同字段）
from custom_calc.model import make_check as mk_check
ck_a = mk_check()
ck_a_item = ed11._scene.add_block(ck_a)
ed11._attach_to_slot(ck_a, paren11.interfaces[0], ck_a_item)
tail11 = [i for i in paren11.interfaces if i.kind == 'slot'][0]
ck_b = mk_check()
ck_b_item = ed11._scene.add_block(ck_b)
ed11._attach_to_slot(ck_b, tail11, ck_b_item)
chain11 = paren11.node.children
check('两个检定积木都保留在链中',
      len(chain11) == 4 and ck_a in chain11 and ck_b in chain11)
check('链式结构正确（值符号值占位）',
      [c.type for c in chain11] == [
          BlockType.CHECK, BlockType.SYMBOL, BlockType.CHECK,
          BlockType.CALC])
check('两积木位置不重叠',
      abs(ck_a_item.pos().x() - ck_b_item.pos().x()) > 10)
ed11.close()

# ---------- 23. 拖出后不跟随（图形父子真正解除） ----------
# 括号嵌入子积木 → 拖出 → 拖动括号子积木不跟随
ed12 = CustomCalcEditor()
paren12 = ed12._scene.add_block(make_paren())
ck12 = mk_check()
ck12_item = ed12._scene.add_block(ck12)
ed12._attach_to_slot(ck12, paren12.interfaces[0], ck12_item)
# 拖出到空白处（场景坐标远离括号）
ck12_item.setPos(500, 300)
ed12._scene._on_drag_finished(ck12_item, ck12_item.scenePos())
check('拖出后子积木回画布顶层', ck12_item.parentItem() is None)
# 拖动括号，子积木不跟随
p0 = paren12.scenePos()
c0 = ck12_item.scenePos()
paren12.setPos(p0.x() + 80, p0.y() + 50)
check('拖动括号后拖出的积木不跟随',
      abs((ck12_item.scenePos() - c0).manhattanLength()) < 1)
ed12.close()

# ---------- 24. 固定槽替换：旧积木解除图形父子（不跟随） ----------
ed13 = CustomCalcEditor()
exp13 = ed13._scene.add_block(make_calc_exp())
# 底数接入积木 A
a13 = mk_check()
a13_item = ed13._scene.add_block(a13)
ed13._attach_block_to_num(exp13.node.children[0], a13_item)
# 再接入积木 B 替换（模拟拖入替换）
b13 = mk_check()
b13_item = ed13._scene.add_block(b13)
ed13._on_drop_interface(b13_item, exp13.interfaces[0])
# 旧积木 A 应已脱离 exp13 图形父子
check('固定槽替换后旧积木解除图形父子',
      a13_item.parentItem() is not exp13)
ed13.close()

# ---------- 25. 拖拽综合判定：鼠标点 + 碰撞 + 高亮 ----------
from PyQt6.QtCore import QPointF
ed14 = CustomCalcEditor()
paren14 = ed14._scene.add_block(make_paren())
drag_item = ed14._scene.add_block(make_calc_num())
# 把积木拖到括号接口上：鼠标点在接口半径内 且 积木本体覆盖接口
iface14 = paren14.interfaces[0]
gp = iface14.mapToScene(iface14.boundingRect().center())
drag_item.setPos(gp)   # 积木本体覆盖接口
found = ed14._scene.interface_at(gp, drag_item)
check('综合判定命中（点+碰撞）', found is iface14)
# 鼠标点远、积木覆盖 → 不命中（防大积木误触）
drag_item.setPos(gp + QPointF(200, 0))
found2 = ed14._scene.interface_at(gp, drag_item)
check('积木覆盖但鼠标点远 → 不命中', found2 is None)
# 高亮检测（积木移回接口位置）
drag_item.setPos(gp)
ed14._scene._highlight_drag_target(gp, drag_item)
hl = [i for i in paren14.interfaces if i._highlight]
check('拖拽中高亮命中接口', len(hl) == 1 and hl[0] is iface14)
# 拖拽高亮清除
ed14._scene._highlight_drag_target(QPointF(9999, 9999), drag_item)
hl2 = [i for i in paren14.interfaces if i._highlight]
check('移开后高亮清除', len(hl2) == 0)
ed14.close()

# ---------- 26. 右键菜单功能（删除/复制/清除定义） ----------
ed15 = CustomCalcEditor()
out15 = ed15._scene.add_block(make_output())
from custom_calc.model import make_calc_num as mk_num
num15 = mk_num()
num15_item = ed15._scene.add_block(num15)
# 清除定义：数元回胚态（calc_subtype=None）
ed15._clear_block_def(num15_item)
check('清除定义：数元回胚态',
      num15_item.node.calc_subtype is None)
# 复制：新增一个积木
before = len(ed15._scene.items())
ed15._copy_block(out15)
check('复制积木：场景积木数 +1',
      len(ed15._scene.items()) == before + 1)
# 删除：移除积木
ed15._delete_block(out15)
check('删除积木：场景积木数 -1',
      len(ed15._scene.items()) == before)
ed15.close()

# ---------- 27. 三角积木函数名选择 ----------
ed16 = CustomCalcEditor()
trig16 = ed16._scene.add_block(
    BlockNode(type=BlockType.CALC))
ed16._set_calc_type(trig16, CalcSubtype.TRIG)
check('三角默认 sin', trig16.node.trig_func == 'sin')
# 切换函数
ed16._set_trig_func(trig16, 'cos')
check('切换函数 cos', trig16.node.trig_func == 'cos')
check('积木标签显示 cos', trig16._label() == 'cos')
# 清除函数
ed16._set_trig_func(trig16, None)
check('清除函数未定义', trig16.node.trig_func is None)
# 检查左侧面板有函数列表（点击后）
ed16._set_calc_type(trig16, CalcSubtype.TRIG)
ed16._show_calc_type_panel(trig16)
func_btns = []
for i in range(ed16._left_panel.count()):
    w = ed16._left_panel.itemAt(i).widget()
    if isinstance(w, QPushButton):
        func_btns.append(w.text())
check('函数名列表显示', any(f in func_btns for f in
      ['sin', 'cos', 'tan', 'arcsin']))
ed16.close()

# ---------- 28. 右键空白创建：选类型直接在右键位置创建 ----------
from PyQt6.QtCore import QPointF
ed17 = CustomCalcEditor()
# 直接测 _right_click_create（菜单 exec 模态无法 offscreen 测）
before = len(ed17._scene.items())
bud17 = BlockNode(type=BlockType.CALC)
ed17._right_click_pos = QPointF(150, 120)
ed17._right_click_create(bud17)
items = ed17._scene.items()
check('右键创建积木数 +1', len(items) == before + 1)
check('右键创建在指定位置',
      abs(items[-1].pos().x() - 150) < 1
      and abs(items[-1].pos().y() - 120) < 1)
ed17.close()

# ---------- 29. 输出积木：方向过滤 + 位置显示 ----------
# 10 计划：输出到行/列两个按钮都显示（不按脚本方向过滤）
ed18 = CustomCalcEditor(direction='以列为单位')
out18 = ed18._scene.add_block(make_output())
ed18._show_output_panel(out18)
opts18 = []
for i in range(ed18._left_panel.count()):
    w = ed18._left_panel.itemAt(i).widget()
    if isinstance(w, QPushButton):
        opts18.append(w.text())
check('输出面板三按钮都显示',
      '剪贴板' in opts18 and '输出到行' in opts18 and '输出到列' in opts18)
check('未选时显示输出?', out18._output_label() == '输出?')
# 设置剪贴板输出
out18.node.output_target = OutputTarget.CLIPBOARD
out18.node.output_index = None
check('剪贴板显示', out18._output_label() == '剪贴板')
# 设置列输出
out18.node.output_target = OutputTarget.COL
out18.node.output_index = 2   # 列C
check('列C显示', out18._output_label() == '列C')
ed18.close()
# 行方向：同样三按钮都显示
ed19 = CustomCalcEditor(direction='以行为单位')
out19 = ed19._scene.add_block(make_output())
ed19._show_output_panel(out19)
opts19 = []
for i in range(ed19._left_panel.count()):
    w = ed19._left_panel.itemAt(i).widget()
    if isinstance(w, QPushButton):
        opts19.append(w.text())
check('行方向输出面板三按钮都显示',
      '剪贴板' in opts19 and '输出到行' in opts19 and '输出到列' in opts19)
out19.node.output_target = OutputTarget.ROW
out19.node.output_index = 4   # 行5
check('行5显示', out19._output_label() == '行5')
ed19.close()

# ---------- 30. 多级嵌套尺寸传播 + 同级重排 ----------
ed20 = CustomCalcEditor()
# 输出积木 → 括号 → 计算元胚
out20 = ed20._scene.add_block(make_output())
paren20 = ed20._scene.add_block(make_paren())
ed20._attach_to_slot(paren20.node, out20.interfaces[0], paren20)
bud20 = BlockNode(type=BlockType.CALC)
bud20_item = ed20._scene.add_block(bud20)
ed20._attach_to_slot(bud20, paren20.interfaces[0], bud20_item)
w_out_before = out20.boundingRect().width()
# 胚 → 指数（变宽），应传播到括号 + 输出积木
ed20._set_calc_type(bud20_item, CalcSubtype.EXP)
check('类型切换后输出积木变宽（多级传播）',
      out20.boundingRect().width() > w_out_before)
# 括号应包住变宽的指数
check('括号包住变宽子积木',
      paren20.boundingRect().width() >= bud20_item.boundingRect().width())
# 同级重排：括号链里再加一个积木，变宽后右边的应移动
# 指数 → 数元（变窄），括号应收缩
w_paren_before = paren20.boundingRect().width()
ed20._set_calc_type(bud20_item, CalcSubtype.NUM)
check('切回数元括号收缩（反向传播）',
      paren20.boundingRect().width() < w_paren_before)
ed20.close()

# ---------- 31. 链中类型切换不破坏布局 + 空隙填补 ----------
ed21 = CustomCalcEditor()
paren21 = ed21._scene.add_block(make_paren())
a21 = BlockNode(type=BlockType.CALC); ai21 = ed21._scene.add_block(a21)
ed21._attach_to_slot(a21, paren21.interfaces[0], ai21)
b21 = BlockNode(type=BlockType.CALC); bi21 = ed21._scene.add_block(b21)
ed21._attach_to_slot(b21, paren21.interfaces[0], bi21)
# 链 = [a, 符号占位, b, 占位]
# a 胚 → 数元（变宽），同级 b 应右移且不重叠
x_b_before = bi21.pos().x()
ed21._set_calc_type(ai21, CalcSubtype.NUM)
check('切换后 b 右移（同级重排）', bi21.pos().x() > x_b_before)
check('切换后 a/b 不重叠',
      ai21.pos().x() + ai21.boundingRect().width() < bi21.pos().x() + 1)
# 问题4：链中空隙填补——拖出 b，链 = [a, 符号占位, 占位(空值位), 占位?]
# 简化：直接构造链 [a, 符号, 占位值位] 再补
ed21._on_detach(bi21, paren21)
print('拖出b后链:', [(c.type.value, c.is_interface) for c in paren21.node.children])
# 在空缺处（占位）补新积木
gap_iface = [i for i in paren21.interfaces if i.kind == 'slot'][0]
new_c = BlockNode(type=BlockType.CALC); nc_item = ed21._scene.add_block(new_c)
ed21._attach_to_slot(new_c, gap_iface, nc_item)
print('补空缺后链:', [(c.type.value, c.is_interface) for c in paren21.node.children])
check('空缺处补入新积木（非链尾）',
      paren21.node.children.index(new_c) < len(paren21.node.children) - 1)
ed21.close()

# ---------- 32. 清除定义回到胚态 + 符号即点即生效 ----------
ed22 = CustomCalcEditor()
num22 = ed22._scene.add_block(make_calc_num())
ed22._clear_block_def(num22)
check('清除定义后回计算元胚态',
      num22.node.calc_subtype is None)
# 符号选择即点即生效（面板清空 = 取消选中）
sym22 = BlockNode(type=BlockType.SYMBOL)
sym_item22 = ed22._scene.add_block(sym22)
ed22._set_symbol(sym22, '+', refresh=sym_item22)
check('符号即点即生效', sym22.sym_value == '+')
# 面板已刷新（显示提示，无符号按钮）
panel_texts = []
for i in range(ed22._left_panel.count()):
    w = ed22._left_panel.itemAt(i).widget()
    if isinstance(w, QLabel):
        panel_texts.append(w.text())
check('符号选择后面板无符号按钮（取消选中）',
      not any(t in panel_texts for t in ['当前符号', '运算符号']))
ed22.close()

# ---------- 33. 括号链式接口拒绝符号元 + 删除链中积木立即重排 ----------
ed23 = CustomCalcEditor()
paren23 = ed23._scene.add_block(make_paren())
# 问题1：链尾接口拒绝符号元
sym23 = BlockNode(type=BlockType.SYMBOL)
sym_item23 = ed23._scene.add_block(sym23)
ed23._attach_to_slot(sym23, paren23.interfaces[0], sym_item23)
check('链尾接口拒绝符号元（链保持空）',
      len(paren23.node.children) == 1
      and paren23.node.children[0].is_interface)
# 问题2：删除链中积木 → 同级立即移动 + 空缺生成接口
a23 = BlockNode(type=BlockType.CALC); ai23 = ed23._scene.add_block(a23)
ed23._attach_to_slot(a23, paren23.interfaces[0], ai23)
b23 = BlockNode(type=BlockType.CALC); bi23 = ed23._scene.add_block(b23)
ed23._attach_to_slot(b23, paren23.interfaces[0], bi23)
x_b_before = bi23.pos().x()
ed23._delete_block(ai23)   # 删除第一个值积木
# 删除后链 = [占位, 符号, b, 占位]，b 应左移
check('删除链中积木后同级左移',
      bi23.pos().x() < x_b_before)
# 删除位置生成加号接口（非末尾占位）
has_gap = any(i.slot == ('children', 0) for i in paren23.interfaces)
check('删除位置生成接口', has_gap)
# 在空缺接口补新积木 → 补在原位置
gap_iface23 = [i for i in paren23.interfaces
               if i.kind == 'slot' and i.slot != ('children', 3)][0]
c23 = BlockNode(type=BlockType.CALC); ci23 = ed23._scene.add_block(c23)
ed23._attach_to_slot(c23, gap_iface23, ci23)
check('空缺处补入新积木', c23 in paren23.node.children
      and paren23.node.children.index(c23) < len(paren23.node.children) - 1)
ed23.close()

# ---------- 34. 固定槽积木（指数/对数/三角/计数/检定）随子积木流式扩展 ----------
ed24 = CustomCalcEditor()
big24 = ed24._scene.add_block(make_paren())
for i in range(3):
    nd24 = make_calc_num()
    nd24.data = DataDef(kind=InputKind.CONST, value=float(i + 1))
    ni24 = ed24._scene.add_block(nd24)
    ed24._attach_to_slot(nd24, big24.interfaces[0], ni24)
big_w24 = big24.boundingRect().width()
from custom_calc.model import make_calc_exp as mk_exp
exp24_node = mk_exp(); exp24 = ed24._scene.add_block(exp24_node)
w0 = exp24.boundingRect().width()
ed24._attach_block_to_num(exp24_node.children[0], big24,
                          refresh=exp24.interfaces[0])
w1 = exp24.boundingRect().width()
check('指数随大子积木扩展', w1 > w0 + 100)
# 指数指数接口流式到子积木之后（x > 大括号宽）
exp_iface1 = [i for i in exp24.interfaces if i.slot == ('children', 1)][0]
check('指数接口流式到子积木后',
      exp_iface1.pos().x() > big_w24)
ed24.close()

# ---------- 35. 数元接口接入积木拖出后 label 还原 ----------
ed25 = CustomCalcEditor()
log25a = make_calc_log(); log25a_item = ed25._scene.add_block(log25a)
log25b = make_calc_log(); log25b_item = ed25._scene.add_block(log25b)
# 对数 A 的第一个数元接口接入对数 B
ed25._attach_block_to_num(log25a_item.node.children[0], log25b_item,
                          refresh=log25a_item.interfaces[0])
check('接入后数元接口显示 log', log25a_item.interfaces[0]._num_label() == 'log')
# 拖出对数 B（拖拽路径）
log25b_item.setPos(500, 300)
ed25._scene._on_drag_finished(log25b_item, log25b_item.scenePos())
check('拖出后数元接口还原数元?',
      log25a_item.interfaces[0]._num_label() == '数元?')
check('拖出后 data.block 清空',
      log25a_item.node.children[0].data.block is None)
ed25.close()

# ---------- 36. 固定槽原生子数元无清除定义 + 输出接口右侧 ----------
ed26 = CustomCalcEditor()
exp26 = ed26._scene.add_block(make_calc_exp())
ed26._on_interface_clicked(exp26.interfaces[0])   # 点底数数元接口
btns26 = [ed26._left_panel.itemAt(i).widget().text()
          for i in range(ed26._left_panel.count())
          if ed26._left_panel.itemAt(i).widget()]
check('固定槽数元接口无清除定义', '清除定义' not in btns26)
out26 = ed26._scene.add_block(make_output())
check('输出积木接口在右侧',
      out26.interfaces[0].pos().x() > out26._layout_width() * 0.5)
ed26.close()

# ---------- 37. 引擎位置对齐：同位置对齐 / 不同位置报错 / 剪贴板 / 计数全表 / 检定拒绝 ----------
from custom_calc.engine import EvalContext, Evaluator, TableValue, CalcError
from custom_calc.model import BlockType as _BT

def mk_ev(model, direction='对列处理'):
    ctx = EvalContext(model, direction)
    return Evaluator(ctx)

# 同位置列对齐：两列纯数据位置一致（行0,2,3 有值，行1 都是 x）
m37a = SpreadsheetModel()
m37a.load_2d([
    ['1', '10'],
    ['x', 'x'],
    ['2', '30'],
    ['3', '40'],
])
ev37a = mk_ev(m37a)
col0 = ev37a._ctx.get_col(0)
col1 = ev37a._ctx.get_col(1)
check('列取数带位置', col0.positions == [0, 2, 3] and col0.values == [1.0, 2.0, 3.0])
check('同位置列对齐无差异', col0.align_positions(col1) is None)
# 同位置相加 → 位置保留
r37 = ev37a._binop('+', col0, col1)
check('同位置相加结果', isinstance(r37, TableValue)
      and r37.positions == [0, 2, 3] and r37.values == [11.0, 32.0, 43.0])
# 不同位置列 → 报错
m37b = SpreadsheetModel()
m37b.load_2d([
    ['1', '10'],
    ['2', '20'],
    ['x', '30'],
    ['3', ''],
])
ev37b = mk_ev(m37b)
b0, b1 = ev37b._ctx.get_col(0), ev37b._ctx.get_col(1)
check('不同位置列检测',
      ev37b._ctx.get_col(0).positions == [0, 1, 3]
      and ev37b._ctx.get_col(1).positions == [0, 1, 2])
try:
    ev37b._binop('+', b0, b1)
    check('不同位置相加报错', False)
except CalcError as e:
    check('不同位置相加报错', '位置未对齐' in str(e))
# 表+常数广播
r37b = ev37b._binop('+', b0, 100)
check('表+常数广播', isinstance(r37b, TableValue)
      and r37b.values == [101.0, 102.0, 103.0])
# 剪贴板一维解析
cb1d = EvalContext.parse_clipboard('5\t6\t7', by_row=True)
check('剪贴板横排一维', cb1d.kind == 'clipboard1d' and cb1d.values == [5.0, 6.0, 7.0])
cb2d = EvalContext.parse_clipboard('1\t2\n3\t4', by_row=True)
check('剪贴板二维', cb2d.kind == 'grid' and len(cb2d.values) == 4)
# 剪贴板一维 + 表：格数相同顺序对齐
ev37c = mk_ev(m37a)
col0c = ev37c._ctx.get_col(0)
r37c = ev37c._binop('+', col0c, cb1d)
check('剪贴板一维+表顺序对齐',
      isinstance(r37c, TableValue) and r37c.values == [6.0, 8.0, 10.0])
# 检定接受一维表（10 计划）：左是列数元（表）→ 逐元素输出 0/1 表
from custom_calc.model import make_check as _mk_check, DataDef, InputKind
ck37 = _mk_check()
ck37.children[0] = make_calc_num_const(0.0)
ck37.children[0].data = DataDef(kind=InputKind.COL, index=0)   # 列0（表）
ck37.children[1] = BlockNode(type=BlockType.SYMBOL, sym_value='>', sym_kind=SymKind.LOGIC)
ck37.children[2] = make_calc_num_const(0.0)
r37d = ev37a.evaluate(ck37)
check('检定接受表逐元素', isinstance(r37d, TableValue)
      and r37d.values == [1.0, 1.0, 1.0])   # 1,2,3 > 0 → 全 1
# 计数：表+常数
from custom_calc.model import make_count as _mk_count
cnt37 = _mk_count()
cnt37.children[0] = make_calc_num_const(0.0)
cnt37.children[0].data = DataDef(kind=InputKind.COL, index=0)   # 列0（表）
cnt37.children[1] = BlockNode(type=BlockType.SYMBOL, sym_value='>', sym_kind=SymKind.LOGIC)
cnt37.children[2] = make_calc_num_const(1.0)
check('计数表+常数', ev37a.evaluate(cnt37) == 2)   # 1,2,3 > 1 → 2,3 两个

# ---------- 37.5 剪贴板二维拒绝 / 全表数元计数 / 剪贴板二维+全表位置对齐 ----------
# 剪贴板二维 + 列表 → 拒绝（09 规格：剪贴板二维与表对 → 报错拒绝）
try:
    ev37a._binop('+', col0, cb2d)
    check('剪贴板二维+表拒绝', False)
except CalcError as e:
    check('剪贴板二维+表拒绝', True)
# 计数：全表数元（WHOLE_TABLE）+ 单值常数 → 广播逐格计数
cnt_whole = _mk_count()
cnt_whole.children[0] = make_calc_num()
cnt_whole.children[0].data = DataDef(kind=InputKind.WHOLE_TABLE)
cnt_whole.children[1] = BlockNode(type=BlockType.SYMBOL, sym_value='>',
                                  sym_kind=SymKind.LOGIC)
cnt_whole.children[2] = make_calc_num_const(1.5)
# m37a 全表纯数据 [1,10,2,30,3,40]，>1.5 的 5 个
check('计数全表数元+常数', ev37a.evaluate(cnt_whole) == 5)
# 计数：剪贴板二维 + 全表数元 → 位置完全对齐才能计数（相等成功）
m37d = SpreadsheetModel()
m37d.load_2d([['1', '2'], ['3', '4']])   # 全表 2x2，与剪贴板 2x2 位置一致
ev37d = mk_ev(m37d)
cnt_cb = _mk_count()
cnt_cb.children[0] = make_calc_num()
cnt_cb.children[0].data = DataDef(kind=InputKind.WHOLE_TABLE)
cnt_cb.children[1] = BlockNode(type=BlockType.SYMBOL, sym_value='=',
                               sym_kind=SymKind.LOGIC)
cnt_cb.children[2] = make_calc_num()
cnt_cb.children[2].data = DataDef(kind=InputKind.CLIPBOARD)
from PyQt6.QtWidgets import QApplication as _QA
_QA.clipboard().setText('1\t2\n3\t4')   # 与全表完全一致 → 4 格相等
check('剪贴板二维+全表位置对齐计数', ev37d.evaluate(cnt_cb) == 4)
# 位置不等 → 拒绝
m37e = SpreadsheetModel()
m37e.load_2d([['1', '2'], ['3', '4'], ['5', '6']])   # 3x2，剪贴板 2x2 位置不齐
ev37e = mk_ev(m37e)
_QA.clipboard().setText('1\t2\n3\t4')
try:
    ev37e.evaluate(cnt_cb)
    check('剪贴板二维+全表位置不等拒绝', False)
except CalcError as e:
    check('剪贴板二维+全表位置不等拒绝', True)

# ---------- 38. 数元定义面板：「整个表格」仅计数积木接口显示（09 步骤 5） ----------
ed38 = CustomCalcEditor(direction='以列为单位')
cnt38 = ed38._scene.add_block(_mk_count())
num_iface38 = None
for iface in cnt38.interfaces:
    if iface.kind == 'num' and iface.slot == ('children', 0):
        num_iface38 = iface
check('计数积木左数元接口存在', num_iface38 is not None)
ed38._on_interface_clicked(num_iface38)
btns38 = []
for i in range(ed38._left_panel.count()):
    w = ed38._left_panel.itemAt(i).widget()
    if isinstance(w, QPushButton):
        btns38.append(w.text())
check('计数接口显示整个表格', '整个表格' in btns38)
# 定义整个表格 + 标签显示
ed38._num_define(cnt38.node.children[0], 'whole_table', refresh=num_iface38)
check('定义整个表格', cnt38.node.children[0].data.kind == InputKind.WHOLE_TABLE)
check('接口标签显示整个表格', num_iface38._num_label() == '整个表格')
ed38.close()
# 普通数元积木自身 → 不显示
ed38b = CustomCalcEditor(direction='以列为单位')
num38 = ed38b._scene.add_block(make_calc_num())
ed38b._on_item_clicked(num38, 'left')
btns38b = []
for i in range(ed38b._left_panel.count()):
    w = ed38b._left_panel.itemAt(i).widget()
    if isinstance(w, QPushButton):
        btns38b.append(w.text())
check('普通数元不显示整个表格', '整个表格' not in btns38b)
ed38b.close()
# 指数积木的数元接口 → 不显示
ed38c = CustomCalcEditor(direction='以列为单位')
exp38 = ed38c._scene.add_block(make_calc_exp())
exp_iface38 = None
for iface in exp38.interfaces:
    if iface.kind == 'num' and iface.slot == ('children', 0):
        exp_iface38 = iface
ed38c._on_interface_clicked(exp_iface38)
btns38c = []
for i in range(ed38c._left_panel.count()):
    w = ed38c._left_panel.itemAt(i).widget()
    if isinstance(w, QPushButton):
        btns38c.append(w.text())
check('指数数元接口不显示整个表格', '整个表格' not in btns38c)
ed38c.close()
# 检定积木数元接口 → 不显示（全表是计数积木专用）
ed38d = CustomCalcEditor(direction='以列为单位')
ck38 = ed38d._scene.add_block(make_check())
ck_iface38 = None
for iface in ck38.interfaces:
    if iface.kind == 'num' and iface.slot == ('children', 0):
        ck_iface38 = iface
ed38d._on_interface_clicked(ck_iface38)
btns38d = []
for i in range(ed38d._left_panel.count()):
    w = ed38d._left_panel.itemAt(i).widget()
    if isinstance(w, QPushButton):
        btns38d.append(w.text())
check('检定数元接口不显示整个表格', '整个表格' not in btns38d)
ed38d.close()
# 脚本剪贴板输出：行方向 → Tab 横排；列方向 → 换行竖排（规格七）
from scripts.自定义运算脚本 import CustomCalcScript as _CCS
from custom_calc.engine import TableValue as _TV
_QA.clipboard().setText('')
_CCS._to_clipboard(_TV([0, 1, 2], [11.0, 12.0, 13.0], 'row'), by_row=True)
check('剪贴板行方向横排', _QA.clipboard().text() == '11\t12\t13')
_CCS._to_clipboard(_TV([0, 1, 2], [11.0, 12.0, 13.0], 'col'), by_row=False)
check('剪贴板列方向竖排', _QA.clipboard().text() == '11\n12\n13')
_CCS._to_clipboard(14.0, by_row=True)
check('剪贴板单值', _QA.clipboard().text() == '14')

# ---------- 39. 链尾占位求值 + validate 提前报错（用户反馈 3 问题） ----------
# 39.1 括号链含链尾占位（编辑器 _append_to_chain 恒补）→ 应正常求值（跳过占位）
m39 = SpreadsheetModel()
m39.load_2d([['1', '10', '100'], ['2', '20', '200'],
             ['3', '30', '300'], ['4', '40', '400']])
ev39 = Evaluator(EvalContext(m39, '以列为单位'))
paren39 = make_paren()
b39 = make_calc_num(); b39.data = DataDef(kind=InputKind.COL, index=1)
c39 = make_calc_num(); c39.data = DataDef(kind=InputKind.COL, index=2)
paren39.children = [b39, make_symbol('+', SymKind.OP), c39,
                    BlockNode(type=BlockType.CALC, state='pending_interface')]
r39 = ev39.evaluate(paren39)
check('链尾占位跳过求值', isinstance(r39, TableValue)
      and r39.values == [110.0, 220.0, 330.0, 440.0])
# 39.2 validate：链内未定义符号 / 未定义数元 / 计算元胚 → 提前报错
v_paren = make_paren()
v_paren.children = [make_calc_num(), BlockNode(type=BlockType.SYMBOL),
                    make_calc_num(),
                    BlockNode(type=BlockType.CALC, state='pending_interface')]
errs39 = validate_blocks([v_paren])
check('validate 链内未定义符号', any('未定义符号' in e for e in errs39))
v_paren2 = make_paren()
v_paren2.children = [make_calc_num(), make_symbol('+', SymKind.OP),
                     make_calc_num(),
                     BlockNode(type=BlockType.CALC, state='pending_interface')]
errs39b = validate_blocks([v_paren2])
check('validate 链内未定义数元', any('数元接口未定义' in e for e in errs39b))
v_paren3 = make_paren()
v_paren3.children = [BlockNode(type=BlockType.CALC),
                     make_symbol('+', SymKind.OP),
                     make_calc_num(),
                     BlockNode(type=BlockType.CALC, state='pending_interface')]
errs39c = validate_blocks([v_paren3])
check('validate 链内计算元胚', any('计算元未选择数据类型' in e for e in errs39c))
# 39.3 validate：计数全表 + 表 → 提前报错；检定 + 表 → 提前报错
cnt39 = make_count()
cnt39.children[0] = make_calc_num()
cnt39.children[0].data = DataDef(kind=InputKind.WHOLE_TABLE)
cnt39.children[1] = make_symbol('>=', SymKind.LOGIC)
cnt39.children[2] = make_calc_num()
cnt39.children[2].data = DataDef(kind=InputKind.ROW, index=2)
errs39d = validate_blocks([cnt39])
check('validate 计数全表+表', any('只能与单值常数比较' in e for e in errs39d))
ck39 = make_check()
ck39.children[0] = make_calc_num()
ck39.children[0].data = DataDef(kind=InputKind.COL, index=0)
ck39.children[1] = make_symbol('>', SymKind.LOGIC)
ck39.children[2] = make_calc_num_const(0.0)
errs39e = validate_blocks([ck39])
check('validate 检定+表可接受', not any('检定积木不接受表格' in e for e in errs39e))
# 39.4 输出积木嵌入未定义计算元 → 变数元后尺寸应包裹（不回缩）
ed39 = CustomCalcEditor(direction='以列为单位')
out39 = ed39._scene.add_block(make_output())
out39.node.output_target = OutputTarget.COL
out39.node.output_index = 0
cal39 = ed39._scene.add_block(BlockNode(type=BlockType.CALC))
ed39._attach_to_slot(cal39.node, out39.interfaces[0], cal39)
w_embryo = out39.boundingRect().width()
ed39._set_calc_type(cal39, CalcSubtype.NUM)
w_num = out39.boundingRect().width()
check('输出积木包裹未定义数元', w_num >= w_embryo and w_num > 80)
check('输出积木尺寸正常', w_num >= 100)
ed39.close()

# ---------- 40. 符号元接入拒绝 + validate 数据级预检（用户反馈问题 1/2） ----------
# 40.1 输出积木/数元接口/数元右键 接入符号元 → 拒绝
from custom_calc.model import make_calc_exp as _mk_exp40, make_output as _mk_out40
ed40 = CustomCalcEditor(direction='以列为单位')
out40 = ed40._scene.add_block(_mk_out40())
out40.node.output_target = OutputTarget.CLIPBOARD
sym40 = ed40._scene.add_block(make_symbol('+', SymKind.OP))
n_before40 = len(out40.node.children)
ed40._attach_to_slot(sym40.node, out40.interfaces[0], sym40)
check('输出积木拒绝符号元', len(out40.node.children) == n_before40)
ed40.close()
ed40b = CustomCalcEditor(direction='以列为单位')
exp40 = ed40b._scene.add_block(_mk_exp40())
exp_iface40 = [i for i in exp40.interfaces
               if i.kind == 'num' and i.slot == ('children', 0)][0]
sym40b = ed40b._scene.add_block(make_symbol('-', SymKind.OP))
ch_before40 = list(exp40.node.children)
ed40b._attach_to_slot(sym40b.node, exp_iface40, sym40b)
check('数元接口拒绝符号元', exp40.node.children[0] is ch_before40[0])
ed40b.close()
ed40c = CustomCalcEditor(direction='以列为单位')
num40 = ed40c._scene.add_block(make_calc_num())
sym40c = ed40c._scene.add_block(make_symbol('+', SymKind.OP))
ed40c._attach_block_to_num(num40.node, sym40c)
check('数元右键拒绝符号元', num40.node.data.block is None)
ed40c.close()
# 40.2 validate 数据级预检：计数 列G>列H 位置不对齐 → 提前报错
m40 = SpreadsheetModel()
m40.load_2d([
    ['1', '2', '3', '4', '5', '6', '10', '100'],
    ['x', '2', '3', '4', '5', '6', '20', '200'],
    ['3', 'x', '3', '4', '5', '6', '30', '300'],
    ['4', '2', 'x', '4', '5', '6', '40', '400'],
])
cnt40 = make_count()
cnt40.children[0] = make_calc_num()
cnt40.children[0].data = DataDef(kind=InputKind.COL, index=6)   # 列G：行0,1,2,3
cnt40.children[1] = make_symbol('>', SymKind.LOGIC)
cnt40.children[2] = make_calc_num()
cnt40.children[2].data = DataDef(kind=InputKind.COL, index=7)   # 列H：行0,1,2,3（对齐）
errs40 = validate_blocks([cnt40], model=m40, direction='以列为单位')
check('对齐计数不误报', not any('对齐' in e for e in errs40))
cnt40b = make_count()
cnt40b.children[0] = make_calc_num()
cnt40b.children[0].data = DataDef(kind=InputKind.COL, index=6)   # 列G：行0,1,2,3
cnt40b.children[1] = make_symbol('>', SymKind.LOGIC)
cnt40b.children[2] = make_calc_num()
cnt40b.children[2].data = DataDef(kind=InputKind.COL, index=0)   # 列A：行0,2,3
errs40b = validate_blocks([cnt40b], model=m40, direction='以列为单位')
check('计数位置不对齐提前报', any('位置未对齐' in e and '计数' in e for e in errs40b))
errs40c = validate_blocks([cnt40b])
check('不传 model 不报对齐', not any('对齐' in e for e in errs40c))
# 40.3 链式表+表对齐预检
paren40 = make_paren()
b40 = make_calc_num(); b40.data = DataDef(kind=InputKind.COL, index=6)
c40 = make_calc_num(); c40.data = DataDef(kind=InputKind.COL, index=0)
paren40.children = [b40, make_symbol('+', SymKind.OP), c40,
                    BlockNode(type=BlockType.CALC, state='pending_interface')]
errs40d = validate_blocks([paren40], model=m40, direction='以列为单位')
check('链式表+表对齐预检', any('括号链' in e and '位置未对齐' in e for e in errs40d))
# 40.4 其他漏检：输出直连计算元胚 / 空括号 / 三角未定义 / 剪贴板为空
outp40 = _mk_out40()
outp40.output_target = OutputTarget.CLIPBOARD
outp40.children[0] = BlockNode(type=BlockType.CALC)
check('输出直连计算元胚', any('计算元未选择数据类型' in e
                          for e in validate_blocks([outp40])))
emp40 = make_paren()
check('空括号报错', any('缺少计算元' in e for e in validate_blocks([emp40])))
from custom_calc.model import make_calc_trig as _mk_trig40
trig40 = _mk_trig40(); trig40.trig_func = None
check('三角未定义报错', any('三角' in e for e in validate_blocks([trig40])))
num_cb40 = make_calc_num(); num_cb40.data = DataDef(kind=InputKind.CLIPBOARD)
_QA.clipboard().setText('')
check('剪贴板为空报错', any('剪贴板为空' in e for e in validate_blocks([num_cb40])))

# ---------- 41. 复制嵌套积木 + 撤销/重做 + 删除自身（用户反馈） ----------
# 41.1 整体复制：嵌套子积木图形完整（不再只剩接口）
from custom_calc.editor import BlockItem as _BI41
ed41 = CustomCalcEditor(direction='以列为单位')
p41 = make_paren()
a41 = make_calc_num(); a41.data = DataDef(kind=InputKind.CONST, value=1.0)
b41 = make_calc_num(); b41.data = DataDef(kind=InputKind.CONST, value=2.0)
p41.children = [a41, make_symbol('+', SymKind.OP), b41,
                BlockNode(type=BlockType.CALC, state='pending_interface')]
item41 = ed41._scene.add_block(p41)
ed41._build_child_items(p41, item41)   # 建子积木图形（等价编辑器内嵌状态）
ed41._copy_block(item41, whole=True)
new_items41 = [it for it in ed41._scene.items()
               if it is not item41 and it.parentItem() is None]
check('整体复制产生新积木', len(new_items41) == 1)
new_paren41 = new_items41[0]
child_blocks41 = [c for c in new_paren41.childItems() if isinstance(c, _BI41)]
check('整体复制嵌套图形完整', len(child_blocks41) == 3)   # 数元+符号+数元
# 41.2 自身复制：不带嵌套（空括号，无子积木图形）
ed41._copy_block(item41, whole=False)
self_items41 = [it for it in ed41._scene.items()
                if it not in (item41, new_paren41)
                and it.parentItem() is None]
check('自身复制产生新积木', len(self_items41) == 1)
self_paren41 = self_items41[0]
check('自身复制无嵌套', len(self_paren41.node.children) == 1
      and self_paren41.node.children[0].is_interface)
# 41.3 撤销/重做：撤销最近一次自身复制 → 恢复；重做 → 再现
def _top_items41():
    return [it for it in ed41._scene.items() if it.parentItem() is None]
ed41._undo()
check('撤销恢复', len(_top_items41()) == 2)   # item41 + new_paren41
ed41._redo()
check('重做再现', len(_top_items41()) == 3)
# 41.4 删除自身：本体删除，子积木保留为自由积木
ed41._delete_self(new_paren41)
survivors41 = [it for it in ed41._scene.items() if it.parentItem() is None]
check('删除自身后子积木仍自由存在', len(survivors41) >= 2)
ed41.close()

# ---------- 42. 撤销中间态修复 + 操作栏按钮无残留（用户反馈） ----------
# 42.1 添加积木到括号后 Ctrl+Z：回到添加前（无自由积木残留，不脱离）
ed42 = CustomCalcEditor(direction='以列为单位')
p42 = ed42._scene.add_block(make_paren())
ed42._push_snapshot()   # 模拟 _create_and_embed 入口 push
iface42 = p42.interfaces[0]
n42 = ed42._scene.add_block(make_calc_num())
ed42._attach_to_slot(n42.node, iface42, n42)
check('嵌入后无顶层自由积木', len([it for it in ed42._scene.items()
                                if it.parentItem() is None]) == 1)
ed42._undo()
tops42 = [it for it in ed42._scene.items() if it.parentItem() is None]
check('撤销后回到添加前（无残留）', len(tops42) == 1
      and len(tops42[0].node.children) == 1
      and tops42[0].node.children[0].is_interface)
ed42.close()
# 42.2 连续选中积木：复制/删除按钮各 1 个（_clear_left 清子布局）
ed42b = CustomCalcEditor(direction='以列为单位')
n42b = ed42b._scene.add_block(make_calc_num())
for _ in range(3):
    ed42b._select_block_mode(n42b, 'self')

def _collect_widgets(panel):
    out = []
    for i in range(panel.count()):
        it = panel.itemAt(i)
        if it.widget():
            out.append(it.widget())
        elif it.layout():
            sub = it.layout()
            for j in range(sub.count()):
                si = sub.itemAt(j)
                if si.widget():
                    out.append(si.widget())
    return out

btns42 = [w.text() for w in _collect_widgets(ed42b._left_panel)
          if isinstance(w, QPushButton)]
check('复制按钮无残留', btns42.count('复制自身') == 1)
check('删除按钮无残留', btns42.count('删除自身') == 1)
ed42b.close()
# 42.3 撤销/重做保持积木位置（node.x/y 同步 + 恢复定位）
from PyQt6.QtCore import QPointF as _QPF42
ed42c = CustomCalcEditor(direction='以列为单位')
n42c = ed42c._scene.add_block(make_calc_num(), _QPF42(100, 100))
n42c.setPos(230, 170)   # 拖动 → _on_item_moved 同步 node.x/y
check('拖动同步 node 位置', n42c.node.x == 230 and n42c.node.y == 170)
ed42c._delete_block(n42c)
ed42c._undo()
tops42c = [it for it in ed42c._scene.items() if it.parentItem() is None]
check('撤销恢复数量', len(tops42c) == 1)
check('撤销恢复保持位置',
      abs(tops42c[0].pos().x() - 230) < 1 and abs(tops42c[0].pos().y() - 170) < 1)
ed42c.close()

# ---------- 43. 一维表计数/检定范围模式（10 计划） ----------
# 43.1 范围计数：列范围 → 水平表；行范围 → 垂直表；单范围；反向报错
from custom_calc.model import make_count as _mk_count43
m43 = SpreadsheetModel()
m43.load_2d([
    ['1', '10', '100'],
    ['2', '20', '200'],
    ['3', '30', '300'],
])
ev43 = Evaluator(EvalContext(m43, '以列为单位'))

def _cnt43(axis, start, end, logic='>', right=5.0):
    """构造计数积木：左数元为范围输入（10 计划 v2 数元特化）。"""
    n = _mk_count43()
    left = make_calc_num()
    left.data = DataDef(kind=InputKind.RANGE, range_axis=axis,
                        range_start=start, range_end=end)
    n.children = [left, make_symbol(logic, SymKind.LOGIC),
                  make_calc_num_const(right)]
    return ev43.evaluate(n)

r43a = _cnt43('col', 0, 2)
check('列范围计数水平表', isinstance(r43a, TableValue) and r43a.kind == 'row'
      and r43a.positions == [0, 1, 2] and r43a.values == [0.0, 3.0, 3.0])
r43b = _cnt43('row', 0, 2)
check('行范围计数垂直表', isinstance(r43b, TableValue) and r43b.kind == 'col'
      and r43b.positions == [0, 1, 2] and r43b.values == [2.0, 2.0, 2.0])
r43c = _cnt43('col', 1, 1)
check('单列范围(起始=结尾)', isinstance(r43c, TableValue) and r43c.values == [3.0])
try:
    _cnt43('col', 2, 0)
    check('反向范围报错', False)
except CalcError as e:
    check('反向范围报错', '顺序错误' in str(e))
# 43.2 方向检测：列表 + 行表 → 拒绝
cnt43d = _mk_count43()
l43 = make_calc_num(); l43.data = DataDef(kind=InputKind.COL, index=0)
r43 = make_calc_num(); r43.data = DataDef(kind=InputKind.ROW, index=0)
cnt43d.children = [l43, make_symbol('>', SymKind.LOGIC), r43]
try:
    ev43.evaluate(cnt43d)
    check('列表+行表拒绝', False)
except CalcError as e:
    check('列表+行表拒绝', '方向不同' in str(e))
# 43.3 任务 2 场景：计数(列范围>3) → 检定(>=3) → 0/1 表 → 脚本输出行16
m43b = SpreadsheetModel()
m43b.load_2d([
    ['组别', '一', '二', '三', '四', '五', '六'],
    ['数据1', '3.5', '2.7', '3.6', '3.5', '3.4', '2.9'],
    ['数据2', '4.5', '4.6', '2.8', '2.9', '5.0', '5.1'],
    ['数据3', '1.3', '1.2', '1.6', '1.6', '1.8', '2.0'],
    ['数据4', '0.3', '0.02', '0.4', '0.8', '1.2', '1.5'],
    ['数据5', '10.7', '10.7', '10.7', '10.7', '10.7', '10.7'],
])
ev43b = Evaluator(EvalContext(m43b, '以列为单位'))
inner43 = _mk_count43()
inner_left43 = make_calc_num()
inner_left43.data = DataDef(kind=InputKind.RANGE, range_axis='col',
                            range_start=1, range_end=6)
inner43.children = [inner_left43, make_symbol('>', SymKind.LOGIC),
                    make_calc_num_const(3.0)]
chk43 = make_check()
chk43.children = [inner43, make_symbol('>=', SymKind.LOGIC),
                  make_calc_num_const(3.0)]
r43e = ev43b.evaluate(chk43)
check('任务2：检定(计数(列范围>3)>=3)',
      isinstance(r43e, TableValue) and r43e.kind == 'row'
      and r43e.positions == [1, 2, 3, 4, 5, 6]
      and r43e.values == [1.0, 0.0, 0.0, 0.0, 1.0, 0.0])
# 脚本写回：输出到行16（index 15）→ 水平表写列1-6
out43 = make_output_node()
out43.output_target = OutputTarget.ROW
out43.output_index = 15   # 用户视角行16（0-based 15）
out43.children[0] = chk43
s43 = CustomCalcScript()
p43 = {'direction': '以列为单位', 'custom_blocks': [out43]}
check('任务2脚本 run ok', s43.run(m43b, p43) is None)
check('任务2写回行16六列',
      [m43b.value(15, c) for c in range(1, 7)] == ['1', '0', '0', '0', '1', '0'])
# 43.4 validate：范围顺序错误 / 范围右侧表 / 输出方向预检
cnt_bad43 = make_count()
b_left43 = make_calc_num()
b_left43.data = DataDef(kind=InputKind.RANGE, range_axis='col',
                        range_start=3, range_end=1)
cnt_bad43.children = [b_left43, make_symbol('>', SymKind.LOGIC),
                      make_calc_num_const(0.0)]
errs43 = validate_blocks([cnt_bad43])
check('validate 范围顺序错误', any('顺序错误' in e for e in errs43))
cnt_rgt43 = make_count()
r_left43 = make_calc_num()
r_left43.data = DataDef(kind=InputKind.RANGE, range_axis='col',
                        range_start=0, range_end=1)
rr43 = make_calc_num(); rr43.data = DataDef(kind=InputKind.COL, index=2)
cnt_rgt43.children = [r_left43, make_symbol('>', SymKind.LOGIC), rr43]
errs43b = validate_blocks([cnt_rgt43])
check('validate 范围右侧须单值', any('单值常数' in e for e in errs43b))
out_dir43 = make_output_node()
out_dir43.output_target = OutputTarget.COL   # 列范围计数输出水平表 → 输出到列 方向不一致
out_dir43.output_index = 10
out_dir43.children[0] = inner43
errs43c = validate_blocks([out_dir43], model=m43b, direction='以列为单位')
check('validate 输出方向预检（列范围→输出到列）',
      any('方向不一致' in e for e in errs43c))
# 43.5 数元面板：范围按钮 + 二级页面 + 数元 RANGE 校验
from custom_calc.editor import CustomCalcEditor as _CCE43
ed43 = _CCE43(direction='以列为单位')
num_ed43 = ed43._scene.add_block(make_calc_num())
ed43._on_item_clicked(num_ed43, 'left')
btns43 = [w.text() for w in _collect_widgets(ed43._left_panel)
          if isinstance(w, QPushButton)]
check('数元面板范围按钮', '范围-以列为单位' in btns43)
num_ed43.node.data = DataDef(kind=InputKind.RANGE, range_axis='col',
                             range_start=1, range_end=6)
check('数元标签显示范围', '范围' in num_ed43._label())
ed43.close()

# ---------- 44. 操作栏固定宽度 + 范围二级面板不叠加（用户反馈） ----------
ed44 = CustomCalcEditor(direction='以行为单位')
num44 = ed44._scene.add_block(make_calc_num())
ed44._on_item_clicked(num44, 'left')
ed44._num_define(num44.node, 'range', refresh=num44)
ed44._show_range_panel(num44.node, num44)
ed44._show_range_panel(num44.node, num44)   # 重复调用 → 不叠加
btns44 = [w.text() for w in _collect_widgets(ed44._left_panel)
          if isinstance(w, QPushButton)]
check('二级面板起始各1', btns44.count('起始行: 未设') == 1
      and btns44.count('结尾行: 未设') == 1)
ed44._show_num_define_panel(num44.node, num44)
ed44._show_num_define_panel(num44.node, num44)
btns44b = [w.text() for w in _collect_widgets(ed44._left_panel)
           if isinstance(w, QPushButton)]
check('返回数元面板不叠加', btns44b.count('范围-以行为单位') == 1)
ed44.close()

# ---------- 45. 输入形式审计：各积木对 单值/一维/二维 的处理（审计 2026-08-22） ----------
# 45.1 剪贴板一维 + 二维 → 拒绝；二维 + 一维 → 明确报"不能混算"
m45 = SpreadsheetModel()
m45.load_2d([['1', '10'], ['2', '20'], ['3', '30']])
ev45 = Evaluator(EvalContext(m45, '以列为单位'))
c45 = ev45._ctx.get_col(0)
cb1d45 = EvalContext.parse_clipboard('1\t2\t3', by_row=True)
cb2d45 = EvalContext.parse_clipboard('1\t2\n3\t4', by_row=True)
try:
    ev45._binop('+', cb1d45, cb2d45)
    check('剪贴板1D+2D 拒绝', False)
except CalcError as e:
    check('剪贴板1D+2D 拒绝', '不能与二维表混算' in str(e))
try:
    ev45._binop('+', c45, cb2d45)
    check('二维+一维明确报错', False)
except CalcError as e:
    check('二维+一维明确报错', '二维表不能与一维表混算' in str(e))
try:
    ev45._binop('+', c45, ev45._ctx.get_whole_table())
    check('全表+一维明确报错', False)
except CalcError as e:
    check('全表+一维明确报错', '二维表不能与一维表混算' in str(e))
# 45.2 剪贴板一维 + 列 → 顺序对齐（各积木）
r45 = ev45._binop('+', c45, cb1d45)
check('剪贴板1D+列顺序对齐', isinstance(r45, TableValue)
      and r45.values == [2.0, 4.0, 6.0])
# 45.3 计数/检定：剪贴板1D 参与正常（顺序对齐/逐元素）
cnt45 = make_count()
cnt45.children = [make_calc_num(), make_symbol('>', SymKind.LOGIC),
                  make_calc_num_const(0.0)]
cnt45.children[0].data = DataDef(kind=InputKind.COL, index=0)
chk45 = make_check()
chk45.children = [make_calc_num(), make_symbol('>', SymKind.LOGIC),
                  make_calc_num_const(0.0)]
chk45.children[0].data = DataDef(kind=InputKind.COL, index=0)
QApplication.clipboard().setText('1\t2\t3')
check('计数(列>剪贴板1D)', ev45.evaluate(cnt45) == 3)
r45c = ev45.evaluate(chk45)
check('检定(列>常数)逐元素', isinstance(r45c, TableValue)
      and r45c.values == [1.0, 1.0, 1.0])
# 45.4 检定接全表（grid）→ 逐元素 0/1 grid 表
chk45g = make_check()
chk45g.children = [make_calc_num(), make_symbol('>', SymKind.LOGIC),
                   make_calc_num_const(1.0)]
chk45g.children[0].data = DataDef(kind=InputKind.WHOLE_TABLE)
r45g = ev45.evaluate(chk45g)
check('检定(全表>常数)grid表', isinstance(r45g, TableValue)
      and r45g.kind == 'grid' and r45g.values == [0.0, 1.0, 1.0, 1.0, 1.0, 1.0])
# 45.5 整体删除递归移除子积木（含嵌套）
from custom_calc.editor import BlockItem as _BI45
ed45 = CustomCalcEditor(direction='以列为单位')
p45 = ed45._scene.add_block(make_paren())
a45 = make_calc_num(); a45.data = DataDef(kind=InputKind.CONST, value=1.0)
p45.node.children = [a45, make_symbol('+', SymKind.OP),
                     make_calc_num_const(2.0),
                     BlockNode(type=BlockType.CALC, state='pending_interface')]
ed45._build_child_items(p45.node, p45)
n_child45 = len([c for c in p45.childItems() if isinstance(c, _BI45)])
check('嵌套子积木存在', n_child45 == 3)
ed45._delete_block(p45)
remaining45 = [it for it in ed45._scene.items() if it.parentItem() is None]
check('整体删除递归移除子积木', len(remaining45) == 0)
ed45.close()

# ---------- 46. 剪贴板二维与全表检测地位等同（用户确认） ----------
cnt46 = make_count()
l46 = make_calc_num(); l46.data = DataDef(kind=InputKind.CLIPBOARD)
r46 = make_calc_num(); r46.data = DataDef(kind=InputKind.COL, index=0)
cnt46.children = [l46, make_symbol('>', SymKind.LOGIC), r46]
_QA46 = QApplication
_QA46.clipboard().setText('1\t2\n3\t4')   # 剪贴板二维
errs46 = validate_blocks([cnt46])
check('validate 剪贴板二维+列', any('二维输入' in e for e in errs46))
_QA46.clipboard().setText('1\t2\t3')      # 剪贴板一维 → 不报二维错误
errs46b = validate_blocks([cnt46])
check('validate 剪贴板一维+列不误报', not any('二维输入' in e for e in errs46b))
cnt46c = make_count()
l46c = make_calc_num(); l46c.data = DataDef(kind=InputKind.CLIPBOARD)
r46c = make_calc_num(); r46c.data = DataDef(kind=InputKind.WHOLE_TABLE)
cnt46c.children = [l46c, make_symbol('>', SymKind.LOGIC), r46c]
_QA46.clipboard().setText('1\t2\n3\t4')
errs46c = validate_blocks([cnt46c])
check('validate 剪贴板二维+全表不报（grid+grid）',
      not any('二维输入' in e for e in errs46c))

# ---------- 47. 编辑器窗口支持最大化/窗口化（用户请求小优化） ----------
from PyQt6.QtCore import Qt as _Qt47
ed47 = CustomCalcEditor(direction='以列为单位')
flags47 = ed47.windowFlags()
check('编辑器有最大化按钮',
      bool(flags47 & _Qt47.WindowType.WindowMaximizeButtonHint))
ed47.show()
ed47.showMaximized()
app.processEvents()
check('最大化后窗口放大', ed47.width() >= 900 or ed47.height() >= 600)
ed47.close()

# ---------- 48. 积木配置：序列化 round-trip + 保存/打开 ----------
from custom_calc.editor import (_node_to_dict, _node_from_dict,
                                _data_to_dict, _data_from_dict)
# 48.1 构造复杂树：输出→括号[数元(列B)+范围计数(列范围>3)] + 接入积木
t48 = make_output()
t48.output_target = OutputTarget.ROW
t48.output_index = 16
p48 = make_paren()
a48 = make_calc_num(); a48.data = DataDef(kind=InputKind.COL, index=1)
cnt48 = make_count()
cnt48.children = [make_calc_num(), make_symbol('>', SymKind.LOGIC),
                  make_calc_num_const(3.0)]
cnt48.children[0].data = DataDef(kind=InputKind.RANGE, range_axis='col',
                                 range_start=1, range_end=6)
p48.children = [a48, make_symbol('+', SymKind.OP), cnt48,
                BlockNode(type=BlockType.CALC, state='pending_interface')]
t48.children = [p48]
d48 = _node_to_dict(t48)
import json as _json48
s48 = _json48.dumps(d48, ensure_ascii=False)
t48b = _node_from_dict(_json48.loads(s48))
check('序列化 round-trip 类型', t48b.type == BlockType.OUTPUT
      and t48b.children[0].type == BlockType.PAREN)
check('序列化 round-trip 数元', t48b.children[0].children[0].data.kind
      == InputKind.COL and t48b.children[0].children[0].data.index == 1)
check('序列化 round-trip 范围', t48b.children[0].children[2].children[0].data.kind
      == InputKind.RANGE and t48b.children[0].children[2].children[0].data.range_axis
      == 'col' and t48b.children[0].children[2].children[0].data.range_end == 6)
check('序列化 round-trip 输出', t48b.output_target == OutputTarget.ROW
      and t48b.output_index == 16)
# 48.2 编辑器保存/打开（monkeypatch 配置文件夹到工作区内临时目录——
# 系统 %TEMP% 受沙箱限制，需用可写工作区）
import tempfile as _tmp48
from PyQt6.QtWidgets import QInputDialog, QFileDialog, QMessageBox as _QMB48
QMessageBox.question = staticmethod(
    lambda *a, **k: QMessageBox.StandardButton.Yes)
_tmp_dir48 = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          '_tmp_cfg48')
os.makedirs(_tmp_dir48, exist_ok=True)
ed48 = CustomCalcEditor(direction='以列为单位', model=SpreadsheetModel())
ed48._config_folder = lambda: _tmp_dir48
# 保存：QInputDialog 返回文件名
QInputDialog.getText = staticmethod(lambda *a, **k: ('配置A', True))
ed48._push_snapshot()
# 用编辑器场景构建一个数元积木再保存
n48 = ed48._scene.add_block(make_calc_num())
n48.node.data = DataDef(kind=InputKind.CONST, value=7.0)
ed48._save_config()
import os as _os48
saved48 = _os48.path.join(_tmp_dir48, '配置A.json')
check('保存生成配置文件', _os48.path.exists(saved48))
# 打开：monkeypatch QFileDialog 返回保存的文件
ed48._scene.clear_blocks()
QFileDialog.getOpenFileName = staticmethod(
    lambda *a, **k: (saved48, '积木配置 (*.json)'))
ed48._load_config()
tops48 = [it for it in ed48._scene.items() if it.parentItem() is None]
check('打开还原积木', len(tops48) == 1
      and tops48[0].node.data.kind == InputKind.CONST
      and tops48[0].node.data.value == 7.0)
# 空选状态有 保存/打开 按钮
ed48._on_blank_clicked()
btns48 = [w.text() for w in _collect_widgets(ed48._left_panel)
          if isinstance(w, QPushButton)]
check('空选显示配置按钮', '保存当前积木配置' in btns48
      and '打开积木配置' in btns48)
ed48.close()

print('ALL CUSTOM CALC SMOKE TESTS PASSED')
print('ALL CUSTOM CALC SMOKE TESTS PASSED')
print('ALL CUSTOM CALC SMOKE TESTS PASSED')
