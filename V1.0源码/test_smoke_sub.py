"""减法脚本冒烟测试 — 覆盖运算顺序（首个为被减数）、保留小数位数、输出形态。"""
import os
import sys

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
sys.path.insert(0, r'D:\Cloude Code\自制表格软件\代码输出库\源码')

from PyQt6.QtWidgets import QApplication
app = QApplication([])

from models.spreadsheet_model import SpreadsheetModel
from scripts.减法脚本 import SubtractScript


def check(name, cond):
    if not cond:
        raise AssertionError(f'FAIL: {name}')
    print('PASS:', name)


# ---------- 1. 脚本结构 ----------
s = SubtractScript()
check('script name', s.name == '减法脚本')
steps = s.steps()
check('steps structure', [type(x).__name__ for x in steps]
      == ['ChooseOptionStep', 'OperandInputStep', 'OutputTargetStep'])
check('decimals enabled', steps[1].decimals is True)
check('operator set', steps[1].operator == '－')

# ---------- 1.5 面板：运算符号行 ----------
from views.side_panel import SidePanel
panel = SidePanel()
panel.show_operand_slots(2, 'column', with_decimals=True, operator='－')
check('operator row shown', panel._operator_row is not None)
i1 = panel._script_btn_area.indexOf(panel._operand_rows[0])
io = panel._script_btn_area.indexOf(panel._operator_row)
i2 = panel._script_btn_area.indexOf(panel._operand_rows[1])
check('operator between slot1 and slot2', i1 < io < i2)
panel.add_operand_slot()
i3 = panel._script_btn_area.indexOf(panel._operand_rows[-1])
check('added slot stays after operator row', i3 > io)
ia = panel._script_btn_area.indexOf(panel._add_operand_btn_row)
check('add button stays below all slots', i3 < ia)
panel2 = SidePanel()
panel2.show_operand_slots(2, 'column', with_decimals=True)
check('no operator row without flag', panel2._operator_row is None)

# 控制器真实调用链：_begin_operand_input 必须把 operator 传给面板
from views.status_bar import StatusBar
from views.spreadsheet_grid import SpreadsheetGrid
from controllers.script_controller import ScriptController
from models.spreadsheet_model import SpreadsheetModel
m0 = SpreadsheetModel()
g0 = SpreadsheetGrid(); g0.setModel(m0)
st0 = StatusBar()
ctrl0 = ScriptController(m0, g0, st0, panel2)
ctrl0._running = True
ctrl0._params['direction'] = '以列为单位'
ctrl0._begin_operand_input(steps[1])
check('controller path shows operator row', panel2._operator_row is not None)

# ---------- 2. 执行 ----------
model = SpreadsheetModel()
model.load_2d([
    ['语文', '数学'],
    ['1.5', '2'],
    ['2.4', '0.5'],
    ['3', '1.75'],
])

A = {'kind': 'column', 'index': 0, 'title': '语文', 'title_idx': 0,
     'display': '语文', 'values': [1.5, 2.4, 3.0], 'decimals': [1, 1, 0]}
B = {'kind': 'column', 'index': 1, 'title': '数学', 'title_idx': 0,
     'display': '数学', 'values': [2.0, 0.5, 1.75], 'decimals': [0, 1, 2]}


def run_params(slots, direction='以列为单位', target=None, mode='auto', digits=None,
               has_title=True, data_len=None, title_idx=0):
    if data_len is None:
        # 与控制器一致：取第一个非常数槽位的长度（全常数时回退 1）
        data_len = 1
        for s in slots:
            if s['kind'] != 'constant':
                data_len = len(s['values'])
                break
    return {
        'direction': direction,
        'operands': {
            'slots': slots,
            'data_len': data_len,
            'title_idx': title_idx,
            'has_title': has_title,
            'decimals': {'mode': mode, 'digits': digits},
        },
        'output': target,
    }


# A - B（自动逐位）：[-0.5, 1.9, 1.25]
p = run_params([A, B], target={'target': 'column', 'index': 2})
check('run ok', s.run(model, p) is None)
check('title cell untouched', model.value(0, 2) == '')
check('C1 = 1.5-2 (n=1) -> -0.5', model.value(1, 2) == '-0.5')
check('C2 = 2.4-0.5 (n=1) -> 1.9', model.value(2, 2) == '1.9')
check('C3 = 3-1.75 (n=2) -> 1.25', model.value(3, 2) == '1.25')

# 顺序敏感：B - A = [0.5, -1.9, -1.25]
p = run_params([B, A], has_title=False, target={'target': 'clipboard'})
check('order matters (B-A)', s.run(model, p) is None
      and QApplication.clipboard().text() == '0.5\n-1.9\n-1.25')

# 常数在第二个：A - 2 = [-0.5, 0.4, 1.0]
C2 = {'kind': 'constant', 'value': 2.0, 'display': '2',
      'title': None, 'title_idx': 0, 'values': [], 'decimals': [0]}
p = run_params([A, C2], has_title=False, target={'target': 'clipboard'})
check('constant subtractor', s.run(model, p) is None
      and QApplication.clipboard().text() == '-0.5\n0.4\n1')

# 常数在第一个：2 - A = [0.5, -0.4, -1.0]
p = run_params([C2, A], has_title=False, target={'target': 'clipboard'})
check('constant as minuend', s.run(model, p) is None
      and QApplication.clipboard().text() == '0.5\n-0.4\n-1')

# 三连减：A - B - 0.5 = [-1.0, 1.4, 0.75]
H = {'kind': 'constant', 'value': 0.5, 'display': '0.5',
     'title': None, 'title_idx': 0, 'values': [], 'decimals': [1]}
p = run_params([A, B, H], has_title=False, target={'target': 'clipboard'})
check('triple subtraction', s.run(model, p) is None
      and QApplication.clipboard().text() == '-1\n1.4\n0.75')

# 手动 2 位：0.1 - 0.01 = 0.09（消除浮点误差）
C01 = {'kind': 'constant', 'value': 0.1, 'display': '0.1',
       'title': None, 'title_idx': 0, 'values': [], 'decimals': [1]}
C001 = {'kind': 'constant', 'value': 0.01, 'display': '0.01',
        'title': None, 'title_idx': 0, 'values': [], 'decimals': [2]}
p = run_params([C01, C001], has_title=False, data_len=1,
               target={'target': 'clipboard'}, mode='manual', digits=2)
check('manual 2 digits 0.09', s.run(model, p) is None
      and QApplication.clipboard().text() == '0.09')

# 手动 0 位：1 - 4 = -3（整数不补零）
C1 = {'kind': 'constant', 'value': 1.0, 'display': '1',
      'title': None, 'title_idx': 0, 'values': [], 'decimals': [0]}
C4 = {'kind': 'constant', 'value': 4.0, 'display': '4',
      'title': None, 'title_idx': 0, 'values': [], 'decimals': [0]}
p = run_params([C1, C4], has_title=False, data_len=1,
               target={'target': 'clipboard'}, mode='manual', digits=0)
check('manual 0 digits negative int', s.run(model, p) is None
      and QApplication.clipboard().text() == '-3')

# 有标题剪贴板：首行空标题格
p = run_params([A, B], target={'target': 'clipboard'})
check('clipboard blanks title row', s.run(model, p) is None
      and QApplication.clipboard().text() == '\n-0.5\n1.9\n1.25')

# 行方向：行1 - 行2 = [-0.9, 1.5]，输出到行 10
R1 = {'kind': 'row', 'index': 1, 'title': None, 'title_idx': 0,
      'display': '行2', 'values': [1.5, 2.0], 'decimals': [1, 0]}
R2 = {'kind': 'row', 'index': 2, 'title': None, 'title_idx': 0,
      'display': '行3', 'values': [2.4, 0.5], 'decimals': [1, 1]}
p = run_params([R1, R2], direction='以行为单位', has_title=False,
               target={'target': 'row', 'index': 10})
check('row run ok', s.run(model, p) is None)
check('row11 colA = 1.5-2.4 -> -0.9', model.value(10, 0) == '-0.9')
check('row11 colB = 2-0.5 -> 1.5', model.value(10, 1) == '1.5')

# 无 decimals 参数（加法式 params）回退 auto
p = run_params([A, B], has_title=False, target={'target': 'clipboard'})
p['operands'].pop('decimals')
check('missing decimals falls back to auto', s.run(model, p) is None
      and QApplication.clipboard().text() == '-0.5\n1.9\n1.25')

print('ALL SUB SMOKE TESTS PASSED')
