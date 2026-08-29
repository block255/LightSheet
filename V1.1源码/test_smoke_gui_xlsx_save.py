"""多 sheet xlsx 文件交互 — GUI 端到端冒烟测试（V1.1）。

覆盖场景（真实写盘、重新打开验证）：
1. 打开多 sheet xlsx → 修改 sheet2 → 保存 → 重开验证整本保留+修改生效
2. 另存为 xlsx（新路径）→ 重开验证整本
3. 另存为 csv → 只写当前激活 sheet
4. 导出 xlsx（模拟文件对话框）→ 重开验证整本
5. 导出 csv → 只写当前 sheet
6. 新建 → 单 sheet、标签条隐藏、格式清空
7. 新建/切换后的脏检查（any_dirty）
8. 保存后全部 sheet 干净标记
"""
import os
import sys

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
sys.path.insert(0, r'D:\Cloude Code\自制表格软件\代码输出库\源码')

from PyQt6.QtWidgets import QApplication
app = QApplication([])

TMP = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_tmp_gui_save')
os.makedirs(TMP, exist_ok=True)

from file_io import xlsx_handler
from file_io.file_handler import FileHandler


def check(name, cond):
    if not cond:
        raise AssertionError(f'FAIL: {name}')
    print('PASS:', name)


def read_xlsx(path):
    return xlsx_handler.load_all(path)


def read_csv(path):
    with open(path, encoding='utf-8-sig') as f:
        return [ln.rstrip('\n').split(',') for ln in f if ln.strip()]


from views.main_window import MainWindow
from config.settings import AppSettings

settings = AppSettings()
settings.load()
win = MainWindow(settings)
win.show()
for _ in range(20):
    app.processEvents()

# ------------------------------------------------------------------
# 0. 准备多 sheet 文件
# ------------------------------------------------------------------
src = os.path.join(TMP, '工作簿.xlsx')
xlsx_handler.write_all(src, [
    ('销售', [['品名', '数量'], ['苹果', '3']]),
    ('库存', [['编号', '库存'], ['A1', '10']]),
    ('员工', [['姓名'], ['张三']]),
])

# ------------------------------------------------------------------
# 1. 打开 → 修改 sheet2 → 保存 → 重开验证
# ------------------------------------------------------------------
check('打开多 sheet 成功', win._file_io.open_file(src))
win._rebuild_sheet_tabs()
win._activate_sheet(0)
check('工作簿 3 sheet', win._file_io.sheet_count == 3)

# 切到 sheet2 修改
win._on_sheet_tab_changed(1)
win._model.set_value(1, 1, '99')   # 库存 A1 行库存改 99
check('sheet2 修改后脏', win._file_io.any_dirty)

# 保存
check('保存成功', win._file_io.save_file())
check('保存后全部干净', not win._file_io.any_dirty)

# 重新打开验证整本保留 + 修改生效
back = read_xlsx(src)
check('重开 sheet 数不变', [n for n, _ in back] == ['销售', '库存', '员工'])
check('sheet1 数据保留', back[0][1] == [['品名', '数量'], ['苹果', '3']])
check('sheet2 修改已写入', back[1][1][1][1] == '99')
check('sheet3 数据保留', back[2][1] == [['姓名'], ['张三']])

# ------------------------------------------------------------------
# 2. 另存为 xlsx（新路径）→ 重开验证整本
# ------------------------------------------------------------------
win._on_sheet_tab_changed(0)   # 切回 sheet1
win._model.set_value(0, 0, '改品名')
save_as1 = os.path.join(TMP, '另存整本.xlsx')
check('另存为 xlsx 成功', win._file_io._do_save_as(save_as1))
back2 = read_xlsx(save_as1)
check('另存 xlsx 整本', [n for n, _ in back2] == ['销售', '库存', '员工'])
check('另存 sheet1 修改生效', back2[0][1][0][0] == '改品名')
check('另存后所有模型指向新路径',
      all(m.file_path == save_as1 for _, m in win._file_io._sheets))
check('另存后全部干净', not win._file_io.any_dirty)

# ------------------------------------------------------------------
# 3. 另存为 csv → 只写当前激活 sheet（当前是 sheet1）
# ------------------------------------------------------------------
csv1 = os.path.join(TMP, '只当前表.csv')
check('另存 csv 成功', win._file_io._do_save_as(csv1))
data = read_csv(csv1)
check('csv 只含 sheet1', data == [['改品名', '数量'], ['苹果', '3']])
check('另存 csv 后格式更新', win._file_io.current_model.file_format == 'csv')

# ------------------------------------------------------------------
# 4. 重新打开多 sheet → 导出 xlsx（模拟文件对话框）
# ------------------------------------------------------------------
from PyQt6.QtWidgets import QFileDialog
win._file_io.open_file(src)
win._rebuild_sheet_tabs()
win._activate_sheet(0)

orig_get_save = QFileDialog.getSaveFileName
export_path = os.path.join(TMP, '导出.xlsx')
QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (export_path, ''))
check('导出 xlsx 成功', win._file_io.export_file('xlsx'))
QFileDialog.getSaveFileName = orig_get_save
back3 = read_xlsx(export_path)
check('导出 xlsx 整本', [n for n, _ in back3] == ['销售', '库存', '员工'])
check('导出数据完整', back3[0][1] == [['品名', '数量'], ['苹果', '3']])

# ------------------------------------------------------------------
# 5. 导出 csv → 只写当前激活 sheet（sheet1）
# ------------------------------------------------------------------
orig_get_save = QFileDialog.getSaveFileName
csv2 = os.path.join(TMP, '导出.csv')
QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (csv2, ''))
check('导出 csv 成功', win._file_io.export_file('csv'))
QFileDialog.getSaveFileName = orig_get_save
check('导出 csv 只含当前表', read_csv(csv2) == [['品名', '数量'], ['苹果', '3']])

# ------------------------------------------------------------------
# 6. 导出 xlsx 但当前激活是 sheet2 → 整本仍导出（不丢表）
# ------------------------------------------------------------------
win._on_sheet_tab_changed(1)   # 激活库存
orig_get_save = QFileDialog.getSaveFileName
export_path2 = os.path.join(TMP, '导出2.xlsx')
QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (export_path2, ''))
check('导出 xlsx(激活sheet2) 成功', win._file_io.export_file('xlsx'))
QFileDialog.getSaveFileName = orig_get_save
back4 = read_xlsx(export_path2)
check('激活sheet2仍整本导出', len(back4) == 3 and back4[1][0] == '库存')

# ------------------------------------------------------------------
# 7. 新建 → 单 sheet、标签条隐藏、格式清空
# ------------------------------------------------------------------
win._file_io.new_file()
win._rebuild_sheet_tabs()
win._activate_sheet(0)
check('新建后单 sheet', win._file_io.sheet_count == 1)
check('新建后标签条隐藏', not win._sheet_tabs.isVisible())
check('新建后格式清空', win._file_io.current_model.file_format == '')
check('新建后无文件路径', win._file_io.current_model.file_path is None)

# 新建后导出 xlsx → 单 sheet
orig_get_save = QFileDialog.getSaveFileName
new_xlsx = os.path.join(TMP, '新建导出.xlsx')
QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (new_xlsx, ''))
check('新建导出 xlsx 成功', win._file_io.export_file('xlsx'))
QFileDialog.getSaveFileName = orig_get_save
back5 = read_xlsx(new_xlsx)
check('新建导出单 sheet', len(back5) == 1 and back5[0][1] == [])

# ------------------------------------------------------------------
# 8. 脏检查：切 sheet 后修改他表 → any_dirty 仍为 True
# ------------------------------------------------------------------
win._file_io.open_file(src)
win._rebuild_sheet_tabs()
win._activate_sheet(0)
win._on_sheet_tab_changed(0)
win._model.set_value(0, 0, 'X')     # 改 sheet1
win._on_sheet_tab_changed(2)        # 切到 sheet3（本身没改）
check('切走仍有脏标记', win._file_io.any_dirty)
check('当前 sheet 不脏但工作簿脏',
      not win._file_io.current_model.is_dirty and win._file_io.any_dirty)

# 保存后干净
check('保存成功', win._file_io.save_file())
check('保存后干净', not win._file_io.any_dirty)
back6 = read_xlsx(src)
check('保存后 sheet1 修改生效', back6[0][1][0][0] == 'X')

import shutil
shutil.rmtree(TMP, ignore_errors=True)
print('ALL GUI XLSX FILE-IO TESTS PASSED')
