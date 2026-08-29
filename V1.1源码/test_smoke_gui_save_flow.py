"""保存行为一致性 — GUI 冒烟测试（V1.1）。

验证两类保存路径在 csv / xlsx 上的行为与多 sheet 数据保全：
A. 打开的文件（有路径）→ 编辑 → 保存 = 自动更新，无弹窗
B. 新建的表格（无路径）→ 保存 = 弹窗命名 → 写表格库；同名检测 → 更新替换
C. xlsx 多 sheet：自动更新/命名保存/同名替换均整本写回，不丢 sheet
"""
import os
import sys

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
sys.path.insert(0, r'D:\Cloude Code\自制表格软件\代码输出库\源码')

from PyQt6.QtWidgets import QApplication
app = QApplication([])

TMP = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_tmp_save_flow')
os.makedirs(TMP, exist_ok=True)

from file_io import xlsx_handler
from file_io.file_handler import FileHandler


def check(name, cond):
    if not cond:
        raise AssertionError(f'FAIL: {name}')
    print('PASS:', name)


from views.main_window import MainWindow
from config.settings import AppSettings

settings = AppSettings()
settings.load()
win = MainWindow(settings)
win.show()
for _ in range(20):
    app.processEvents()

# 让"表格库"指向临时目录，避免污染真实库
lib = os.path.join(TMP, '库')
os.makedirs(lib, exist_ok=True)
win._file_io._get_file_folder = lambda: lib

# ------------------------------------------------------------------
# A1. 打开 csv → 编辑 → 保存 = 自动更新（无弹窗）
# ------------------------------------------------------------------
csv_src = os.path.join(lib, '台账.csv')
with open(csv_src, 'w', encoding='utf-8') as f:
    f.write('品名,数量\n苹果,3\n')
check('打开 csv', win._file_io.open_file(csv_src))
win._rebuild_sheet_tabs(); win._activate_sheet(0)
win._model.set_value(1, 1, '5')
check('保存返回 True（自动更新路径）', win._file_io.save_file())
with open(csv_src, encoding='utf-8') as f:
    check('csv 已自动更新', '苹果,5' in f.read())
check('保存后干净', not win._file_io.any_dirty)

# ------------------------------------------------------------------
# A2. 打开多 sheet xlsx → 编辑两表 → 保存 = 整本自动更新
# ------------------------------------------------------------------
xlsx_src = os.path.join(lib, '账本.xlsx')
xlsx_handler.write_all(xlsx_src, [
    ('收入', [['日期', '金额'], ['1日', '100']]),
    ('支出', [['日期', '金额'], ['1日', '30']]),
])
check('打开 xlsx', win._file_io.open_file(xlsx_src))
win._rebuild_sheet_tabs(); win._activate_sheet(0)
win._model.set_value(1, 1, '200')      # 收入 100→200
win._on_sheet_tab_changed(1)
win._model.set_value(1, 1, '80')       # 支出 30→80
check('保存返回 True', win._file_io.save_file())
back = xlsx_handler.load_all(xlsx_src)
check('sheet 数保留', [n for n, _ in back] == ['收入', '支出'])
check('收入表修改已保存', back[0][1][1][1] == '200')
check('支出表修改已保存', back[1][1][1][1] == '80')
check('保存后全部干净', not win._file_io.any_dirty)

# ------------------------------------------------------------------
# B1. 新建 csv → 保存 → 弹窗命名 → 写表格库（自动补 .csv）
# ------------------------------------------------------------------
from PyQt6.QtWidgets import QInputDialog
win._on_new()   # 默认 csv
win._model.set_value(0, 0, '新表数据')
orig_get_text = QInputDialog.getText
QInputDialog.getText = staticmethod(lambda *a, **k: ('新建台账', True))
check('命名保存返回 True', win._file_io.save_file())
QInputDialog.getText = orig_get_text
p = os.path.join(lib, '新建台账.csv')
check('csv 已写入表格库', os.path.isfile(p))
check('csv 文件格式正确', win._file_io.current_model.file_format == 'csv')

# ------------------------------------------------------------------
# B2. 新建 csv → 同名已存在 → 弹窗选「更新」→ 覆盖替换
# ------------------------------------------------------------------
with open(p, 'w', encoding='utf-8') as f:
    f.write('旧内容\n')
win._on_new()   # 再新建一个 csv
win._model.set_value(0, 0, '新内容覆盖')
orig_get_text = QInputDialog.getText
QInputDialog.getText = staticmethod(lambda *a, **k: ('新建台账', True))
orig_dialog = win._file_io._show_duplicate_dialog
win._file_io._show_duplicate_dialog = lambda matches: ('update', matches[0])
check('同名更新返回 True', win._file_io.save_file())
win._file_io._show_duplicate_dialog = orig_dialog
QInputDialog.getText = orig_get_text
with open(p, encoding='utf-8') as f:
    check('csv 已覆盖为新内容', '新内容覆盖' in f.read() and '旧内容' not in f.read())

# ------------------------------------------------------------------
# C1. 新建 xlsx（多 sheet）→ 命名保存 → 整本写入表格库
# ------------------------------------------------------------------
win._on_new_as('xlsx')
win._model.set_value(0, 0, '表A数据')
win._file_io.add_sheet('辅助表')
win._file_io.set_current_sheet(1)
win._file_io.current_model.set_value(0, 0, '表B数据')
win._file_io.set_current_sheet(0)
orig_get_text = QInputDialog.getText
QInputDialog.getText = staticmethod(lambda *a, **k: ('工作簿', True))
check('xlsx 命名保存返回 True', win._file_io.save_file())
QInputDialog.getText = orig_get_text
p2 = os.path.join(lib, '工作簿.xlsx')
check('xlsx 已写入表格库', os.path.isfile(p2))
back2 = xlsx_handler.load_all(p2)
check('两表都保存（不丢 sheet）', [n for n, _ in back2] == ['Sheet1', '辅助表'])
check('表A数据保留', back2[0][1][0][0] == '表A数据')
check('表B数据保留', back2[1][1][0][0] == '表B数据')
check('保存后全部干净', not win._file_io.any_dirty)

# ------------------------------------------------------------------
# C2. 新建 xlsx → 同名已存在（含旧 sheet）→ 弹窗选「更新」→ 覆盖且新 sheet 生效
# ------------------------------------------------------------------
check('重开同名 xlsx', win._file_io.open_file(p2))
win._rebuild_sheet_tabs(); win._activate_sheet(0)
win._model.set_value(0, 0, '改了A')
win._on_sheet_tab_changed(1)
win._model.set_value(0, 0, '改了B')
check('保存返回 True', win._file_io.save_file())
back3 = xlsx_handler.load_all(p2)
check('更新后 sheet 保留', [n for n, _ in back3] == ['Sheet1', '辅助表'])
check('A 表更新生效', back3[0][1][0][0] == '改了A')
check('B 表更新生效', back3[1][1][0][0] == '改了B')

# ------------------------------------------------------------------
# C3. 新建 xlsx → 命名时带扩展名 → 不重复补
# ------------------------------------------------------------------
win._on_new_as('xlsx')
win._model.set_value(0, 0, '带名保存')
orig_get_text = QInputDialog.getText
QInputDialog.getText = staticmethod(lambda *a, **k: ('明确名字.xlsx', True))
check('带扩展名保存返回 True', win._file_io.save_file())
QInputDialog.getText = orig_get_text
p3 = os.path.join(lib, '明确名字.xlsx')
check('未重复补扩展名', os.path.isfile(p3))
back4 = xlsx_handler.load_all(p3)
check('带名保存单表', len(back4) == 1)

# ------------------------------------------------------------------
# C4. 打开多 sheet → 修改后「另存为」新 xlsx → 原文件不动、新文件整本
# ------------------------------------------------------------------
win._file_io.open_file(xlsx_src)
win._rebuild_sheet_tabs(); win._activate_sheet(0)
win._model.set_value(1, 1, '999')
new_path = os.path.join(lib, '另存工作簿.xlsx')
check('另存为 True', win._file_io._do_save_as(new_path))
orig_back = xlsx_handler.load_all(xlsx_src)
check('原文件未被改动', orig_back[0][1][1][1] == '200')
new_back = xlsx_handler.load_all(new_path)
check('另存文件整本含修改', new_back[0][1][1][1] == '999')
check('另存后模型指向新路径', win._file_io.current_model.file_path == new_path)

import shutil
shutil.rmtree(TMP, ignore_errors=True)
print('ALL SAVE-FLOW TESTS PASSED')
