"""乘法脚本冒烟测试 — 覆盖面板 DecimalsSlot、保留小数位数状态机、识别、执行。"""
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
from scripts.base_script import OperandInputStep
from scripts.乘法脚本 import MultiplyScript


def check(name, cond):
    if not cond:
        raise AssertionError(f'FAIL: {name}')
    print('PASS:', name)


# ---------- 1. 面板：DecimalsSlot 显示与布局顺序 ----------
panel = SidePanel()
panel.show_operand_slots(2, 'column', with_decimals=True)
panel.show_confirm_button(enabled=False)
check('decimals slot shown', panel._decimals_slot is not None
      and panel._decimals_slot._text_btn.text() == '保留位数：默认（自动）')
check('decimals slot above confirm', panel._script_btn_area.indexOf(panel._decimals_row)
      < panel._script_btn_area.indexOf(panel._confirm_row))

# 新增计算元插到保留行之前
panel.add_operand_slot()
li = panel._script_btn_area.indexOf(panel._operand_rows[-1])
di = panel._script_btn_area.indexOf(panel._decimals_row)
ci = panel._script_btn_area.indexOf(panel._confirm_row)
check('added slot above decimals row', li >= 0 and di >= 0 and ci >= 0 and li < di < ci)

# 加法脚本不开 decimals：无保留行，新增框仍插到确定按钮之前
panel2 = SidePanel()
panel2.show_operand_slots(2, 'column', with_decimals=False)
panel2.show_confirm_button(enabled=False)
panel2.add_operand_slot()
check('no decimals row without flag', panel2._decimals_slot is None)
check('add still above confirm without flag',
      panel2._script_btn_area.indexOf(panel2._operand_rows[-1])
      < panel2._script_btn_area.indexOf(panel2._confirm_row))

# 手动输入态：箭头保留、文本隐藏、Enter 快捷键让位
w = None
from PyQt6.QtWidgets import QMainWindow
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
w = QMainWindow()
panel3 = SidePanel()
w.setCentralWidget(panel3)
w.show()
panel3.show_operand_slots(2, 'column', with_decimals=True)
panel3.show_confirm_button(enabled=True)
ds = panel3._decimals_slot
panel3.show_decimals_editor()
check('editor keeps arrow visible', not ds._menu_btn.isHidden())
check('text hidden while editing', ds._text_btn.isHidden())
check('enter shortcuts disabled while editing',
      not any(sc.isEnabled() for sc in panel3._confirm_shortcuts))
submitted, confirmed = [], []
ds.digits_submitted.connect(lambda t: submitted.append(t))
panel3.confirm_clicked.connect(lambda: confirmed.append(1))
ds._edit.setText('3')
ds._edit.setFocus()
QTest.keyClick(ds._edit, Qt.Key.Key_Return)  # 走真实事件分发（含快捷键系统）
app.processEvents()
check('enter submits digits (real event path)', submitted == ['3'])
check('enter does not trigger confirm', confirmed == [])
# Esc 取消：原文本保留
ds._edit.setText('9')
QTest.keyClick(ds._edit, Qt.Key.Key_Escape)
app.processEvents()
check('esc keeps previous text', ds._text_btn.text() == '保留位数：默认（自动）'
      and not ds._text_btn.isHidden())
panel3.set_decimals_display('保留位数：3 位')
check('display restored after submit', ds._text_btn.text() == '保留位数：3 位')
check('enter shortcuts re-enabled after edit', all(sc.isEnabled() for sc in panel3._confirm_shortcuts))

# ---------- 2. 识别：逐位小数位数 ----------
parse = ScriptController._parse_numeric_cells
check('decimals parsed per cell', parse(['语文', '1.5', '2.4', '3'])
      == ('语文', 0, [1.5, 2.4, 3.0], [1, 1, 0], None))
check('trailing zero kept (2.50 -> 2)', parse(['2.50', '1'])
      == (None, 0, [2.5, 1.0], [2, 0], None))
check('negative decimal count', parse(['-1.25'])[3] == [2])
check('integer zero decimals', parse(['3', '4'])[3] == [0, 0])
check('empty cell rejected', parse(['1', '', '3'])[4] is not None)
check('title ratio rejected', parse(['语文', '数学', '1'])[4] is not None)
# 旧签名 _recognize_cells 兼容（加法测试依赖）
check('legacy recognize 4-tuple', ScriptController._recognize_cells(['语文', '1', '2'])
      == ('语文', 0, [1.0, 2.0], None))

# ---------- 3. 控制器：保留小数位数状态机 ----------
model = SpreadsheetModel()
model.load_2d([
    ['语文', '数学'],
    ['1.5', '2'],
    ['2.4', '0.5'],
    ['3', '1.75'],
])
grid = SpreadsheetGrid()
grid.setModel(model)
status = StatusBar()
ctrl = ScriptController(model, grid, status, panel)
ctrl._running = True
ctrl._params['direction'] = '以列为单位'
step = OperandInputStep('test', decimals=True)
ctrl._begin_operand_input(step)
check('decimals default auto', ctrl._decimals_mode == 'auto' and ctrl._decimals_digits is None)
check('decimals slot in panel', panel._decimals_slot is not None)

# 点选列 A：decimals 存入槽位
ctrl._pending_slot = 0
ctrl._on_pick_column(0)
check('column slot has decimals', ctrl._operand_slots[0]['values'] == [1.5, 2.4, 3.0]
      and ctrl._operand_slots[0]['decimals'] == [1, 1, 0])
# 常数槽位：从文本推导位数
ctrl._pending_slot = -1
ctrl._on_operand_constant(1, '2.50')
check('constant slot decimals from text', ctrl._operand_slots[1]['kind'] == 'constant'
      and ctrl._operand_slots[1]['decimals'] == [2])

# 手动模式：非法输入拒绝、超范围拒绝、合法提交
ctrl._on_decimals_mode('manual')
check('manual prompt shown', '保留小数位数' in panel._script_prompt.text())
check('editor open in manual mode', panel._decimals_slot.is_editing)
ctrl._on_decimals_digits('abc')
check('non-digit rejected', '位数无效' in panel._script_prompt.text())
ctrl._on_decimals_digits('11')
check('out of range rejected', '超出范围' in panel._script_prompt.text())
ctrl._on_decimals_digits('2')
check('manual digits stored', ctrl._decimals_mode == 'manual' and ctrl._decimals_digits == 2)
check('manual display set', panel._decimals_slot._text_btn.text() == '保留位数：2 位')
check('editor closed after submit', not panel._decimals_slot.is_editing)
# 切回自动
ctrl._on_decimals_mode('auto')
check('back to auto', ctrl._decimals_mode == 'auto' and ctrl._decimals_digits is None
      and panel._decimals_slot._text_btn.text() == '保留位数：默认（自动）')
# Esc 取消恢复提示
ctrl._on_decimals_mode('manual')
ctrl._on_decimals_cancelled()
check('cancel restores prompt', panel._script_prompt.text() == step.prompt)

# 确定：params 组装 decimals
ctrl._operand_slots[1] = {'kind': 'column', 'index': 1, 'title': '数学',
                          'title_idx': 0, 'display': '数学',
                          'values': [2.0, 0.5, 1.75], 'decimals': [0, 1, 2]}
ctrl._on_operands_confirmed()
check('params decimals assembled', ctrl._params['operands']['decimals']
      == {'mode': 'auto', 'digits': None})

# ---------- 4. 脚本执行 ----------
s = MultiplyScript()

def run_params(slots, direction='以列为单位', target=None, mode='auto', digits=None,
               has_title=True, data_len=None, title_idx=0):
    p = {
        'direction': direction,
        'operands': {
            'slots': slots,
            'data_len': data_len if data_len is not None else len(slots[0]['values']),
            'title_idx': title_idx,
            'has_title': has_title,
            'decimals': {'mode': mode, 'digits': digits},
        },
        'output': target,
    }
    return p

A = {'kind': 'column', 'index': 0, 'title': '语文', 'title_idx': 0,
     'display': '语文', 'values': [1.5, 2.4, 3.0], 'decimals': [1, 1, 0]}
B = {'kind': 'column', 'index': 1, 'title': '数学', 'title_idx': 0,
     'display': '数学', 'values': [2.0, 0.5, 1.75], 'decimals': [0, 1, 2]}

# 自动模式：逐位置取位数最多者
ctrl._params = run_params([A, B], target={'target': 'column', 'index': 2})
err = s.run(model, ctrl._params)
check('auto run ok', err is None)
check('title cell untouched', model.value(0, 2) == '')
check('C1 = 1.5*2 (n=1) -> 3', model.value(1, 2) == '3')
check('C2 = 2.4*0.5 (n=1) -> 1.2', model.value(2, 2) == '1.2')
check('C3 = 3*1.75 (n=2) -> 5.25', model.value(3, 2) == '5.25')

# 手动 2 位：0.1*0.1 消除浮点误差
ctrl._params = run_params([
    {'kind': 'constant', 'value': 0.1, 'display': '0.1',
     'title': None, 'title_idx': 0, 'values': [], 'decimals': [1]},
    {'kind': 'constant', 'value': 0.1, 'display': '0.1',
     'title': None, 'title_idx': 0, 'values': [], 'decimals': [1]},
], has_title=False, data_len=1,
    target={'target': 'clipboard'}, mode='manual', digits=2)
err = s.run(model, ctrl._params)
check('manual 2 digits 0.01', QApplication.clipboard().text() == '0.01')

# 手动 2 位：整数不补零（无标题，避免空标题行）
ctrl._params = run_params([A, B], has_title=False, target={'target': 'clipboard'},
                          mode='manual', digits=2)
err = s.run(model, ctrl._params)
check('manual keeps int as int', QApplication.clipboard().text() == '3\n1.2\n5.25')

# 常数广播（自动：常数 1 位 + 列 1 位 -> 1 位）
C = {'kind': 'constant', 'value': 2.0, 'display': '2',
     'title': None, 'title_idx': 0, 'values': [], 'decimals': [0]}
ctrl._params = run_params([A, C], target={'target': 'column', 'index': 3})
err = s.run(model, ctrl._params)
check('constant broadcast ok', err is None)
check('D1 = 1.5*2 -> 3', model.value(1, 3) == '3')
check('D2 = 2.4*2 -> 4.8', model.value(2, 3) == '4.8')

# 常数 0：结果全 0
Z = {'kind': 'constant', 'value': 0.0, 'display': '0',
     'title': None, 'title_idx': 0, 'values': [], 'decimals': [0]}
ctrl._params = run_params([A, Z], target={'target': 'clipboard'})
err = s.run(model, ctrl._params)
check('zero constant gives zeros', QApplication.clipboard().text() == '\n0\n0\n0')

# 无标题：不空标题格
ctrl._params = run_params([A, B], has_title=False, target={'target': 'clipboard'})
err = s.run(model, ctrl._params)
check('no-title clipboard no blank', QApplication.clipboard().text() == '3\n1.2\n5.25')

# 行方向：行1 × 行2，输出到行 10
R1 = {'kind': 'row', 'index': 1, 'title': None, 'title_idx': 0,
      'display': '行2', 'values': [1.5, 2.0], 'decimals': [1, 0]}
R2 = {'kind': 'row', 'index': 2, 'title': None, 'title_idx': 0,
      'display': '行3', 'values': [2.4, 0.5], 'decimals': [1, 1]}
ctrl._params = run_params([R1, R2], direction='以行为单位', has_title=False,
                          target={'target': 'row', 'index': 10})
err = s.run(model, ctrl._params)
check('row run ok', err is None)
check('row11 colA = 1.5*2.4 -> 3.6', model.value(10, 0) == '3.6')
check('row11 colB = 2*0.5 (n=1) -> 1', model.value(10, 1) == '1')

# 行方向剪贴板：Tab 分隔，有标题开头空一格
ctrl._params = run_params([R1, R2], direction='以行为单位',
                          target={'target': 'clipboard'})
err = s.run(model, ctrl._params)
check('row clipboard tab line with blank', QApplication.clipboard().text() == '\t3.6\t1')

# 无 decimals 参数（加法式 params）也能跑：回退 auto
ctrl._params = run_params([A, B], has_title=False, target={'target': 'clipboard'})
ctrl._params['operands'].pop('decimals')
err = s.run(model, ctrl._params)
check('missing decimals falls back to auto', QApplication.clipboard().text() == '3\n1.2\n5.25')

print('ALL MUL SMOKE TESTS PASSED')
