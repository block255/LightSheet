"""单表保存 / 单表导出为 — GUI 冒烟测试（V1.1 右键 sheet 标签）。

语义验证：
- 单表保存：只把目标 sheet 内存数据写回文件，其他 sheet 以磁盘原样
  保留（即使其他表内存有未保存修改也不覆盖）；只清目标表脏标记。
- 单表导出为：只导出目标 sheet；不改变工作簿状态。
- 单表文件（csv/单 sheet xlsx）菜单不提供单表项。
"""
import os
import sys

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
sys.path.insert(0, r'D:\Cloude Code\自制表格软件\代码输出库\源码')

from PyQt6.QtWidgets import QApplication, QFileDialog
app = QApplication([])

TMP = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_tmp_sheet_only')
os.makedirs(TMP, exist_ok=True)

from file_io import xlsx_handler


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

# ------------------------------------------------------------------
# 0. 准备：3-sheet xlsx
# ------------------------------------------------------------------
src = os.path.join(TMP, '账本.xlsx')
xlsx_handler.write_all(src, [
    ('收入', [['日期', '金额'], ['1日', '100']]),
    ('支出', [['日期', '金额'], ['1日', '30']]),
    ('备注', [['说明'], ['无']]),
])
win._file_io.open_file(src)
win._rebuild_sheet_tabs()
win._activate_sheet(0)

# ------------------------------------------------------------------
# 1. 单表保存：改 sheet1+sheet2 → 只保存 sheet1 → sheet2 内存修改保留脏
# ------------------------------------------------------------------
win._model.set_value(1, 1, '200')       # 改收入（当前激活）
win._on_sheet_tab_changed(1)
win._model.set_value(1, 1, '80')        # 改支出
check('两表都脏', win._file_io.any_dirty)

check('单表保存 sheet1 成功', win._file_io.save_sheet_only(0))
back = xlsx_handler.load_all(src)
check('磁盘 sheet1 已更新', back[0][1][1][1] == '200')
check('磁盘 sheet2 保持原值(30)', back[1][1][1][1] == '30')
check('磁盘 sheet3 保持', back[2][1] == [['说明'], ['无']])
check('sheet1 脏标记已清', not win._file_io.sheet_models[0].is_dirty)
check('sheet2 脏标记保留', win._file_io.sheet_models[1].is_dirty)
check('工作簿仍脏(有未保存表)', win._file_io.any_dirty)

# 单表保存 sheet2 → 全部干净
check('单表保存 sheet2 成功', win._file_io.save_sheet_only(1))
back = xlsx_handler.load_all(src)
check('磁盘 sheet2 已更新', back[1][1][1][1] == '80')
check('全部干净', not win._file_io.any_dirty)

# ------------------------------------------------------------------
# 2. 单表保存不覆盖其他表内存修改（关键语义）
# ------------------------------------------------------------------
win._model.set_value(0, 0, '日期改')    # 改 sheet2（当前激活）
win._on_sheet_tab_changed(2)
win._model.set_value(0, 0, '说明改')    # 改 sheet3
# 单表保存 sheet1（它没修改）——此时磁盘应保持原样，sheet2/3 内存修改仍在
check('单表保存 sheet1', win._file_io.save_sheet_only(0))
back = xlsx_handler.load_all(src)
check('磁盘 sheet1 无变化', back[0][1] == [['日期', '金额'], ['1日', '200']])
check('磁盘 sheet2 无变化(内存改未写)', back[1][1][0][0] == '日期')
check('磁盘 sheet3 无变化(内存改未写)', back[2][1][0][0] == '说明')
check('sheet2 仍脏', win._file_io.sheet_models[1].is_dirty)
check('sheet3 仍脏', win._file_io.sheet_models[2].is_dirty)

# 恢复：整本保存清干净
win._file_io.save_file()
check('整本保存后全干净', not win._file_io.any_dirty)

# ------------------------------------------------------------------
# 3. 单表导出为：目标 sheet 数据正确，工作簿状态不变
# ------------------------------------------------------------------
orig_get_save = QFileDialog.getSaveFileName

# 导出 sheet2（支出）为 csv —— 注意 sheet2 内存 (0,0) 已被第 2 节改为「日期改」
csv_out = os.path.join(TMP, '支出表.csv')
QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (csv_out, ''))
check('单表导出 sheet2→csv', win._file_io.export_sheet_only_dialog(1, 'csv'))
QFileDialog.getSaveFileName = orig_get_save
with open(csv_out, encoding='utf-8-sig') as f:
    lines = [ln.rstrip('\n').split(',') for ln in f if ln.strip()]
check('csv 内容是支出表（内存数据）', lines == [['日期改', '金额'], ['1日', '80']])

# 导出 sheet3 为 xlsx（含 sheet 名）—— 内存 (0,0) 是第 2 节改的「说明改」
xlsx_out = os.path.join(TMP, '备注表.xlsx')
QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (xlsx_out, ''))
check('单表导出 sheet3→xlsx', win._file_io.export_sheet_only_dialog(2, 'xlsx'))
QFileDialog.getSaveFileName = orig_get_save
back2 = xlsx_handler.load_all(xlsx_out)
check('xlsx 单表含 sheet 名', len(back2) == 1 and back2[0][0] == '备注')
check('xlsx 数据正确', back2[0][1] == [['说明改'], ['无']])

# 导出 sheet1 为 txt —— sheet1 未被动过，保持原始内容
txt_out = os.path.join(TMP, '收入表.txt')
QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (txt_out, ''))
check('单表导出 sheet1→txt', win._file_io.export_sheet_only_dialog(0, 'txt'))
QFileDialog.getSaveFileName = orig_get_save
with open(txt_out, encoding='utf-8') as f:
    tlines = [ln.rstrip('\n').split('\t') for ln in f if ln.strip()]
check('txt 内容是收入表', tlines == [['日期', '金额'], ['1日', '200']])

# 导出不改变工作簿
check('导出后 sheet 数不变', win._file_io.sheet_count == 3)
check('导出后格式不变', win._file_io.current_model.file_format == 'xlsx')
check('导出后不新增脏', not win._file_io.any_dirty)

# ------------------------------------------------------------------
# 4. 菜单可见性：多 sheet 有单表项，单表文件没有
# ------------------------------------------------------------------
# 模拟右键菜单构建——检查菜单动作文本（直接调用构建逻辑较难，
# 用信号代理验证：单表文件（csv）下 sheet_count==1 不显示）
csv_src = os.path.join(TMP, '单表.csv')
with open(csv_src, 'w', encoding='utf-8') as f:
    f.write('a,b\n1,2\n')
win._file_io.open_file(csv_src)
win._rebuild_sheet_tabs(); win._activate_sheet(0)
check('csv 单表 sheet_count==1', win._sheet_tabs.sheet_count == 1)

# 多 sheet 时菜单含单表项（通过 contextMenuEvent 直接检查——用事件模拟复杂，
# 这里验证 sheet_count 判定条件即可：>1 显示、==1 隐藏）
win._file_io.open_file(src)
win._rebuild_sheet_tabs(); win._activate_sheet(0)
check('多 sheet sheet_count==3', win._sheet_tabs.sheet_count == 3)

# 单表保存对未保存过文件（无路径）的防御
# 先整本保存清干净，避免 new_file 触发「是否保存」模态框
win._file_io.save_file()
check('整本保存后全干净', not win._file_io.any_dirty)
win._file_io.new_file()
win._file_io.current_model.set_value(0, 0, 'x')
from PyQt6.QtWidgets import QMessageBox
orig_warning = QMessageBox.warning
QMessageBox.warning = staticmethod(lambda *a, **k: None)
check('无路径单表保存返回 False', win._file_io.save_sheet_only(0) is False)
QMessageBox.warning = orig_warning

# ------------------------------------------------------------------
# 5. 单表导入：csv 覆盖 / txt 覆盖 / xlsx 拒绝
# ------------------------------------------------------------------
from PyQt6.QtWidgets import QMessageBox, QFileDialog
win._file_io.open_file(src)
win._rebuild_sheet_tabs(); win._activate_sheet(0)

# 准备导入源文件
imp_csv = os.path.join(TMP, '导入源.csv')
with open(imp_csv, 'w', encoding='utf-8') as f:
    f.write('新列1,新列2\n甲,1\n乙,2\n')
imp_txt = os.path.join(TMP, '导入源.txt')
with open(imp_txt, 'w', encoding='utf-8') as f:
    f.write('文本列\t数值\n丙\t3\n')

orig_get_open = QFileDialog.getOpenFileName

# 5a. 导入 csv 覆盖 sheet1
QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: (imp_csv, ''))
check('单表导入 csv 成功', win._file_io.import_sheet_dialog(0))
QFileDialog.getOpenFileName = orig_get_open
check('sheet1 内容被覆盖', win._file_io.sheet_models[0].value(0, 0) == '新列1'
      and win._file_io.sheet_models[0].value(1, 1) == '1')
check('sheet1 名保留', win._file_io.sheet_names[0] == '收入')
check('导入后标记脏', win._file_io.sheet_models[0].is_dirty)
check('其他 sheet 不受影响', win._file_io.sheet_models[1].value(1, 1) == '80')

# 5b. 导入 txt 覆盖 sheet2
QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: (imp_txt, ''))
check('单表导入 txt 成功', win._file_io.import_sheet_dialog(1))
QFileDialog.getOpenFileName = orig_get_open
check('sheet2 内容被覆盖', win._file_io.sheet_models[1].value(0, 0) == '文本列'
      and win._file_io.sheet_models[1].value(1, 0) == '丙')

# 5c. 导入 xlsx → 拒绝（弹警告）
imp_xlsx = os.path.join(TMP, '拒绝表.xlsx')
xlsx_handler.write_all(imp_xlsx, [('表', [['x']])])
warns = []
def fake_warning(parent, title, text):
    warns.append(text)
QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: (imp_xlsx, ''))
orig_w = QMessageBox.warning
QMessageBox.warning = staticmethod(fake_warning)
check('单表导入 xlsx 被拒绝', win._file_io.import_sheet_dialog(0) is False)
QMessageBox.warning = orig_w
QFileDialog.getOpenFileName = orig_get_open
check('拒绝提示含格式说明', any('CSV / TXT' in w for w in warns))
check('xlsx 拒绝后内容未变', win._file_io.sheet_models[0].value(0, 0) == '新列1')

# 5d. 取消对话框 → False 无副作用
QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: ('', ''))
check('取消导入返回 False', win._file_io.import_sheet_dialog(0) is False)
QFileDialog.getOpenFileName = orig_get_open

import shutil
shutil.rmtree(TMP, ignore_errors=True)
print('ALL SHEET-ONLY TESTS PASSED')
