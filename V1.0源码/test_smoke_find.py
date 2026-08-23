"""查找脚本 — 冒烟测试（数据查找/文本查找/标题识别/输出方式）。"""
import os
import sys

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
sys.path.insert(0, r'D:\Cloude Code\自制表格软件\代码输出库\源码')

from PyQt6.QtWidgets import QApplication
app = QApplication([])

from models.spreadsheet_model import SpreadsheetModel
from scripts.查找脚本 import FindScript


def check(name, cond):
    if not cond:
        raise AssertionError(f'FAIL: {name}')
    print('PASS:', name)


s = FindScript()
check('步骤结构', [type(x).__name__ for x in s.steps()]
      == ['SelectRangeStep', 'ChooseOptionStep', 'FindLookupStep',
          'FindOutputStep'])

# 表格：标题行 + 数据
m = SpreadsheetModel()
m.load_2d([
    ['姓名', '语文', '数学'],      # 行0 标题
    ['张三', '90', '80'],
    ['李四', '70', '95'],
    ['王五', '88', '60'],
    ['赵六', '55', '72'],
])

# 数据查找：以行为单位，参考列=数学（列2），>70（含标题行，控制器已排除→_valid_indices）
p = {
    'range': (0, 0, 4, 2), 'unit': '以行为单位',
    'lookup_type': '按数据查找', 'ref': 2,
    'operator': '>', 'constant': '70', 'find_output': 'col',
    '_valid_indices': [1, 2, 3, 4],   # 标题行(0)已排除
}
err = s.run(m, p)
check('数据查找 run ok', err is None)
clip = QApplication.clipboard().text()
check('以列输出标题', clip == '张三\n李四\n赵六')   # 数学>70：张三80 李四95 赵六72

# 数据查找：参考格为空 → 控制器选参考时报错（脚本 run 层由 valid 排除）
# 这里直接测控制器校验逻辑
from controllers.script_controller import ScriptController
from views.side_panel import SidePanel
from views.spreadsheet_grid import SpreadsheetGrid
from views.status_bar import StatusBar
m2 = SpreadsheetModel()
m2.load_2d([['姓名', '语文'], ['甲', '80'], ['乙', ''], ['丙', '60']])
sp2 = SidePanel()
g2 = SpreadsheetGrid(); g2.setModel(m2)
st2 = StatusBar()
ctrl2 = ScriptController(m2, g2, st2, sp2)
ctrl2._params = {'range': (0, 0, 3, 1), 'unit': '以行为单位',
                 'lookup_type': '按数据查找'}
ctrl2._find_step = __import__('scripts.base_script', fromlist=['FindLookupStep']).FindLookupStep('t')
ctrl2._find_bounds = (0, 1)
ctrl2._running = True
ctrl2._find_picking = True
ctrl2._on_find_ref_clicked(1)
check('数据查找空格报错', ctrl2._params.get('ref') is None
      and '空格' in sp2._script_prompt.text())

# 文本查找：包含 + 忽略首格
m3 = SpreadsheetModel()
m3.load_2d([
    ['组别', 'A', 'B'],
    ['第一组', '数据', '备注'],
    ['第二组', '数据', '重要'],
    ['第三组', '备注', '数据'],
])
# 以列为单位，参考行=行1（第一组行），包含"数据" → 仅 B 列（行1列1='数据'）符合
p3 = {'range': (0, 0, 3, 2), 'unit': '以列为单位', 'lookup_type': '按文本查找',
      'ref': 1, 'text': '数据', 'ignore_head': '不忽略首格', 'find_output': 'hint'}
err3 = s.run(m3, p3)
check('文本查找 run ok', err3 is None)
check('文本查找结果提示', p3.get('find_results') == 'A')   # B 列标题（行0列1='A'）
# 忽略首格：参考行=行0（组别标题行），跳过第一个列单位
p3b = {'range': (0, 0, 3, 2), 'unit': '以列为单位', 'lookup_type': '按文本查找',
       'ref': 0, 'text': '组', 'ignore_head': '不忽略首格', 'find_output': 'hint'}
s.run(m3, p3b)
check('文本查找组别', p3b.get('find_results') == '组别')
p3c = dict(p3b, ignore_head='忽略首格')
s.run(m3, p3c)
check('忽略首格跳首单位', p3c.get('find_results') == '无符合')

# 标题识别：纯数据首格 → 行号
m4 = SpreadsheetModel()
m4.load_2d([['1', '10'], ['2', '20'], ['3', '30']])
p4 = {'range': (0, 0, 2, 1), 'unit': '以行为单位', 'lookup_type': '按数据查找',
      'ref': 1, 'operator': '>', 'constant': '15', 'find_output': 'col'}
err4 = s.run(m4, p4)
check('纯数据首格用行号', err4 is None
      and QApplication.clipboard().text() == '第2行\n第3行')

# 以列输出剪贴板（Tab 横排）
p5 = dict(p4, find_output='row')
s.run(m4, p5)
check('以行输出横排', QApplication.clipboard().text() == '第2行\t第3行')

print('ALL FIND SMOKE TESTS PASSED')
