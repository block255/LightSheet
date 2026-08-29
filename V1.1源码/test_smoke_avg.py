"""平均值脚本冒烟测试 — 覆盖标题行列识别、垂直输出、invert 方向、精度。"""
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
from scripts.base_script import OutputTargetStep
from scripts.平均值脚本 import AverageScript


def check(name, cond):
    if not cond:
        raise AssertionError(f'FAIL: {name}')
    print('PASS:', name)


# ---------- 1. 脚本结构 ----------
s = AverageScript()
check('script name', s.name == '平均值脚本')
steps = s.steps()
check('steps structure', [type(x).__name__ for x in steps]
      == ['SelectRangeStep', 'ChooseOptionStep', 'OutputTargetStep'])
check('output step invert', steps[2].invert is True)

# ---------- 2. 控制器 invert：输出轴与处理单位垂直 ----------
model = SpreadsheetModel()
model.load_2d([
    ['学生', '语文', '数学', '英语', '物理', '化学', '生物', '总分'],
    ['小明', '131', '128', '138', '83', '93', '100', '673'],
    ['小华', '126', '135', '132', '90', '93', '95', '671'],
    ['小红', '130', '120', '130', '80', '80', '90', '630'],
    ['平均', '', '', '', '', '', '', ''],
])
grid = SpreadsheetGrid()
grid.setModel(model)
status = StatusBar()
panel = SidePanel()
ctrl = ScriptController(model, grid, status, panel)
ctrl._running = True

ctrl._params['direction'] = '对列处理'
ctrl._begin_output_target(OutputTargetStep('t', invert=True))
ctrl._on_output_pick()
check('对列处理 -> 提示点行头', '行头' in panel._script_prompt.text())
ctrl._disconnect_output_signals()

ctrl._params['direction'] = '对行处理'
ctrl._begin_output_target(OutputTargetStep('t', invert=True))
ctrl._on_output_pick()
check('对行处理 -> 提示点列头', '列头' in panel._script_prompt.text())
ctrl._disconnect_output_signals()

# ---------- 3. run：对列处理（区域 A1:H5，含预留的平均行） ----------
p = {
    'range': (0, 0, 4, 7),
    'direction': '对列处理',
    'output': {'target': 'row', 'index': 4},
}
check('run ok', s.run(model, p) is None)
check('学生列整列排除（A5 保留原内容）', model.value(4, 0) == '平均')
check('B5 = 语文平均 129', model.value(4, 1) == '129')
check('C5 = 数学平均 127.67', model.value(4, 2) == '127.67')
check('D5 = 英语平均 133.33', model.value(4, 3) == '133.33')
check('E5 = 物理平均 84.33', model.value(4, 4) == '84.33')
check('F5 = 化学平均 88.67', model.value(4, 5) == '88.67')
check('G5 = 生物平均 95（除尽不补零）', model.value(4, 6) == '95')
check('H5 = 总分平均 658', model.value(4, 7) == '658')

# ---------- 4. run：对行处理（区域 A1:H4，输出到 I 列） ----------
model2 = SpreadsheetModel()
model2.load_2d([
    ['学生', '语文', '数学', '英语', '物理', '化学', '生物', '总分'],
    ['小明', '131', '128', '138', '83', '93', '100', '673'],
    ['小华', '126', '135', '132', '90', '93', '95', '671'],
    ['小红', '130', '120', '130', '80', '80', '90', '630'],
])
p2 = {
    'range': (0, 0, 3, 7),
    'direction': '对行处理',
    'output': {'target': 'column', 'index': 8},
}
check('row run ok', s.run(model2, p2) is None)
check('标题行整行排除（I1 不写）', model2.value(0, 8) == '')
check('I2 = 小明各科平均 192.29', model2.value(1, 8) == '192.29')
check('I3 = 小华各科平均 191.71', model2.value(2, 8) == '191.71')
check('I4 = 小红各科平均 180', model2.value(3, 8) == '180')

# ---------- 5. 精度 + 单标题格白名单：3 行数据 + 1 行标题（33% > 30% 但仅 1 个标题格，豁免） ----------
m3 = SpreadsheetModel()
m3.load_2d([
    ['科目', 'A', 'B'],
    ['x', '1.1', '0.25'],
    ['y', '2.2', '3.75'],
    ['z', '3.3', '5.25'],
])
p3 = {
    'range': (0, 0, 3, 2),
    'direction': '对列处理',
    'output': {'target': 'row', 'index': 4},
}
check('decimal run ok', s.run(m3, p3) is None)
check('科目列整列文字排除', m3.value(4, 0) == '')
check('A 平均 2.2 (n=3, 单标题格白名单)', m3.value(4, 1) == '2.2')
check('B 平均 3.0833 (n=4, 除尽不补零)', m3.value(4, 2) == '3.0833')

# ---------- 6. 剪贴板输出 + 无数据区域 ----------
m4 = SpreadsheetModel()
m4.load_2d([
    ['学生', '语文', '数学', '英语', '物理', '化学', '生物', '总分'],
    ['小明', '131', '128', '138', '83', '93', '100', '673'],
    ['小华', '126', '135', '132', '90', '93', '95', '671'],
    ['小红', '130', '120', '130', '80', '80', '90', '630'],
    ['平均', '', '', '', '', '', '', ''],
])
p4 = {
    'range': (0, 0, 4, 7),
    'direction': '对列处理',
    'output': {'target': 'clipboard'},
}
check('clipboard ok', s.run(m4, p4) is None)
check('clipboard 对列处理横排(Tab分隔)',
      QApplication.clipboard().text() == '129\t127.67\t133.33\t84.33\t88.67\t95\t658')

p5 = {
    'range': (4, 1, 4, 6),  # m4 第 5 行 B-G 列，全是空格
    'direction': '对列处理',
    'output': {'target': 'clipboard'},
}
check('empty region errors', s.run(m4, p5) is not None)

print('ALL AVG SMOKE TESTS PASSED')
