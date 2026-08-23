"""加法脚本冒烟测试 — 验证面板控件、识别逻辑、控制器状态机、脚本执行。"""
import os
import sys

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
sys.path.insert(0, r'D:\Cloude Code\自制表格软件\代码输出库\源码')

from PyQt6.QtWidgets import QApplication
app = QApplication([])

from views.side_panel import SidePanel
from models.spreadsheet_model import SpreadsheetModel
from views.spreadsheet_grid import SpreadsheetGrid
from views.status_bar import StatusBar
from controllers.script_controller import ScriptController
from scripts.base_script import OperandInputStep, OutputTargetStep
from scripts.加法脚本 import AddScript


def check(name, cond):
    if not cond:
        raise AssertionError(f'FAIL: {name}')
    print('PASS:', name)


# ---------- 1. 面板控件冒烟 ----------
panel = SidePanel()
panel.show_operand_slots(2, 'column')
check('operand slots count == 2', panel.operand_slot_count == 2)
panel.set_slot_display(0, '语文')
panel.show_slot_editor(1)
panel.reset_slot(0)
panel.show_output_buttons()
check('output buttons shown', panel._clip_btn is not None and panel._pick_btn is not None)

# 布局顺序：新加的槽位在确定按钮之前
panel.show_operand_slots(2, 'column')
panel.show_confirm_button(enabled=False)
panel.add_operand_slot()
ci = panel._script_btn_area.indexOf(panel._confirm_row)
li = panel._script_btn_area.indexOf(panel._operand_rows[-1])
check('added slot above confirm button', li >= 0 and ci >= 0 and li < ci)
# 删除槽位 + 索引重排
panel._remove_operand_slot(1)
check('remove slot count == 2', panel.operand_slot_count == 2)
check('indexes renumbered', panel._operand_slots[0]._index == 0
      and panel._operand_slots[1]._index == 1)
# 常数输入态保留箭头：可重新打开菜单
slot0 = panel._operand_slots[0]
check('arrow btn has no duplicate text symbol', slot0._menu_btn.text() == '')
slot0.set_display('语文')
check('normal text shown', slot0._text_btn.text() == '语文' and not slot0._text_btn.isHidden())
slot0.show_editor()
check('editor keeps arrow visible', not slot0._menu_btn.isHidden())
check('text hidden while editing', slot0._text_btn.isHidden())
slot0.set_display('5')
check('display restored after constant', slot0._text_btn.text() == '5')
slot0.show_editor()
slot0.cancel_constant()
check('cancel keeps previous text', slot0._text_btn.text() == '5'
      and not slot0._text_btn.isHidden())
slot0.reset()
check('reset back to placeholder', slot0._text_btn.text() == '选择计算元')

# ---------- 2. 识别函数单元测试 ----------
rec = ScriptController._recognize_cells
check('normal with title', rec(['语文', '1', '2', '3']) == ('语文', 0, [1.0, 2.0, 3.0], None))
check('no title', rec(['1', '2', '3']) == (None, 0, [1.0, 2.0, 3.0], None))
check('empty cell rejected', rec(['1', '', '3'])[3] is not None)
check('leading empty skipped', rec(['', '语文', '1', '2', '3']) == ('语文', 1, [1.0, 2.0, 3.0], None))
check('too many titles rejected', rec(['语文', '数学', '1'])[3] is not None)
check('empty data rejected', rec([])[3] is not None)
check('title ratio 25% ok', rec(['语文', '1', '2', '3'])[1] == 0)
check('single title whitelist 50% ok', rec(['语文', '1']) == ('语文', 0, [1.0], None))
check('single title whitelist 33% ok', rec(['语文', '1', '2']) == ('语文', 0, [1.0, 2.0], None))
check('two titles 50% rejected', rec(['语文', '数学', '1', '2'])[3] is not None)
check('two titles 67% rejected', rec(['语文', '数学', '1'])[3] is not None)
check('text mid-data becomes title', rec(['1', '备注', '2', '3'])[0] == '备注')

# ---------- 3. 控制器状态机 ----------
model = SpreadsheetModel()
model.load_2d([
    ['语文', '数学'],
    ['1', '2'],
    ['3', '4'],
    ['5', '6'],
    ['7', '8'],
])
grid = SpreadsheetGrid()
grid.setModel(model)
status = StatusBar()
ctrl = ScriptController(model, grid, status, panel)
ctrl._running = True

ctrl._params['direction'] = '以列为单位'
step = OperandInputStep('test')
ctrl._begin_operand_input(step)
ctrl._pending_slot = 0
ctrl._on_pick_column(0)  # 列A: 语文/1/3/5/7
check('pick column A', ctrl._operand_slots[0]['display'] == '语文'
      and ctrl._operand_slots[0]['values'] == [1.0, 3.0, 5.0, 7.0])
ctrl._pending_slot = 1
ctrl._on_pick_column(1)  # 列B: 数学/2/4/6/8
check('pick column B', ctrl._operand_slots[1]['display'] == '数学'
      and ctrl._operand_slots[1]['values'] == [2.0, 4.0, 6.0, 8.0])

# 删除联动：面板删除第 2 个槽位 → 控制器同步
panel._remove_operand_slot(1)
check('ctrl synced after remove', len(ctrl._operand_slots) == 1
      and ctrl._operand_slots[0]['display'] == '语文')
# 重新添加并填回
ctrl._operand_slots.append(None)
panel.add_operand_slot()
ctrl._pending_slot = 1
ctrl._on_pick_column(1)
check('refill after remove', ctrl._operand_slots[1]['values'] == [2.0, 4.0, 6.0, 8.0])

# 输入态下重新选择能变回去
panel._operand_slots[0].show_editor()
panel._operand_slots[0]._emit('clear')  # 模拟点箭头菜单「清除」
check('clear exits editor back to placeholder',
      panel._operand_slots[0]._text_btn.text() == '选择计算元'
      and panel._operand_slots[0]._text_btn.isHidden() is False)
panel._operand_slots[0].show_editor()
panel._operand_slots[0]._emit('column')  # 模拟点箭头菜单「点选列」
ctrl._pending_slot = 0
ctrl._on_pick_column(0)
check('pick column exits editor', panel._operand_slots[0]._text_btn.text() == '语文'
      and panel._operand_slots[0]._text_btn.isHidden() is False)

# 手动输入常数：通过真实菜单项触发，顶部提示文字随之变化；Esc 取消后恢复
def trigger_menu(slot, text):
    """编程触发计算元框菜单里的某个菜单项（模拟真实点击）。"""
    for a in slot._menu_btn.menu().actions():
        if text in a.text():
            a.trigger()
            return True
    return False

slot0b = panel._operand_slots[0]
check('menu has constant action', trigger_menu(slot0b, '手动输入常数'))
check('constant prompt shown via real menu action', '请输入常数' in panel._script_prompt.text())
check('editor shown via real menu action', not slot0b._edit.isHidden())
ctrl._on_operand_constant_cancelled(0)
check('prompt restored after cancel', panel._script_prompt.text() == step.prompt)
# 常数无效时提示
trigger_menu(slot0b, '手动输入常数')
ctrl._on_operand_constant(0, 'abc')
check('invalid constant prompt', '常数无效' in panel._script_prompt.text())
# 输入有效常数完成：提示恢复 + 槽位数据更新（显示为纯数字，不带"常数"前缀）
ctrl._on_operand_constant(0, '10')
check('constant stored and prompt restored',
      ctrl._operand_slots[0]['display'] == '10'
      and panel._script_prompt.text() == step.prompt)

# Enter 在输入框聚焦时：只提交常数，不触发确定（即使确定按钮可用）
from PyQt6.QtWidgets import QMainWindow
from PyQt6.QtCore import QEvent, Qt
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtTest import QTest
w2 = QMainWindow()
panel2 = SidePanel()
w2.setCentralWidget(panel2)
w2.show()
panel2.show_operand_slots(2, 'column')
panel2.show_confirm_button(enabled=True)
s2 = panel2._operand_slots[0]
panel2.show_slot_editor(0)
check('enter shortcuts disabled while editing',
      not any(sc.isEnabled() for sc in panel2._confirm_shortcuts))
s2._edit.setText('7')
s2._edit.setFocus()
submitted, confirmed = [], []
s2.constant_submitted.connect(lambda i, t: submitted.append((i, t)))
panel2.confirm_clicked.connect(lambda: confirmed.append(1))
QTest.keyClick(s2._edit, Qt.Key.Key_Return)  # 走真实事件分发（含快捷键系统）
app.processEvents()
check('enter submits constant (real event path)', submitted == [(0, '7')])
check('enter does not trigger confirm', confirmed == [])
# 模拟控制器提交成功后的面板回调（set_slot_display 关闭编辑态）
panel2.set_slot_display(0, '常数 7')
check('enter shortcuts re-enabled after edit', all(sc.isEnabled() for sc in panel2._confirm_shortcuts))

# 用户场景回归：槽位0 输入常数并提交 → 槽位1 点列 → 确定按钮变亮
panel3 = SidePanel()
w3 = QMainWindow()
w3.setCentralWidget(panel3)
w3.show()
ctrl3 = ScriptController(model, grid, status, panel3)
ctrl3._running = True
ctrl3._params['direction'] = '以列为单位'
ctrl3._begin_operand_input(OperandInputStep('t'))
panel3._operand_slots[0]._emit('constant')
ctrl3._on_operand_constant(0, '3')
check('constant committed shows in slot', panel3._operand_slots[0]._text_btn.text() == '3')
ctrl3._pending_slot = 1
ctrl3._on_pick_column(1)
check('confirm enabled after constant + column', panel3._confirm_btn.isEnabled())

# 真实常数槽位（控制器生成）→ 点确定不崩溃、数据结构完整
panel4 = SidePanel()
w4 = QMainWindow()
w4.setCentralWidget(panel4)
w4.show()
ctrl4 = ScriptController(model, grid, status, panel4)
ctrl4._running = True
ctrl4._params['direction'] = '以列为单位'
ctrl4._begin_operand_input(OperandInputStep('t'))
panel4._operand_slots[0]._emit('constant')
ctrl4._on_operand_constant(0, '5')
check('constant slot has full keys',
      all(k in ctrl4._operand_slots[0]
          for k in ('kind', 'value', 'display', 'title', 'title_idx', 'values')))
ctrl4._pending_slot = 1
ctrl4._on_pick_column(1)
ctrl4._on_operands_confirmed()  # 之前这里会 KeyError 崩溃
check('confirm works with real constant slot',
      'operands' in ctrl4._params
      and ctrl4._params['operands']['slots'][0]['kind'] == 'constant'
      and ctrl4._params['operands']['slots'][1]['kind'] == 'column')

# 恢复槽位 0 为列（后续对齐/执行需要两个列计算元）
ctrl._operand_slots[0] = {'kind': 'column', 'index': 0, 'title': '语文',
                          'title_idx': 0, 'display': '语文', 'values': [1.0, 3.0, 5.0, 7.0]}
panel._operand_slots[0].set_display('语文')

ctrl._on_operands_confirmed()
check('params operands stored', 'operands' in ctrl._params
      and ctrl._params['operands']['data_len'] == 4)

# 未对齐场景：B 槽位只剩 1 个值
ctrl._operand_slots[1] = {'kind': 'column', 'index': 1, 'title': '数学',
                          'title_idx': 0, 'display': '数学', 'values': [2.0]}
ctrl._on_operands_confirmed()
check('misalign blocked', ctrl._params['operands']['slots'][1]['values'] == [2.0, 4.0, 6.0, 8.0])

# 重建正常 operands（模拟确认通过后的 params）
ctrl._params['operands'] = {
    'slots': [
        {'kind': 'column', 'index': 0, 'title': '语文', 'title_idx': 0,
         'display': '语文', 'values': [1.0, 3.0, 5.0, 7.0]},
        {'kind': 'column', 'index': 1, 'title': '数学', 'title_idx': 0,
         'display': '数学', 'values': [2.0, 4.0, 6.0, 8.0]},
    ],
    'data_len': 4,
    'title_idx': 0,
    'has_title': True,
}

# ---------- 4. 脚本执行 ----------
s = AddScript()
ctrl._params['output'] = {'target': 'column', 'index': 2}
err = s.run(model, ctrl._params)
check('run to column ok', err is None)
check('title cell untouched', model.value(0, 2) == '')
check('C1 = 1+2', model.value(1, 2) == '3')
check('C2 = 3+4', model.value(2, 2) == '7')
check('C4 = 7+8', model.value(4, 2) == '15')

ctrl._params['output'] = {'target': 'clipboard'}
err = s.run(model, ctrl._params)
check('run to clipboard ok', err is None)
cb = QApplication.clipboard().text()
check('clipboard has leading blank', cb == '\n3\n7\n11\n15')

# 常数参与
ctrl._params['operands']['slots'].append(
    {'kind': 'constant', 'value': 100, 'display': '常数 100',
     'title': None, 'title_idx': 0, 'values': []})
ctrl._params['output'] = {'target': 'column', 'index': 3}
err = s.run(model, ctrl._params)
check('constant added ok', err is None)
check('D1 = 3+100', model.value(1, 3) == '103')

# 按行运算
ctrl._params['direction'] = '以行为单位'
ctrl._params['operands'] = {
    'slots': [
        {'kind': 'row', 'index': 1, 'title': None, 'title_idx': 0,
         'display': '行2', 'values': [1.0, 2.0]},
        {'kind': 'row', 'index': 2, 'title': None, 'title_idx': 0,
         'display': '行3', 'values': [3.0, 4.0]},
    ],
    'data_len': 2,
    'title_idx': 0,
    'has_title': False,
}
ctrl._params['output'] = {'target': 'row', 'index': 10}
err = s.run(model, ctrl._params)
check('run to row ok', err is None)
check('row11 colA = 1+3 (no title, starts at 0)', model.value(10, 0) == '4')
check('row11 colB = 2+4', model.value(10, 1) == '6')

# 剪贴板输出与运算方向一致 + 无标题不空标题格
ctrl._params['direction'] = '以列为单位'
ctrl._params['operands'] = {
    'slots': [
        {'kind': 'column', 'index': 5, 'title': None, 'title_idx': 0,
         'display': '列F', 'values': [1.0, 2.0]},
        {'kind': 'column', 'index': 6, 'title': None, 'title_idx': 0,
         'display': '列G', 'values': [10.0, 20.0]},
    ],
    'data_len': 2,
    'title_idx': 0,
    'has_title': False,
}
ctrl._params['output'] = {'target': 'clipboard'}
err = s.run(model, ctrl._params)
check('no-title clipboard no blank line', QApplication.clipboard().text() == '11\n22')
ctrl._params['output'] = {'target': 'column', 'index': 7}
err = s.run(model, ctrl._params)
check('no-title column starts at row 0', model.value(0, 7) == '11' and model.value(1, 7) == '22')

# 按行方向剪贴板：一行 Tab 分隔；有标题时空出开头标题格
ctrl._params['direction'] = '以行为单位'
ctrl._params['operands'] = {
    'slots': [
        {'kind': 'row', 'index': 1, 'title': None, 'title_idx': 0,
         'display': '行2', 'values': [1.0, 2.0]},
        {'kind': 'row', 'index': 2, 'title': None, 'title_idx': 0,
         'display': '行3', 'values': [3.0, 4.0]},
    ],
    'data_len': 2,
    'title_idx': 0,
    'has_title': False,
}
ctrl._params['output'] = {'target': 'clipboard'}
err = s.run(model, ctrl._params)
check('row-direction clipboard is one tab line', QApplication.clipboard().text() == '4\t6')
ctrl._params['operands']['has_title'] = True
err = s.run(model, ctrl._params)
check('row clipboard with title blanks first cell', QApplication.clipboard().text() == '\t4\t6')

print('ALL SMOKE TESTS PASSED')
