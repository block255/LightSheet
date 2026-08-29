"""动态脚本模式 GUI 端到端 — 冒烟测试（P1）。

覆盖（真实 MainWindow 全链路）：
- 打开 xlsx → 动态控制器绑定、公式格扫描
- 工具栏「动态脚本」→ 面板打开、开关默认关闭
- 开启开关 → 运行加法脚本成功 → 自动记录进列表
- 修改引用格（失焦）→ 自动重放 → 输出列更新
- csv 打开 → 开关禁用、列表不显示
- 面板右键：移除/上移/下移
- 重放失败提示（数据变文字）
"""
import os
import shutil
import sys

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
sys.path.insert(0, r'D:\Cloude Code\自制表格软件\代码输出库\源码')

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt
app = QApplication([])

TMP = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_tmp_dyn_gui')
shutil.rmtree(TMP, ignore_errors=True)
LIB = os.path.join(TMP, '表格文件库')
os.makedirs(LIB, exist_ok=True)

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
# 让表格库指向临时目录
win._file_io._get_file_folder = lambda: LIB

# ------------------------------------------------------------------
# 1. 准备 xlsx + 打开
# ------------------------------------------------------------------
src = os.path.join(LIB, '动态演示.xlsx')
xlsx_handler.write_all(src, [('表1', [['1', '2', ''], ['3', '4', '']])])
check('打开 xlsx', win._file_io.open_file(src))
win._rebuild_sheet_tabs()
win._activate_sheet(0)
win._rebind_dynamic()
check('动态控制器绑定 xlsx', win._dynamic_ctrl.is_xlsx is True)
check('默认开关关闭', win._dynamic_ctrl.enabled is False)
check('扩展区已建', win._dynamic_ctrl._store.ext_path.exists())

# ------------------------------------------------------------------
# 2. 面板：打开、开关
# ------------------------------------------------------------------
from views.dynamic_panel import DynamicPanel
panel = DynamicPanel(win._dynamic_ctrl, win)
check('面板开关默认关', panel._switch.isChecked() is False)
check('面板开关可用(xlsx)', panel._switch.isEnabled() is True)
panel._switch.setChecked(True)
app.processEvents()
check('面板开启后 enabled', win._dynamic_ctrl.enabled is True)

# ------------------------------------------------------------------
# 3. 运行加法脚本（真实路径）
# ------------------------------------------------------------------
import inspect
from scripts import 加法脚本 as add_mod
add_path = inspect.getfile(add_mod)

# 直接模拟脚本运行成功 → run_succeeded 信号 → 记录
win._on_script_succeeded('加法脚本', add_path, {
    'direction': '以列为单位',
    'operands': {
        'slots': [
            {'kind': 'column', 'index': 0, 'title': None, 'title_idx': 0,
             'values': [1.0, 3.0]},
            {'kind': 'column', 'index': 1, 'title': None, 'title_idx': 0,
             'values': [2.0, 4.0]},
        ],
        'data_len': 2, 'title_idx': 0, 'has_title': False,
    },
    'output': {'target': 'column', 'index': 2},
})
check('脚本运行成功 → 记录进列表', len(win._dynamic_ctrl.scripts) == 1)
rec = win._dynamic_ctrl.scripts[0]
check('记录摘要', '列A' in rec['summary'] and '列C' in rec['summary'])

# 面板刷新后显示
panel._refresh()
check('面板列表 1 条', panel._list.count() >= 1)

# ------------------------------------------------------------------
# 4. 修改引用格 → 自动重放
# ------------------------------------------------------------------
# 修改 A1（列A 引用区）：1 → 10
win._model.set_value(0, 0, '10')
win._on_cell_committed(0, 0)   # 模拟失焦
check('重放后 C1=10+2=12', win._model.value(0, 2) == '12')
check('重放后 C2=3+4=7', win._model.value(1, 2) == '7')

# 修改 B1（列B 引用区）：2 → 20
win._model.set_value(0, 1, '20')
win._on_cell_committed(0, 1)
check('重放后 C1=10+20=30', win._model.value(0, 2) == '30')

# ------------------------------------------------------------------
# 5. 依赖链（两个脚本，顺序=依赖序）
# ------------------------------------------------------------------
# 记录脚本2：列C+常数10 → 列D（依赖脚本1的输出 C 列）
win._on_script_succeeded('加法脚本2', add_path, {
    'direction': '以列为单位',
    'operands': {
        'slots': [
            {'kind': 'column', 'index': 2, 'title': None, 'title_idx': 0,
             'values': [30.0, 7.0]},
            {'kind': 'constant', 'value': 10.0},
        ],
        'data_len': 2, 'title_idx': 0, 'has_title': False,
    },
    'output': {'target': 'column', 'index': 3},
})
check('两条脚本', len(win._dynamic_ctrl.scripts) == 2)
check('顺序：加法脚本在加法脚本2上面',
      win._dynamic_ctrl.scripts[0]['script'] == '加法脚本'
      and win._dynamic_ctrl.scripts[1]['script'] == '加法脚本2')

# 改 A1 → 脚本1重放（写C）→ 链继续 → 脚本2重放（读C写D）
win._model.set_value(0, 0, '100')
win._on_cell_committed(0, 0)
check('脚本1重放 C1=100+20=120', win._model.value(0, 2) == '120')
check('链式脚本2重放 D1=120+10=130', win._model.value(0, 3) == '130')
check('链式脚本2重放 D2=7+10=17', win._model.value(1, 3) == '17')

# ------------------------------------------------------------------
# 6. 顺序反向：把脚本2移到脚本1上面 → 改A1 → 脚本2先查(不命中A) → 脚本1重放 → 链终止（脚本2已检测过）
# ------------------------------------------------------------------
from PyQt6.QtCore import QEventLoop, QTimer
def _wait(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()

_wait(400)   # 过防抖窗口，允许同格再次触发
check('下移脚本1', win._dynamic_ctrl.reorder_script(
    win._dynamic_ctrl.scripts[0]['id'], 1))
check('顺序反了', win._dynamic_ctrl.scripts[0]['script'] == '加法脚本2')
win._model.set_value(0, 0, '200')
win._on_cell_committed(0, 0)
check('脚本2先检测不触发(未命中A)', True)   # 无异常即通过
check('脚本1重放 C1=200+20=220', win._model.value(0, 2) == '220')
# 此时 D 列没有更新（脚本2已检测过，链单向向下）——验证单向链语义
check('D列未被链式更新（顺序反）', win._model.value(0, 3) == '130')

# 恢复顺序
win._dynamic_ctrl.reorder_script(win._dynamic_ctrl.scripts[1]['id'], -1)

# ------------------------------------------------------------------
# 7. 重放失败提示
# ------------------------------------------------------------------
_wait(400)   # 过防抖窗口
win._model.set_value(0, 0, '文字')
win._on_cell_committed(0, 0)
check('失败提示(状态栏)', '重放失败' in win._status_bar._status_label.text())

# ------------------------------------------------------------------
# 8. csv：开关禁用 + 列表不显示
# ------------------------------------------------------------------
csv_path = os.path.join(LIB, '单.csv')
with open(csv_path, 'w', encoding='utf-8') as f:
    f.write('a,b\n1,2\n')
win._file_io.open_file(csv_path)
win._rebuild_sheet_tabs()
win._activate_sheet(0)
win._rebind_dynamic()
check('csv is_xlsx False', win._dynamic_ctrl.is_xlsx is False)
panel2 = DynamicPanel(win._dynamic_ctrl, win)
check('csv 开关禁用', panel2._switch.isEnabled() is False)
check('csv 面板列表不显示', panel2._list.count() == 0)

# ------------------------------------------------------------------
# 9. 面板右键：移除
# ------------------------------------------------------------------
win._file_io.open_file(src)
win._rebuild_sheet_tabs()
win._activate_sheet(0)
win._rebind_dynamic()
check('重开 xlsx 列表恢复', len(win._dynamic_ctrl.scripts) == 2)
panel3 = DynamicPanel(win._dynamic_ctrl, win)
panel3._refresh()
check('面板显示 2 条', panel3._list.count() >= 2)
# 移除第一条
sid = win._dynamic_ctrl.scripts[0]['id']
check('右键移除', win._dynamic_ctrl.remove_script(sid))
check('移除后 1 条', len(win._dynamic_ctrl.scripts) == 1)

# 持久化验证
win._file_io.open_file(src)
win._rebuild_sheet_tabs()
win._activate_sheet(0)
win._rebind_dynamic()
check('移除持久化', len(win._dynamic_ctrl.scripts) == 1)

# ------------------------------------------------------------------
# 10. 公式格条目：展开详情 + 右键移除/排序 + 写回语义
# ------------------------------------------------------------------
src2 = os.path.join(LIB, '公式演示.xlsx')
xlsx_handler.write_all(src2, [('表1', [['1', '2', ''], ['3', '4', '']])],
                       formulas={'表1': {(1, 1): '=A1+A2', (0, 0): '=B1+B2'}})
win._file_io.open_file(src2)
win._rebuild_sheet_tabs()
win._activate_sheet(0)
win._rebind_dynamic()
dc = win._dynamic_ctrl
check('公式条目扫描 2 条', len(dc._formula_entries) == 2)

panel4 = DynamicPanel(dc, win)
panel4._refresh()
check('面板列表含公式条目', panel4._list.count() >= 2)
kinds = [panel4._list.item(i).data(Qt.ItemDataRole.UserRole + 1)
         for i in range(panel4._list.count())]
check('kind=formula 标记存在', 'formula' in kinds)

# 展开详情：公式全文 / 引用 / 输出
e0 = dc._formula_entries[0]
detail = panel4._formula_detail_text(e0)
check('公式详情含全文', e0.get('formula', {}).get('text', '') in detail)
check('公式详情含引用', '引用:' in detail)
check('公式详情含输出', '输出:' in detail)

# 移除公式：条目删除 + 当前值保留
r0, c0 = e0['output']['region'][0], e0['output']['region'][1]
val_before = win._model.value(r0, c0)
check('移除公式', dc.remove_formula(e0['id']))
check('公式条目剩 1', len(dc._formula_entries) == 1)
check('移除后当前值保留', win._model.value(r0, c0) == val_before)

# 模拟保存（collect_save_formulas 写回）：被移除格不再有公式 → xlsx 重扫只剩 1
formulas = dc.collect_save_formulas()
check('被移除格不在写回公式集',
      (r0, c0) not in formulas.get('表1', {}))
xlsx_handler.write_all(src2, [('表1', win._model.to_2d())], formulas)
win._file_io.open_file(src2)
win._rebuild_sheet_tabs()
win._activate_sheet(0)
win._rebind_dynamic()
check('移除持久化（xlsx 公式消失）', len(win._dynamic_ctrl._formula_entries) == 1)

# 排序：两个公式条目上移/下移（公式块内生效）
xlsx_handler.write_all(src2, [('表1', [['1', '2', ''], ['3', '4', '']])],
                       formulas={'表1': {(1, 1): '=A1+A2', (0, 0): '=B1+B2'}})
win._file_io.open_file(src2)
win._rebuild_sheet_tabs()
win._activate_sheet(0)
win._rebind_dynamic()
dc = win._dynamic_ctrl
check('排序前 2 条', len(dc._formula_entries) == 2)
f0, f1 = dc._formula_entries[0], dc._formula_entries[1]
check('下移公式条目', dc.reorder_formula(f0['id'], 1))
check('下移后顺序交换', dc._formula_entries[0]['id'] == f1['id'])
check('上移公式条目', dc.reorder_formula(f0['id'], -1))
check('上移后顺序恢复', dc._formula_entries[0]['id'] == f0['id'])
check('越界上移失败', dc.reorder_formula(f0['id'], -1) is False)

# ------------------------------------------------------------------
# 11. 混合顺序 + 循环引用 + 迭代次数（2026-08-29）
# ------------------------------------------------------------------
from controllers.dynamic_controller import detect_cycle_entry_ids
dc = win._dynamic_ctrl
store = dc._store
# 清空 entries，交替添加 script/formula/script（验证混排保序）
store.save({'version': 2, 'source_path': store.rel_path,
            'dynamic_mode': True, 'entries': []})
s1 = store.add_entry({'kind': 'script', 'sheet': '表1', 'summary': '脚本1',
                      'script': '加法脚本', 'script_path': '',
                      'replay_cfg': {}, 'ref_cells': [], 'output_cells': []})
f1 = store.add_entry({'kind': 'formula', 'sheet': '表1',
                      'output': {'region': [0, 0, 0, 0]},
                      'refs': [{'sheet': '表1', 'range': [0, 1, 0, 1]}],
                      'formula': {'text': '=B1'}, 'summary': '[公式] =B1'})
s2 = store.add_entry({'kind': 'script', 'sheet': '表1', 'summary': '脚本2',
                      'script': '求和脚本', 'script_path': '',
                      'replay_cfg': {}, 'ref_cells': [], 'output_cells': []})
mixed = dc.mixed_entries('表1')
check('混合顺序保序', [e['kind'] for e in mixed] ==
      ['script', 'formula', 'script'])
panel5 = DynamicPanel(dc, win)
panel5._refresh()
kinds = [panel5._list.item(i).data(Qt.ItemDataRole.UserRole + 1)
         for i in range(panel5._list.count())]
check('面板混合顺序', kinds == ['script', 'formula', 'script'])

# 循环引用：A1=B1 ↔ B1=A1（f1 refs B1，再加 f2 输出 B1 refs A1）
f2 = store.add_entry({'kind': 'formula', 'sheet': '表1',
                      'output': {'region': [0, 1, 0, 1]},
                      'refs': [{'sheet': '表1', 'range': [0, 0, 0, 0]}],
                      'formula': {'text': '=A1'}, 'summary': '[公式] =A1'})
dc._sync_formula_state()
cycle = detect_cycle_entry_ids(dc._formula_entries)
check('循环检测命中', f1['id'] in cycle and f2['id'] in cycle)
panel5._refresh()
check('警告条显示', not panel5._cycle_warn.isHidden()
      and '循环引用' in panel5._cycle_warn.text())
# 移除 f2 破环 → 警告隐藏
dc.remove_formula(f2['id'])
panel5._refresh()
check('破环后警告隐藏', panel5._cycle_warn.isHidden())

# 迭代次数：默认 5 / 设置 3 / 钳制 1-100（按 xlsx 存扩展区）
check('迭代默认 5', store.get_iterations() == 5)
check('设迭代 3', dc.set_iterations(3) == 3 and store.get_iterations() == 3)
check('钳制下限 1', dc.set_iterations(0) == 1)
check('钳制上限 100', dc.set_iterations(999) == 100)
dc.set_iterations(5)

# ------------------------------------------------------------------
# 12. 面板独立撤销（会话级，与表格撤销分离；参照积木编辑器快照栈）
# ------------------------------------------------------------------
# 当前 store entries: [s1(脚本), f1(公式), s2(脚本)]（第 11 节 f2 已移除）
dc.sync_from_store()
panel6 = DynamicPanel(dc, win)
panel6._refresh()
before_kinds = [panel6._list.item(i).data(Qt.ItemDataRole.UserRole + 1)
                for i in range(panel6._list.count())]
check('撤销基线 3 条', before_kinds == ['script', 'formula', 'script'])

# 移除公式 → undo 恢复 → redo 再移除
victim = dc._formula_entries[0]['id']
panel6._push_snapshot()   # 模拟操作前快照（真实流程在菜单操作里自动 push）
dc.remove_formula(victim)
panel6._refresh()
check('移除后 2 条', panel6._list.count() == 2)
panel6._undo()
kinds_after_undo = [panel6._list.item(i).data(Qt.ItemDataRole.UserRole + 1)
                    for i in range(panel6._list.count())]
check('撤销恢复 3 条', kinds_after_undo == before_kinds)
panel6._redo()
check('重做再移除 2 条', panel6._list.count() == 2)
panel6._undo()   # 恢复为 3 条

# 排序 undo（上移脚本2 → undo 恢复）
panel6._push_snapshot()
dc.reorder_script(s2['id'], -1)
panel6._refresh()
check('排序后公式在第2位', [panel6._list.item(i).data(Qt.ItemDataRole.UserRole + 1)
      for i in range(panel6._list.count())] == ['script', 'script', 'formula'])
panel6._undo()
check('排序撤销恢复', [panel6._list.item(i).data(Qt.ItemDataRole.UserRole + 1)
      for i in range(panel6._list.count())] == before_kinds)

# 迭代变更 undo
panel6._push_snapshot()
dc.set_iterations(7)
check('迭代设 7', dc.iterations == 7)
panel6._undo()
check('迭代撤销回 5', dc.iterations == 5)

# 无可撤销提示（不崩溃）
panel6._undo_stack.clear()
panel6._undo()
check('无可撤销不崩溃', True)

shutil.rmtree(TMP, ignore_errors=True)
print('ALL DYNAMIC GUI TESTS PASSED')
