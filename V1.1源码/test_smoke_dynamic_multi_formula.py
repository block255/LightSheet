"""多 sheet 公式按对应模型算值测试（修复跨 sheet 错位污染）。"""
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

tmp = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_tmp_multi')
shutil.rmtree(tmp, ignore_errors=True)
os.makedirs(tmp)
lib = os.path.join(tmp, 'lib'); os.makedirs(lib)
xlsx_path = os.path.join(lib, 't.xlsx'); open(xlsx_path, 'w').close()

store = ExtStore(xlsx_path, lib)
# 两个 sheet 的 formula 条目
store.add_entry({'kind': 'formula', 'sheet': '销售表',
                 'output': {'region': [1, 3, 1, 3]},
                 'refs': [{'range': [1, 1, 1, 2]}],
                 'formula': {'text': '=B2*C2'}})
store.add_entry({'kind': 'formula', 'sheet': '库存表',
                 'output': {'region': [1, 3, 1, 3]},
                 'refs': [{'range': [1, 1, 1, 2]}],
                 'formula': {'text': '=IF(B2<C2,"补货","正常")'}})

def make_model(matrix):
    m = SpreadsheetModel(); m.load_2d(matrix)
    m.file_format = 'xlsx'; m.file_path = xlsx_path
    return m

m_sale = make_model([['商品','单价','数量','销售额'],['苹果',3,10,'']])
m_stock = make_model([['商品','库存','预警线','状态'],['苹果',30,20,'']])

ctrl = DynamicController(store, m_sale, None)
ctrl._formula_entries = [e for e in store.get_entries()
                         if e.get('kind') == 'formula']

# 修前行为：无 sheet_models → 用当前模型（销售表）算所有 → 库存表条目污染销售表
ctrl.compute_formula_values()  # 旧路径（单 sheet 场景）
# 但这是多 sheet——应传 sheet_models
ctrl.compute_formula_values([('销售表', m_sale), ('库存表', m_stock)])
check('销售表 D2 = B2*C2 = 30', m_sale.value(1, 3) == '30')
check('库存表 D2 = IF 正常', m_stock.value(1, 3) == '正常')
# 销售表不被库存表公式污染（D2 不是"补货"）
check('销售表未被污染', m_sale.value(1, 3) != '补货')

# 缺省路径（单 sheet）兼容：单 sheet 工作簿无参调用用当前模型
store2 = ExtStore(xlsx_path, lib)
store2.load()
store2._data = {'version': 2, 'entries': []} if False else None
store2.remove()  # 清掉旧扩展
store2 = ExtStore(xlsx_path, lib)
store2.add_entry({'kind': 'formula', 'sheet': '销售表',
                  'output': {'region': [1, 3, 1, 3]},
                  'refs': [{'range': [1, 1, 1, 2]}],
                  'formula': {'text': '=B2*C2'}})
ctrl2 = DynamicController(store2, m_sale, None)
ctrl2._formula_entries = [e for e in store2.get_entries()
                          if e.get('kind') == 'formula']
ctrl2.compute_formula_values()   # 无参：单 sheet 用当前模型
check('单 sheet 无参兼容', m_sale.value(1, 3) == '30')

print()
print('ALL MULTI-SHEET FORMULA TESTS PASSED')
print('ALL MULTI-SHEET FORMULA TESTS PASSED')
print('ALL MULTI-SHEET FORMULA TESTS PASSED')
shutil.rmtree(tmp, ignore_errors=True)
