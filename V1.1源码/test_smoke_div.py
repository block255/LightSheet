"""除法脚本冒烟测试 — 覆盖 ÷ 符号行、除 0 报错中止、auto 逐位 +2 精度、输出形态。"""
import os
import sys

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
sys.path.insert(0, r'D:\Cloude Code\自制表格软件\代码输出库\源码')

from PyQt6.QtWidgets import QApplication
app = QApplication([])

from models.spreadsheet_model import SpreadsheetModel
from scripts.除法脚本 import DivideScript


def check(name, cond):
    if not cond:
        raise AssertionError(f'FAIL: {name}')
    print('PASS:', name)


# ---------- 1. 脚本结构 ----------
s = DivideScript()
check('script name', s.name == '除法脚本')
steps = s.steps()
check('steps structure', [type(x).__name__ for x in steps]
      == ['ChooseOptionStep', 'OperandInputStep', 'OutputTargetStep'])
check('decimals enabled', steps[1].decimals is True)
check('operator is divide sign', steps[1].operator == '÷')

# ---------- 1.5 控制器调用链：÷ 符号行 ----------
from views.side_panel import SidePanel
from views.status_bar import StatusBar
from views.spreadsheet_grid import SpreadsheetGrid
from controllers.script_controller import ScriptController
panel = SidePanel()
m0 = SpreadsheetModel()
g0 = SpreadsheetGrid(); g0.setModel(m0)
st0 = StatusBar()
ctrl0 = ScriptController(m0, g0, st0, panel)
ctrl0._running = True
ctrl0._params['direction'] = '以列为单位'
ctrl0._begin_operand_input(steps[1])
check('controller path shows divide operator row', panel._operator_row is not None)

# ---------- 2. 执行 ----------
model = SpreadsheetModel()
model.load_2d([
    ['语文', '数学'],
    ['1.5', '0.25'],
    ['1', '3'],
    ['8', '2'],
])

A = {'kind': 'column', 'index': 0, 'title': '语文', 'title_idx': 0,
     'display': '语文', 'values': [1.5, 1.0, 8.0], 'decimals': [1, 0, 0]}
B = {'kind': 'column', 'index': 1, 'title': '数学', 'title_idx': 0,
     'display': '数学', 'values': [0.25, 3.0, 2.0], 'decimals': [2, 0, 0]}


def run_params(slots, direction='以列为单位', target=None, mode='auto', digits=None,
               has_title=True, data_len=None, title_idx=0):
    if data_len is None:
        data_len = 1
        for sl in slots:
            if sl['kind'] != 'constant':
                data_len = len(sl['values'])
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


# A ÷ B（auto 逐位 max+2）：
#   1.5÷0.25=6.0   N=max(1,2)+2=4 → 除尽不补零 → '6'
#   1÷3=0.333...   N=max(0,0)+2=2 → '0.33'
#   8÷2=4.0        N=2 → '4'
p = run_params([A, B], target={'target': 'column', 'index': 2})
check('run ok', s.run(model, p) is None)
check('title cell untouched', model.value(0, 2) == '')
check('C1 = 1.5/0.25 exact, no padding -> 6', model.value(1, 2) == '6')
check('C2 = 1/3 (n=2) -> 0.33', model.value(2, 2) == '0.33')
check('C3 = 8/2 -> 4', model.value(3, 2) == '4')

# 常数除数：A ÷ 2 = [0.75, 0.5, 4]
C2 = {'kind': 'constant', 'value': 2.0, 'display': '2',
      'title': None, 'title_idx': 0, 'values': [], 'decimals': [0]}
p = run_params([A, C2], has_title=False, target={'target': 'clipboard'})
check('constant divisor', s.run(model, p) is None
      and QApplication.clipboard().text() == '0.75\n0.5\n4')

# 常数被除数：2 ÷ A = [1.333..., 2, 0.25]
p = run_params([C2, A], has_title=False, target={'target': 'clipboard'})
check('constant as dividend', s.run(model, p) is None
      and QApplication.clipboard().text() == '1.333\n2\n0.25')

# 除 0：常数 0 → 报错中止，不写入任何结果
Z = {'kind': 'constant', 'value': 0.0, 'display': '0',
     'title': None, 'title_idx': 0, 'values': [], 'decimals': [0]}
before = [model.value(r, 3) for r in range(model.row_total)]
p = run_params([A, Z], target={'target': 'column', 'index': 3})
err = s.run(model, p)
check('zero constant aborts', err is not None and '除数为 0' in err)
check('no write after abort', [model.value(r, 3) for r in range(model.row_total)] == before)

# 除 0：列中某位置为 0 → 报错带位置信息
model2 = SpreadsheetModel()
model2.load_2d([
    ['语文', '数学'],
    ['1.5', '0.25'],
    ['1', '0'],
    ['8', '2'],
])
A2 = {'kind': 'column', 'index': 0, 'title': '语文', 'title_idx': 0,
      'display': '语文', 'values': [1.5, 1.0, 8.0], 'decimals': [1, 0, 0]}
B2 = {'kind': 'column', 'index': 1, 'title': '数学', 'title_idx': 0,
      'display': '数学', 'values': [0.25, 0.0, 2.0], 'decimals': [2, 0, 0]}
before2 = [model2.value(r, 2) for r in range(model2.row_total)]
p = run_params([A2, B2], target={'target': 'column', 'index': 2})
err = s.run(model2, p)
check('zero in data aborts with position', err is not None
      and '除数为 0' in err and '第 2 行' in err)
check('no write after data-zero abort',
      [model2.value(r, 2) for r in range(model2.row_total)] == before2)

# 手动 4 位：1 ÷ 3 = 0.3333
C1 = {'kind': 'constant', 'value': 1.0, 'display': '1',
      'title': None, 'title_idx': 0, 'values': [], 'decimals': [0]}
C3 = {'kind': 'constant', 'value': 3.0, 'display': '3',
      'title': None, 'title_idx': 0, 'values': [], 'decimals': [0]}
p = run_params([C1, C3], has_title=False, data_len=1,
               target={'target': 'clipboard'}, mode='manual', digits=4)
check('manual 4 digits 0.3333', s.run(model, p) is None
      and QApplication.clipboard().text() == '0.3333')

# 手动 0 位：1 ÷ 3 → 0（整数不补零）
p = run_params([C1, C3], has_title=False, data_len=1,
               target={'target': 'clipboard'}, mode='manual', digits=0)
check('manual 0 digits -> 0', s.run(model, p) is None
      and QApplication.clipboard().text() == '0')

# 有标题剪贴板：首行空标题格
p = run_params([A, B], target={'target': 'clipboard'})
check('clipboard blanks title row', s.run(model, p) is None
      and QApplication.clipboard().text() == '\n6\n0.33\n4')

# 行方向：行1 ÷ 行2 = [1.5, 0.0833...]
R1 = {'kind': 'row', 'index': 1, 'title': None, 'title_idx': 0,
      'display': '行2', 'values': [1.5, 0.25], 'decimals': [1, 2]}
R2 = {'kind': 'row', 'index': 2, 'title': None, 'title_idx': 0,
      'display': '行3', 'values': [1.0, 3.0], 'decimals': [0, 0]}
p = run_params([R1, R2], direction='以行为单位', has_title=False,
               target={'target': 'row', 'index': 10})
check('row run ok', s.run(model, p) is None)
check('row11 colA = 1.5/1 -> 1.5', model.value(10, 0) == '1.5')
check('row11 colB = 0.25/3 (n=4) -> 0.0833', model.value(10, 1) == '0.0833')

# 无 decimals 参数（加法式 params）回退 auto
p = run_params([A, B], has_title=False, target={'target': 'clipboard'})
p['operands'].pop('decimals')
check('missing decimals falls back to auto', s.run(model, p) is None
      and QApplication.clipboard().text() == '6\n0.33\n4')

print('ALL DIV SMOKE TESTS PASSED')
