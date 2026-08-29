"""排序脚本动态重放 — 冒烟测试（P1 补丁验证）。

用户场景：运行数值排序（框选区域+参考列）→ 记录 → 修改参考列数据
→ 自动重放排序。
覆盖：
- extract_replay_config 提取排序脚本（range/unit/order/ref）
- 排序输出区 = range（原地重排）
- build_replay_params 重放时重新计算 _valid_indices
- 真实排序脚本重放：改参考列值后整区域重新排序
- attrib 隐藏改为 ctypes（无 subprocess 调用）
"""
import os
import shutil
import sys

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
sys.path.insert(0, r'D:\Cloude Code\自制表格软件\代码输出库\源码')

from PyQt6.QtWidgets import QApplication
app = QApplication([])

from models.ext_store import ExtStore
from models.spreadsheet_model import SpreadsheetModel
from controllers.dynamic_controller import (
    DynamicController, extract_replay_config, build_replay_params,
)
from file_io import xlsx_handler

TMP = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_tmp_sort_dyn')
shutil.rmtree(TMP, ignore_errors=True)
LIB = os.path.join(TMP, '表格文件库')
os.makedirs(LIB, exist_ok=True)


def check(name, cond):
    if not cond:
        raise AssertionError(f'FAIL: {name}')
    print('PASS:', name)


# ------------------------------------------------------------------
# 1. 提取排序配置
# ------------------------------------------------------------------
sort_params = {
    'range': (0, 0, 4, 1),      # A1:B5
    'unit': '以行为单位',
    'order': '升序排列',
    'ref': 0,                    # 参考列 A
    '_valid_indices': [0, 1, 2, 3, 4],
}
cfg, refs, outs = extract_replay_config(sort_params)
check('排序 cfg 含 order', cfg.get('order') == '升序排列')
check('排序 cfg 含 ref', cfg.get('ref') == 0)
check('排序 cfg 含 range', cfg.get('range') == [0, 0, 4, 1])
check('排序 refs 含 range', refs == [{'range': [0, 0, 4, 1]}])
check('排序 outs = range（原地）', outs == [{'range': [0, 0, 4, 1]}])

# ------------------------------------------------------------------
# 2. 重放：真实排序脚本
# ------------------------------------------------------------------
import importlib.util
sort_path = r'D:\表格软件\自用表格\脚本库\排序脚本\数值排序.py'
if not os.path.isfile(sort_path):
    print('SKIP: 脚本库数值排序.py 不存在')
    sys.exit(0)

xlsx_path = os.path.join(LIB, '排序.xlsx')
xlsx_handler.write_all(xlsx_path, [('表1', [])])
model = SpreadsheetModel()
# 5 行数据：A=参考列(无序)，B=附带列
model.load_2d([
    ['5', 'e'],
    ['2', 'b'],
    ['4', 'd'],
    ['1', 'a'],
    ['3', 'c'],
])
model.file_path = xlsx_path
model.file_format = 'xlsx'

store = ExtStore(xlsx_path, LIB)
dc = DynamicController(store, model, None)
dc.set_enabled(True)
msgs = []
dc.status_message.connect(msgs.append)

rec = dc.record('数值排序', sort_path, sort_params)
check('排序脚本记录成功', rec is not None)
check('记录 cfg 含 order', rec['replay_cfg']['order'] == '升序排列')

# 重放验证：build_replay_params 重算 valid_indices + 直接跑脚本
params = build_replay_params(rec['replay_cfg'], model)
check('重放 params 含 order', params.get('order') == '升序排列')
check('重放 params 重算 valid_indices', params.get('_valid_indices') == [0, 1, 2, 3, 4])

from controllers.dynamic_controller import load_script_instance
script = load_script_instance(sort_path)
err = script.run(model, params)
check('重放排序成功', err is None)
check('排序后 A 列升序', [model.value(r, 0) for r in range(5)]
      == ['1', '2', '3', '4', '5'])
check('排序后 B 列跟随', [model.value(r, 1) for r in range(5)]
      == ['a', 'b', 'c', 'd', 'e'])

# ------------------------------------------------------------------
# 3. 修改参考列 → 触发重放
# ------------------------------------------------------------------
# 打乱数据（模拟用户改参考列 A2）
model.load_2d([
    ['5', 'e'],
    ['9', 'x'],     # 改 A2=9（参考列变化）
    ['4', 'd'],
    ['1', 'a'],
    ['3', 'c'],
])
# load_2d 会清 file_path/format（真实场景只 set_value，这里补回）
model.file_path = xlsx_path
model.file_format = 'xlsx'
model.set_value(1, 0, '9')
msgs.clear()
dc.on_cell_edited(1, 0)   # 改参考列格
check('触发重放', any('已自动重放' in m for m in msgs))
check('重放后 A 升序', [model.value(r, 0) for r in range(5)]
      == ['1', '3', '4', '5', '9'])
check('重放后 B 跟随', [model.value(r, 1) for r in range(5)]
      == ['a', 'c', 'd', 'e', 'x'])

# 改 range 外 → 不触发
msgs.clear()
model.set_value(8, 8, 'z')
dc.on_cell_edited(8, 8)
check('range 外不触发', not any('已自动重放' in m for m in msgs))

# ------------------------------------------------------------------
# 4. 参考列数据全文字 → 重放失败（valid_indices 重算失败）
# ------------------------------------------------------------------
model.set_value(0, 0, '文字')
model.set_value(1, 0, '文字')
model.set_value(2, 0, '文字')
model.set_value(3, 0, '文字')
model.set_value(4, 0, '文字')
msgs.clear()
dc.on_cell_edited(0, 0)
check('参考列全文字 → 失败提示', any('重放失败' in m for m in msgs))

# ------------------------------------------------------------------
# 5. attrib 子进程已移除（ctypes 替代）
# ------------------------------------------------------------------
import inspect
from models import ext_store as es
src = inspect.getsource(es)
check('无 subprocess 调用', 'subprocess' not in src)
check('用 ctypes SetFileAttributesW', 'SetFileAttributesW' in src)

shutil.rmtree(TMP, ignore_errors=True)
print('ALL SORT-DYNAMIC TESTS PASSED')
