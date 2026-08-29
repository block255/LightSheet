"""互译集成测试：记录自动翻译 / 公式条目引擎重放 / 保存公式收集 / 输出格过滤。"""
import os, sys, shutil
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
sys.path.insert(0, r'D:\Cloude Code\自制表格软件\代码输出库\源码')
from PyQt6.QtWidgets import QApplication
app = QApplication([])

from models.ext_store import ExtStore
from controllers.dynamic_controller import (
    DynamicController, extract_replay_config,
)
from models.spreadsheet_model import SpreadsheetModel

def check(name, cond):
    if not cond:
        raise AssertionError('FAIL: ' + name)
    print('PASS:', name)

# 临时库
tmp = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_tmp_dynint')
shutil.rmtree(tmp, ignore_errors=True)
os.makedirs(tmp)
lib = os.path.join(tmp, 'lib')
os.makedirs(lib)
xlsx_path = os.path.join(lib, 't.xlsx')
open(xlsx_path, 'w').close()

def make_model(matrix):
    m = SpreadsheetModel()
    m.load_2d(matrix)
    m.file_format = 'xlsx'
    m.file_path = xlsx_path
    return m

model = make_model([['2', '3', '5'], ['4', '6', '10']])
store = ExtStore(xlsx_path, lib)
ctrl = DynamicController(store, model, None)

# ==== 1. record 自动翻译（加法 → formula 模板）====
print('--- 记录自动翻译 ---')
store.set_dynamic_mode(True)
params = {'direction': '以列为单位',
          'operands': {'slots': [{'kind': 'column', 'index': 0},
                                 {'kind': 'column', 'index': 1}]},
          'output': {'target': 'column', 'index': 2}}
rec = ctrl.record('加法脚本.py', 'D:/x/加法脚本.py', params, '表1')
check('record 返回带 formula', rec and rec.get('formula'))
check('加法公式模板', rec['formula']['text'] == '=A{r}+B{r}')
check('公式基准起点 col2', rec['formula']['cell0'] == [0, 2])

# 统计类翻译
params2 = {'direction': '对列处理', 'range': [0, 0, 1, 2],
           'output': {'target': 'row', 'index': 2}}
rec2 = ctrl.record('平均值脚本.py', 'D:/x/平均值脚本.py', params2, '表1')
check('统计公式模板', rec2['formula']['text'] == '=AVERAGE({c}1:{c}2)')
check('统计基准起点 row2', rec2['formula']['cell0'] == [2, 0])

# 不可译（剪贴板槽）无 formula
params3 = {'direction': '以列为单位',
           'operands': {'slots': [{'kind': 'column', 'index': 0},
                                  {'kind': 'clipboard', 'value': 'x'}]},
           'output': {'target': 'column', 'index': 2}}
rec3 = ctrl.record('加法脚本.py', 'D:/x/加法脚本.py', params3, '表1')
check('不可译无 formula', rec3.get('formula') is None)

# ==== 2. formula 条目引擎重放 ====
print('--- 公式条目引擎重放 ---')
# 外来公式：B1 格 = SUM(A1:A2) → 引擎算 = 6
store.add_entry({'kind': 'formula', 'source': 'external', 'sheet': '表1',
                 'output': {'region': [0, 1, 0, 1]},
                 'refs': [{'range': [0, 0, 1, 0]}],
                 'formula': {'text': '=SUM(A1:A2)'},
                 'summary': '[公式] =SUM(A1:A2)'})
ctrl._formula_entries = [e for e in store.get_entries()
                         if e.get('kind') == 'formula']
ok = ctrl._replay_formula(ctrl._formula_entries[0])
check('引擎算公式写模型', ok and model.value(0, 1) == '6')

# 编辑触发公式重放：改 A1=10 → 触发 → B1 = SUM(10,4) = 14
model.set_value(0, 0, '10')
ctrl.set_model(model, '表1')
ctrl.on_cell_edited(0, 0, '表1')
check('编辑触发公式重放 B1=14', model.value(0, 1) == '14')

# ==== 3. 保存公式收集 ====
print('--- 保存公式收集 ---')
f = ctrl.collect_save_formulas(row_total=2, col_total=4)
check('加法公式展开 C1/C2', f.get('表1', {}).get((0, 2)) == '=A1+B1'
      and f.get('表1', {}).get((1, 2)) == '=A2+B2')
check('统计公式展开 行3各列', f.get('表1', {}).get((2, 0)) == '=AVERAGE(A1:A2)'
      and f.get('表1', {}).get((2, 2)) == '=AVERAGE(C1:C2)')
check('外来公式原文保留', f.get('表1', {}).get((0, 1)) == '=SUM(A1:A2)')

# ==== 4. 输出格过滤（脚本输出区）====
print('--- 输出格过滤 ---')
out = ctrl.script_output_cells(row_total=2, col_total=4)
check('含加法输出列C', (0, 2) in {(r, c) for _s, r, c in out})
check('含统计输出行3', (2, 0) in {(r, c) for _s, r, c in out})

# ==== 5. 脚本公式展开跳过标题行（2026-08-29：标题文字不被公式覆盖）====
print('--- 标题行跳过 ---')
params_title = {'direction': '以列为单位',
                'operands': {'slots': [{'kind': 'column', 'index': 1,
                                        'title': '单价', 'title_idx': 0},
                                       {'kind': 'column', 'index': 2,
                                        'title': '数量', 'title_idx': 0}],
                             'data_len': 3, 'title_idx': 0, 'has_title': True},
                'output': {'target': 'column', 'index': 4}}
cfg_t, ref_t, out_t = extract_replay_config(params_title)
check('精确展开信息提取', cfg_t.get('has_title') is True
      and cfg_t.get('title_idx') == 0 and cfg_t.get('data_len') == 3)
store.add_entry({'kind': 'script', 'source': 'ours', 'sheet': '表1',
                 'summary': '乘法脚本 列B×列C→列E', 'script': '乘法脚本.py',
                 'script_path': 'D:/x/乘法脚本.py', 'replay_cfg': cfg_t,
                 'ref_cells': ref_t, 'output_cells': out_t,
                 'formula': {'text': '=B{r}*C{r}', 'cell0': [0, 4]}})
f_t = ctrl.collect_save_formulas(row_total=4, col_total=5)
cells_t = f_t.get('表1', {})
check('标题行(E1)不在公式集', (0, 4) not in cells_t)
check('数据行展开 E2/E3', cells_t.get((1, 4)) == '=B2*C2'
      and cells_t.get((2, 4)) == '=B3*C3')

# ==== 6. 孤儿条目跳过（sheet 不存在 → 不回退当前模型，2026-08-29）====
print('--- 孤儿条目跳过 ---')
# 构造 sheet='不存在的表' 的脚本条目（输出 row4 col3 会写 D5 如果回退）
store.add_entry({'kind': 'script', 'source': 'ours', 'sheet': '不存在的表',
                 'summary': '孤儿求和脚本', 'script': '求和脚本.py',
                 'script_path': 'D:/x/求和脚本.py',
                 'output_cells': [{'row': 4}],
                 'replay_cfg': {'direction': '对列处理',
                                'range': [0, 3, 3, 3]},
                 'ref_cells': [{'range': [0, 3, 3, 3]}],
                 'formula': {'text': '=SUM({c}1:{c}4)', 'cell0': [4, 0]}})
# 单独构造 controller 用 sheet_models 调 compute_formula_values
from controllers.dynamic_controller import DynamicController
model2 = make_model([['1', '2', '3'], ['4', '5', '6']])
ctrl2 = DynamicController(store, model2, None)
ctrl2.set_model(model2, '表1')
ctrl2._formula_entries = []
ctrl2._scripts = store.get_scripts()
# sheet_models 只有 '表1'（孤儿条目 sheet 不匹配 → 应跳过，不写 D5）
ctrl2.compute_formula_values([('表1', model2)])
check('孤儿条目不写当前模型 D5', model2.value(4, 3) == '')

print()
print('ALL DYNAMIC INTEGRATE TESTS PASSED')
print('ALL DYNAMIC INTEGRATE TESTS PASSED')
print('ALL DYNAMIC INTEGRATE TESTS PASSED')
shutil.rmtree(tmp, ignore_errors=True)
