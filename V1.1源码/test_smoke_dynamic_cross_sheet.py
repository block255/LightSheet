"""跨表公式测试：引擎跨表求值 + 动态触发跨表重算。"""
import os, sys, shutil
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
sys.path.insert(0, r'D:\Cloude Code\自制表格软件\代码输出库\源码')
from PyQt6.QtWidgets import QApplication
app = QApplication([])
from models.ext_store import ExtStore
from controllers.dynamic_controller import DynamicController
from models.spreadsheet_model import SpreadsheetModel

def check(name, cond):
    if not cond:
        raise AssertionError('FAIL: ' + name)
    print('PASS:', name)

tmp = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_tmp_cross')
shutil.rmtree(tmp, ignore_errors=True)
os.makedirs(tmp)
lib = os.path.join(tmp, 'lib'); os.makedirs(lib)
xlsx_path = os.path.join(lib, 't.xlsx'); open(xlsx_path, 'w').close()

def make_model(matrix):
    m = SpreadsheetModel(); m.load_2d(matrix)
    m.file_format = 'xlsx'; m.file_path = xlsx_path
    return m

m_sale = make_model([['商品','单价','数量','销售额'],
                     ['苹果',3,10,''],['香蕉',2,15,''],['橙子',4,8,'']])
m_stock = make_model([['商品','库存','预警线','状态'],
                      ['苹果',30,20,''],['香蕉',5,20,''],['橙子',25,10,'']])
m_sum = make_model([['项目','数值'],['总销售额',''],['最高单价',''],['平均库存','']])

store = ExtStore(xlsx_path, lib)
# 跨表条目（汇总表 B2 = SUM(销售表!D2:D4)）
store.add_entry({'kind': 'formula', 'sheet': '汇总表',
                 'output': {'region': [1, 1, 1, 1]},
                 'refs': [{'sheet': '销售表', 'range': [1, 3, 3, 3]}],
                 'formula': {'text': '=SUM(销售表!D2:D4)'}})
# 同表条目（销售表 D2/D3/D4 = B*C）
for i, (r, c) in enumerate([(1, 2), (2, 2), (3, 2)]):
    store.add_entry({'kind': 'formula', 'sheet': '销售表',
                     'output': {'region': [r, 3, r, 3]},
                     'refs': [{'range': [r, 1, r, 2]}],
                     'formula': {'text': f'=B{r+1}*C{r+1}'}})

ctrl = DynamicController(store, m_sale, None)
ctrl._formula_entries = [e for e in store.get_entries()
                         if e.get('kind') == 'formula']
ctrl.set_sheet_models({'销售表': m_sale, '库存表': m_stock, '汇总表': m_sum})
store.set_dynamic_mode(True)

# 打开算值（按 sheet 各自算）
ctrl.compute_formula_values([('销售表', m_sale), ('库存表', m_stock),
                             ('汇总表', m_sum)])
check('销售表 D2=30', m_sale.value(1, 3) == '30')
check('汇总表 B2=92（跨表SUM）', m_sum.value(1, 1) == '92')

# 编辑触发跨表：改销售表 C2=20 → D2=60、D5... 汇总表 B2=SUM(60,30,32)=122
ctrl.set_model(m_sale, '销售表')
m_sale.set_value(1, 2, '20')   # C2=20
ctrl.on_cell_edited(1, 2, '销售表')
check('编辑销售表 D2 重算=60', m_sale.value(1, 3) == '60')
check('跨表触发汇总表 B2=122', m_sum.value(1, 1) == '122')

# 编辑库存表 → 汇总表 AVERAGE 条目（若存在）——当前只有 SUM 条目，改库存不影响
# regions_contain 跨表：编辑销售表不触发引用库存表的条目（无此条目，跳过）
print()
print('ALL CROSS-SHEET TESTS PASSED')
print('ALL CROSS-SHEET TESTS PASSED')
print('ALL CROSS-SHEET TESTS PASSED')
shutil.rmtree(tmp, ignore_errors=True)
