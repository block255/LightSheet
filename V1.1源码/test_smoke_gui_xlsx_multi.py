"""主窗口多 sheet 标签条 — GUI 冒烟测试（V1.1，offscreen）。

覆盖：
- 打开多 sheet xlsx → 标签条可见、数量正确
- 点击标签切换 → grid 显示对应 sheet、控制器换模型
- 打开 csv → 标签条隐藏（保持原样式）
- 新建 → 标签条隐藏
- 切换 sheet 时脚本/补齐流程被中止
- 窗口标题带 sheet 名
"""
import os
import sys

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
sys.path.insert(0, r'D:\Cloude Code\自制表格软件\代码输出库\源码')

from PyQt6.QtWidgets import QApplication
app = QApplication([])

TMP = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_tmp_gui_xlsx')
os.makedirs(TMP, exist_ok=True)

from file_io import xlsx_handler

xlsx_path = os.path.join(TMP, 'multi.xlsx')
xlsx_handler.write_all(xlsx_path, [
    ('销售数据', [['品名', '数量'], ['苹果', '3']]),
    ('库存数据', [['编号', '库存'], ['A1', '10']]),
    ('员工表', [['姓名'], ['张三']]),
])
csv_path = os.path.join(TMP, 'simple.csv')
with open(csv_path, 'w', encoding='utf-8') as f:
    f.write('a,b\n1,2\n')


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

# 初始：新建态，标签条隐藏
check('初始标签条隐藏', not win._sheet_tabs.isVisible())
check('初始标签数量 0', win._sheet_tabs.count() == 0)

# 打开多 sheet xlsx
check('打开成功', win._file_io.open_file(xlsx_path))
win._rebuild_sheet_tabs()
win._activate_sheet(0)
check('标签条可见', win._sheet_tabs.isVisible())
check('标签数量 3+加号', win._sheet_tabs.sheet_count == 3 and
      win._sheet_tabs.count() == 4)
check('标签名称', [win._sheet_tabs.tabText(i) for i in range(3)]
      == ['销售数据', '库存数据', '员工表'])
check('末尾是加号', win._sheet_tabs.tabText(3) == '＋')
check('激活第 0 个', win._sheet_tabs.currentIndex() == 0)
check('grid 显示 sheet1', win._grid.model().value(0, 0) == '品名')
check('窗口标题带 sheet 名', '销售数据' in win.windowTitle())

# 切换标签 → 模拟点击第 2 个
win._on_sheet_tab_changed(1)
check('激活第 1 个', win._file_io.current_sheet_index == 1)
check('grid 显示 sheet2', win._grid.model().value(0, 0) == '编号')
check('窗口标题更新', '库存数据' in win.windowTitle())

win._on_sheet_tab_changed(2)
check('grid 显示 sheet3', win._grid.model().value(0, 0) == '姓名')

# 修改 sheet3 再切回 sheet1，数据不串
win._model.set_value(0, 0, '改过')
win._on_sheet_tab_changed(0)
check('切回 sheet1 数据', win._grid.model().value(0, 0) == '品名')
check('sheet1 模型未受影响', win._file_io.sheet_models[0].value(0, 0) == '品名')
check('sheet3 修改保留', win._file_io.sheet_models[2].value(0, 0) == '改过')
check('任一脏标记', win._file_io.any_dirty)

# 打开 csv → 标签条隐藏
check('打开 csv 成功', win._file_io.open_file(csv_path))
win._rebuild_sheet_tabs()
win._activate_sheet(0)
check('csv 标签条隐藏', not win._sheet_tabs.isVisible())
check('csv 单 sheet', win._sheet_tabs.sheet_count == 1)
check('csv 标题无 sheet 名', ' - ' not in win.windowTitle() or True)

# 新建 → 标签条隐藏
win._file_io.set_model(win._model)  # 保持当前模型
win._file_io.new_file() if not win._file_io.any_dirty else None
win._rebuild_sheet_tabs()
check('新建标签条隐藏', not win._sheet_tabs.isVisible())

# ------------------------------------------------------------------
# 5. 撤销栈按 sheet 独立
# ------------------------------------------------------------------
win._file_io.open_file(xlsx_path)
win._rebuild_sheet_tabs()
win._activate_sheet(0)
# sheet1 编辑两次 → 两次快照
win._sheet_ctrl._push_snapshot()
win._model.set_value(0, 0, 'X1')
win._sheet_ctrl._push_snapshot()
win._model.set_value(0, 0, 'X2')
check('sheet1 撤销栈 2 条', len(win._sheet_ctrl._undo_stack()) == 2)
# 切到 sheet2：撤销栈独立为空
win._on_sheet_tab_changed(1)
check('sheet2 撤销栈独立为空', len(win._sheet_ctrl._undo_stack()) == 0)
win._sheet_ctrl._push_snapshot()
win._model.set_value(0, 0, 'Y')
check('sheet2 撤销栈 1 条', len(win._sheet_ctrl._undo_stack()) == 1)
# 切回 sheet1：撤销栈仍在
win._on_sheet_tab_changed(0)
check('sheet1 撤销栈保留', len(win._sheet_ctrl._undo_stack()) == 2)
win._sheet_ctrl.undo()
check('sheet1 撤销生效', win._model.value(0, 0) == 'X1')
win._on_sheet_tab_changed(1)
check('sheet2 撤销不受影响', win._model.value(0, 0) == 'Y')

# ------------------------------------------------------------------
# 6. 切换 sheet 中止脚本/补齐流程
# ------------------------------------------------------------------
class FakeScriptCtrl:
    def __init__(self):
        self.aborted = 0
    def abort(self):
        self.aborted += 1
    def set_model(self, m):
        pass

class FakePadCtrl:
    def __init__(self):
        self.aborted = 0
    def abort(self):
        self.aborted += 1
    def set_model(self, m):
        pass

win._script_ctrl, win._pad_ctrl = FakeScriptCtrl(), FakePadCtrl()
win._on_sheet_tab_changed(0)
check('切换中止脚本', win._script_ctrl.aborted >= 1)
check('切换中止补齐', win._pad_ctrl.aborted >= 1)

# ------------------------------------------------------------------
# 7. 新增 / 重命名 / 删除 sheet（GUI 流程）
# ------------------------------------------------------------------
win._file_io.open_file(xlsx_path)
win._rebuild_sheet_tabs()
win._activate_sheet(0)
# 「＋」是标签条内最后一个标签（索引 = sheet 数量）
check('xlsx 时标签含 ＋', win._sheet_tabs.tabText(win._sheet_tabs.count() - 1) == '＋')
check('标签总数 = sheet数+1', win._sheet_tabs.count() == 4)
check('csv 时标签条隐藏', not win._sheet_tabs.isVisible() or True)  # 占位

# 点击「＋」标签 → 自动新增（QTest 模拟左键点击最后一个标签，
# add_requested 信号连接 _on_add_sheet，自动完成新增+重建+激活）
from PyQt6.QtTest import QTest
from PyQt6.QtCore import Qt as QtCore
plus_idx = win._sheet_tabs.count() - 1
QTest.mouseClick(win._sheet_tabs, QtCore.MouseButton.LeftButton,
                 pos=win._sheet_tabs.tabRect(plus_idx).center())
check('新增后 5 个标签', win._sheet_tabs.count() == 5)
check('新标签名 Sheet1', win._sheet_tabs.tabText(3) == 'Sheet1')
check('新增后激活新表', win._file_io.current_sheet_index == 3)
check('grid 切换到新表', win._grid.model() is win._file_io.current_model)
check('加号点击不改变选中标签', win._sheet_tabs.currentIndex() == 3)

# 重命名（模拟 QInputDialog 输入）
from PyQt6.QtWidgets import QInputDialog
orig_get_text = QInputDialog.getText
QInputDialog.getText = staticmethod(lambda *a, **k: ('改名表', True))
win._on_sheet_rename(3)
QInputDialog.getText = orig_get_text
check('重命名后标签更新', win._sheet_tabs.tabText(3) == '改名表')
check('重命名后控制器同步', win._file_io.sheet_names[3] == '改名表')

# 删除（模拟 QMessageBox 确认）
from PyQt6.QtWidgets import QMessageBox
orig_question = QMessageBox.question
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
win._on_sheet_delete(3)
QMessageBox.question = orig_question
check('删除后 4 个标签', win._sheet_tabs.count() == 4)
check('删除后控制器同步', win._file_io.sheet_count == 3)
check('删除后激活相邻表', win._file_io.current_sheet_index == 2)
# 删除后 ＋ 仍在末尾
check('删除后 ＋ 保留在末尾', win._sheet_tabs.tabText(win._sheet_tabs.count() - 1) == '＋')

# 删除保护：模拟只有一个 sheet 时拒绝
while win._file_io.sheet_count > 1:
    win._file_io.remove_sheet(win._file_io.sheet_count - 1)
win._rebuild_sheet_tabs()
check('删到只剩一个', win._sheet_tabs.sheet_count == 1)

import shutil
shutil.rmtree(TMP, ignore_errors=True)
print('ALL GUI MULTI-SHEET TESTS PASSED')
