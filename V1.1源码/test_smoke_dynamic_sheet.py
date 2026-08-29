"""动态脚本按 sheet 隔离 — 冒烟测试。

验证（xlsx 公式分 sheet，动态脚本同样按 sheet 隔离）：
- 记录时带 sheet 名
- 触发时只处理同 sheet 的脚本（其他 sheet 脚本不触发）
- 重放在正确 sheet 模型上执行
- 切 sheet 后 set_model 更新重放目标
"""
import os
import shutil
import sys

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
sys.path.insert(0, r'D:\Cloude Code\自制表格软件\代码输出库\源码')

from PyQt6.QtWidgets import QApplication
app = QApplication([])

from models.ext_store import ExtStore
from models.spreadsheet_model import SpreadsheetModel
from controllers.dynamic_controller import DynamicController
from file_io import xlsx_handler

TMP = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_tmp_sheet_iso')
shutil.rmtree(TMP, ignore_errors=True)
LIB = os.path.join(TMP, '表格文件库')
os.makedirs(LIB, exist_ok=True)


def check(name, cond):
    if not cond:
        raise AssertionError(f'FAIL: {name}')
    print('PASS:', name)


import inspect
from scripts import 加法脚本 as add_mod
add_path = inspect.getfile(add_mod)

# 两个 sheet 的模型
xlsx_path = os.path.join(LIB, '多表.xlsx')
xlsx_handler.write_all(xlsx_path, [
    ('甲表', [['1', '2', ''], ['3', '4', '']]),
    ('乙表', [['10', '20', ''], ['30', '40', '']]),
])
store = ExtStore(xlsx_path, LIB)
model_a = SpreadsheetModel()
model_a.load_2d([['1', '2', ''], ['3', '4', '']])
model_a.file_path = xlsx_path
model_a.file_format = 'xlsx'
model_b = SpreadsheetModel()
model_b.load_2d([['10', '20', ''], ['30', '40', '']])
model_b.file_path = xlsx_path
model_b.file_format = 'xlsx'

dc = DynamicController(store, model_a, None)
dc.set_enabled(True)
dc.set_model(model_a, '甲表')
msgs = []
dc.status_message.connect(msgs.append)

params = {
    'direction': '以列为单位',
    'operands': {'slots': [
        {'kind': 'column', 'index': 0, 'values': [1.0, 3.0]},
        {'kind': 'column', 'index': 1, 'values': [2.0, 4.0]}]},
    'output': {'target': 'column', 'index': 2},
}

# 1. 在甲表记录脚本（sheet=甲表）
rec = dc.record('加法脚本', add_path, params, '甲表')
check('记录带 sheet', rec['sheet'] == '甲表')
check('扩展区持久化 sheet', store.get_scripts()[0]['sheet'] == '甲表')

# 2. 乙表记录另一个脚本（sheet=乙表）
params2 = {
    'direction': '以列为单位',
    'operands': {'slots': [
        {'kind': 'column', 'index': 0, 'values': [10.0, 30.0]},
        {'kind': 'constant', 'value': 5.0}]},
    'output': {'target': 'column', 'index': 2},
}
dc.set_model(model_b, '乙表')
rec2 = dc.record('加法脚本', add_path, params2, '乙表')
check('乙表记录带 sheet', rec2['sheet'] == '乙表')
check('两条脚本分属两表', {s['sheet'] for s in dc.scripts} == {'甲表', '乙表'})

# 3. 甲表编辑 → 只触发甲表脚本
dc.set_model(model_a, '甲表')
model_a.set_value(0, 0, '100')
msgs.clear()
dc.on_cell_edited(0, 0, '甲表')
check('甲表触发重放', any('已自动重放' in m for m in msgs))
check('甲表 C1=100+2=102', model_a.value(0, 2) == '102')
check('乙表未被误触（乙表 D 列未写）', model_b.value(0, 2) == '')

# 4. 乙表编辑 → 只触发乙表脚本
dc.set_model(model_b, '乙表')
model_b.set_value(0, 0, '50')
msgs.clear()
dc.on_cell_edited(0, 0, '乙表')
check('乙表触发重放', any('已自动重放' in m for m in msgs))
check('乙表 C1=50+5=55', model_b.value(0, 2) == '55')
check('甲表未被误触（甲表 C1 保持 102）', model_a.value(0, 2) == '102')

# 5. sheet 不匹配时不触发（甲表编辑但 sheet 传乙表）
msgs.clear()
model_a.set_value(0, 1, '7')
dc.on_cell_edited(0, 1, '乙表')   # sheet 错配
check('sheet 错配不触发', not any('已自动重放' in m for m in msgs))

# 6. 重开文件恢复 sheet 归属
store2 = ExtStore(xlsx_path, LIB)
check('重开 sheet 归属保留',
      {s['sheet'] for s in store2.get_scripts()} == {'甲表', '乙表'})

shutil.rmtree(TMP, ignore_errors=True)
print('ALL SHEET-ISOLATION TESTS PASSED')
