"""xlsx 多 sheet 读写 — 冒烟测试（V1.1）。

覆盖：
- write_all / load_all 多 sheet 往返
- sheet 名清理（非法字符 / 重名 / 超长 / 空名）
- FileHandler.load_sheets / save_sheets 分发（xlsx 整本 / csv 单表）
- FileIOController 打开多 sheet 工作簿、切换 sheet、整本保存
"""
import os
import sys

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
sys.path.insert(0, r'D:\Cloude Code\自制表格软件\代码输出库\源码')

from PyQt6.QtWidgets import QApplication
app = QApplication([])

TMP = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_tmp_xlsx')
os.makedirs(TMP, exist_ok=True)


def check(name, cond):
    if not cond:
        raise AssertionError(f'FAIL: {name}')
    print('PASS:', name)


# ------------------------------------------------------------------
# 1. xlsx_handler 多 sheet 往返
# ------------------------------------------------------------------
from file_io import xlsx_handler

path1 = os.path.join(TMP, 'multi.xlsx')
sheets_in = [
    ('销售数据', [['品名', '数量'], ['苹果', '3'], ['香蕉', '5']]),
    ('库存数据', [['编号', '库存'], ['A1', '10']]),
    ('员工表', [['姓名'], ['张三']]),
]
xlsx_handler.write_all(path1, sheets_in)
sheets_out = xlsx_handler.load_all(path1)
check('sheet 数量一致', [n for n, _ in sheets_out] == ['销售数据', '库存数据', '员工表'])
check('sheet1 数据一致', sheets_out[0][1] == sheets_in[0][1])
check('sheet2 数据一致', sheets_out[1][1] == sheets_in[1][1])
check('sheet3 数据一致', sheets_out[2][1] == sheets_in[2][1])
check('顺序保持', sheets_out[0][0] == '销售数据' and sheets_out[2][0] == '员工表')

# 单 sheet 兼容
path2 = os.path.join(TMP, 'single.xlsx')
xlsx_handler.write(path2, [['a', 'b'], ['1', '2']])
rows = xlsx_handler.load(path2)
check('load 取第一个 sheet', rows == [['a', 'b'], ['1', '2']])

# ------------------------------------------------------------------
# 2. sheet 名清理
# ------------------------------------------------------------------
from file_io.xlsx_handler import _unique_sheet_name
used: set[str] = set()
check('非法字符替换', _unique_sheet_name('a/b\\c?d*e[f]g:h', used) == 'a_b_c_d_e_f_g_h')
# 重名检查（序号逻辑）
u2 = {'数据'}
n2 = _unique_sheet_name('数据', u2)
check('重名生成序号', n2 == '数据2')
u2.add(n2)
check('再次重名生成序号3', _unique_sheet_name('数据', u2) == '数据3')
# 超长截断
long_name = '很' * 40
n3 = _unique_sheet_name(long_name, set())
check('超长截断31字符', len(n3) == 31)
# 空名兜底
n4 = _unique_sheet_name('', set())
check('空名兜底 Sheet1', n4 == 'Sheet1')
n5 = _unique_sheet_name('///', set())
check('非法字符替换为下划线', n5 == '___')

# 实际写入重名 sheet → 不报错且可读回
path3 = os.path.join(TMP, 'dup.xlsx')
xlsx_handler.write_all(path3, [('表', [['1']]), ('表', [['2']])])
dup_out = xlsx_handler.load_all(path3)
check('重名写入成功且名称唯一', len({n for n, _ in dup_out}) == 2)

# ------------------------------------------------------------------
# 3. FileHandler 分发
# ------------------------------------------------------------------
from file_io.file_handler import FileHandler

fs = FileHandler.load_sheets(path1)
check('load_sheets xlsx 多表', [n for n, _ in fs] == ['销售数据', '库存数据', '员工表'])

csv_path = os.path.join(TMP, 't.csv')
with open(csv_path, 'w', encoding='utf-8') as f:
    f.write('a,b\n1,2\n')
cs = FileHandler.load_sheets(csv_path)
check('load_sheets csv 单表', len(cs) == 1 and cs[0][1] == [['a', 'b'], ['1', '2']])

# save_sheets：xlsx 整本、csv 只写第一个
path4 = os.path.join(TMP, 'round.xlsx')
FileHandler.save_sheets(path4, sheets_in)
check('save_sheets xlsx 整本',
      [n for n, _ in FileHandler.load_sheets(path4)] == ['销售数据', '库存数据', '员工表'])
csv_out = os.path.join(TMP, 'round.csv')
FileHandler.save_sheets(csv_out, sheets_in)
with open(csv_out, encoding='utf-8') as f:
    check('save_sheets csv 只写第一表', f.read().strip() == '品名,数量\n苹果,3\n香蕉,5')

# ------------------------------------------------------------------
# 4. FileIOController 多 sheet 工作簿
# ------------------------------------------------------------------
from controllers.file_io_controller import FileIOController
from config.settings import AppSettings

settings = AppSettings()
settings.load()
ctrl = FileIOController(settings)
model0 = ctrl._current_model = None
from models.spreadsheet_model import SpreadsheetModel
initial = SpreadsheetModel()
ctrl.set_model(initial)

ok = ctrl.open_file(path1)
check('open_file 成功', ok)
check('工作簿 3 个 sheet', ctrl.sheet_count == 3)
check('sheet 名称正确', ctrl.sheet_names == ['销售数据', '库存数据', '员工表'])
check('激活第一个 sheet', ctrl.current_sheet_index == 0)
check('当前表数据为 sheet1',
      ctrl.current_model.value(0, 0) == '品名')

# 切换 sheet
ctrl.set_current_sheet(1)
check('切换到 sheet2', ctrl.current_sheet_name == '库存数据')
check('sheet2 数据', ctrl.current_model.value(1, 0) == 'A1')
ctrl.set_current_sheet(2)
check('切换到 sheet3', ctrl.current_model.value(0, 0) == '姓名')
ctrl.set_current_sheet(99)  # 越界忽略
check('越界切换忽略', ctrl.current_sheet_index == 2)

# 修改 sheet1 后整本保存 → 全部 sheet 保留
ctrl.set_current_sheet(0)
ctrl.current_model.set_value(1, 1, '99')
check('修改后 sheet1 脏', ctrl.current_model.is_dirty)
path5 = os.path.join(TMP, 'save_back.xlsx')
ctrl._do_save_as(path5)
back = FileHandler.load_sheets(path5)
check('整本保存 sheet 数不变', len(back) == 3)
check('sheet1 修改已写入', back[0][1][1][1] == '99')
check('sheet2 数据保留', back[1][1] == sheets_in[1][1])
check('保存后全部干净', not ctrl.any_dirty)

# 另存为 csv → 只写当前激活 sheet（sheet1）
path6 = os.path.join(TMP, 'only_current.csv')
ctrl._do_save_as(path6)
with open(path6, encoding='utf-8') as f:
    content = f.read()
check('另存 csv 只含当前 sheet', '品名' in content and '库存' not in content)

# 脏状态：改 sheet2 后 any_dirty 为 True
ctrl.set_current_sheet(1)
ctrl.current_model.set_value(0, 0, '改')
check('任一 sheet 脏检测', ctrl.any_dirty)
check('当前 sheet 名正确', ctrl.current_sheet_name == '库存数据')

# 新建：重置为单 sheet
ctrl2 = FileIOController(settings)
ctrl2.set_model(SpreadsheetModel())
ctrl2.new_file()
check('new_file 后单 sheet', ctrl2.sheet_count == 1)

# ------------------------------------------------------------------
# 5. 新增 / 重命名 / 删除 sheet
# ------------------------------------------------------------------
ctrl3 = FileIOController(settings)
ctrl3.set_model(SpreadsheetModel())
ctrl3.open_file(path1)   # 3 个 sheet
check('open 3 sheet', ctrl3.sheet_count == 3)

# 新增：自动命名（找第一个未被占用的 SheetN）
idx = ctrl3.add_sheet()
check('新增自动命名', ctrl3.sheet_names[-1] == 'Sheet1')
check('新增后激活', ctrl3.current_sheet_index == idx == 3)
check('新增 sheet 跟随文件格式', ctrl3.current_model.file_format == 'xlsx')
ctrl3.current_model.set_value(0, 0, '新表数据')
check('新 sheet 可写', ctrl3.current_model.value(0, 0) == '新表数据')

# 新增：指定名字（重名自动避让）
idx2 = ctrl3.add_sheet('销售数据')
check('重名自动避让', ctrl3.sheet_names[-1] == '销售数据2')
idx3 = ctrl3.add_sheet('a/b*c')
check('非法字符清理', ctrl3.sheet_names[-1] == 'a_b_c')

# 重命名
check('重命名成功', ctrl3.rename_sheet(0, '第一表'))
check('重命名生效', ctrl3.sheet_names[0] == '第一表')
check('重命名重名避让', ctrl3.rename_sheet(0, '库存数据') and
      ctrl3.sheet_names[0] == '库存数据2')
check('重命名空名拒绝', not ctrl3.rename_sheet(0, '  '))
check('重命名越界拒绝', not ctrl3.rename_sheet(99, 'x'))

# 删除
ctrl3.set_current_sheet(4)
before = ctrl3.sheet_count
check('删除成功', ctrl3.remove_sheet(4))
check('删除后数量-1', ctrl3.sheet_count == before - 1)
# 删除当前激活的 sheet → 激活原位置的后续 sheet（a_b_c，索引 4）
check('删除后激活相邻', ctrl3.current_sheet_index == 4)
check('删除后激活的是后续表', ctrl3.current_sheet_name == 'a_b_c')
# 全部删光保护：删到只剩 1 个
while ctrl3.sheet_count > 1:
    ctrl3.remove_sheet(ctrl3.sheet_count - 1)
check('删到只剩一个', ctrl3.sheet_count == 1)
check('最后一个不可删', not ctrl3.remove_sheet(0))
check('删除越界拒绝', not ctrl3.remove_sheet(5))

# 新增/重命名/删除后整本保存
ctrl3.add_sheet('最后表')
ctrl3.current_model.set_value(0, 0, 'zzz')
path7 = os.path.join(TMP, 'edited.xlsx')
ctrl3._do_save_as(path7)
final = FileHandler.load_sheets(path7)
check('编辑后保存 sheet 名正确',
      [n for n, _ in final] == ['库存数据2', '最后表'])
check('新表数据已写入', final[-1][1][0][0] == 'zzz')

import shutil
shutil.rmtree(TMP, ignore_errors=True)
print('ALL XLSX MULTI-SHEET TESTS PASSED')
