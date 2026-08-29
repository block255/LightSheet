"""导出为 三格式互转 — GUI 冒烟测试（V1.1）。

覆盖 3×3 组合：
- 源：csv / xlsx（多 sheet）/ txt
- 目标：csv / xlsx / txt
关键断言：
- 数据内容一致（xlsx→csv/txt 只导出当前激活 sheet；→xlsx 整本）
- 导出不改变当前工作簿状态（file_path/file_format/脏标记）
- 导出的 xlsx 打开后再导出仍可往返
"""
import os
import sys

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
sys.path.insert(0, r'D:\Cloude Code\自制表格软件\代码输出库\源码')

from PyQt6.QtWidgets import QApplication, QFileDialog
app = QApplication([])

TMP = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_tmp_export')
os.makedirs(TMP, exist_ok=True)

from file_io import xlsx_handler
from file_io.file_handler import FileHandler


def check(name, cond):
    if not cond:
        raise AssertionError(f'FAIL: {name}')
    print('PASS:', name)


def read_csv(path):
    with open(path, encoding='utf-8-sig') as f:
        return [ln.rstrip('\n').split(',') for ln in f if ln.strip()]


def read_txt(path):
    with open(path, encoding='utf-8') as f:
        return [ln.rstrip('\n').split('\t') for ln in f if ln.strip()]


from views.main_window import MainWindow
from config.settings import AppSettings

settings = AppSettings()
settings.load()
win = MainWindow(settings)
win.show()
for _ in range(20):
    app.processEvents()

# ------------------------------------------------------------------
# 准备三个源文件
# ------------------------------------------------------------------
csv_src = os.path.join(TMP, '源表.csv')
with open(csv_src, 'w', encoding='utf-8') as f:
    f.write('品名,数量\n苹果,3\n香蕉,5\n')

xlsx_src = os.path.join(TMP, '源簿.xlsx')
xlsx_handler.write_all(xlsx_src, [
    ('收入', [['日期', '金额'], ['1日', '100']]),
    ('支出', [['日期', '金额'], ['1日', '30']]),
])

txt_src = os.path.join(TMP, '源文.txt')
with open(txt_src, 'w', encoding='utf-8') as f:
    f.write('姓名\t分数\n张三\t90\n')


def export_as(fmt, path):
    """模拟菜单「导出为」：弹对话框选择路径 → 执行。"""
    orig = QFileDialog.getSaveFileName
    QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (path, ''))
    ok = win._file_io.export_file(fmt)
    QFileDialog.getSaveFileName = orig
    return ok


# ==================================================================
# 1. csv 源 → 三种目标
# ==================================================================
win._file_io.open_file(csv_src)
win._rebuild_sheet_tabs(); win._activate_sheet(0)

# csv → csv
p = os.path.join(TMP, 'csv_转csv.csv')
check('csv→csv 导出成功', export_as('csv', p))
check('csv→csv 数据一致', read_csv(p) == [['品名', '数量'], ['苹果', '3'], ['香蕉', '5']])

# csv → xlsx
p = os.path.join(TMP, 'csv_转xlsx.xlsx')
check('csv→xlsx 导出成功', export_as('xlsx', p))
back = xlsx_handler.load_all(p)
check('csv→xlsx 单 sheet', len(back) == 1)
check('csv→xlsx sheet 名保留源名', back[0][0] == '源表')
check('csv→xlsx 数据一致', back[0][1] == [['品名', '数量'], ['苹果', '3'], ['香蕉', '5']])

# csv → txt
p = os.path.join(TMP, 'csv_转txt.txt')
check('csv→txt 导出成功', export_as('txt', p))
check('csv→txt 数据一致', read_txt(p) == [['品名', '数量'], ['苹果', '3'], ['香蕉', '5']])

# 导出不改变当前工作簿
check('导出后格式仍 csv', win._file_io.current_model.file_format == 'csv')
check('导出后路径不变', win._file_io.current_model.file_path == csv_src)
check('导出后不脏', not win._file_io.any_dirty)

# ==================================================================
# 2. xlsx 源（多 sheet）→ 三种目标
# ==================================================================
win._file_io.open_file(xlsx_src)
win._rebuild_sheet_tabs(); win._activate_sheet(0)

# xlsx → csv（当前激活 sheet1=收入）
p = os.path.join(TMP, 'xlsx_转csv.csv')
check('xlsx→csv 导出成功', export_as('csv', p))
check('xlsx→csv 只含当前激活表', read_csv(p) == [['日期', '金额'], ['1日', '100']])

# 切到 sheet2 再导 csv → 应导出支出
win._on_sheet_tab_changed(1)
p = os.path.join(TMP, 'xlsx_转csv2.csv')
check('xlsx→csv(激活2) 导出成功', export_as('csv', p))
check('xlsx→csv 随激活表变化', read_csv(p) == [['日期', '金额'], ['1日', '30']])

# xlsx → xlsx（整本）
win._on_sheet_tab_changed(0)
p = os.path.join(TMP, 'xlsx_转xlsx.xlsx')
check('xlsx→xlsx 导出成功', export_as('xlsx', p))
back = xlsx_handler.load_all(p)
check('xlsx→xlsx 整本', [n for n, _ in back] == ['收入', '支出'])
check('xlsx→xlsx 数据完整', back[0][1] == [['日期', '金额'], ['1日', '100']]
      and back[1][1] == [['日期', '金额'], ['1日', '30']])

# xlsx → txt（当前激活 sheet1）
p = os.path.join(TMP, 'xlsx_转txt.txt')
check('xlsx→txt 导出成功', export_as('txt', p))
check('xlsx→txt 只含当前表', read_txt(p) == [['日期', '金额'], ['1日', '100']])

# 导出不改变工作簿
check('导出后 sheet 数不变', win._file_io.sheet_count == 2)
check('导出后格式仍 xlsx', win._file_io.current_model.file_format == 'xlsx')
check('导出后路径不变', win._file_io.current_model.file_path == xlsx_src)

# ==================================================================
# 3. txt 源 → 三种目标
# ==================================================================
win._file_io.open_file(txt_src)
win._rebuild_sheet_tabs(); win._activate_sheet(0)

p = os.path.join(TMP, 'txt_转csv.csv')
check('txt→csv 导出成功', export_as('csv', p))
check('txt→csv 数据一致', read_csv(p) == [['姓名', '分数'], ['张三', '90']])

p = os.path.join(TMP, 'txt_转xlsx.xlsx')
check('txt→xlsx 导出成功', export_as('xlsx', p))
back = xlsx_handler.load_all(p)
check('txt→xlsx 单 sheet 数据一致', len(back) == 1
      and back[0][1] == [['姓名', '分数'], ['张三', '90']])

p = os.path.join(TMP, 'txt_转txt.txt')
check('txt→txt 导出成功', export_as('txt', p))
check('txt→txt 数据一致', read_txt(p) == [['姓名', '分数'], ['张三', '90']])

# ==================================================================
# 4. 往返：导出的 xlsx 再打开再导出 csv
# ==================================================================
win._file_io.open_file(os.path.join(TMP, 'xlsx_转xlsx.xlsx'))
win._rebuild_sheet_tabs(); win._activate_sheet(0)
p = os.path.join(TMP, '往返.csv')
check('往返导出成功', export_as('csv', p))
check('往返数据一致', read_csv(p) == [['日期', '金额'], ['1日', '100']])

# ==================================================================
# 5. 取消对话框 → 返回 False 且无副作用
# ==================================================================
orig = QFileDialog.getSaveFileName
QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: ('', ''))
check('取消导出返回 False', win._file_io.export_file('xlsx') is False)
QFileDialog.getSaveFileName = orig

import shutil
shutil.rmtree(TMP, ignore_errors=True)
print('ALL EXPORT TESTS PASSED')
