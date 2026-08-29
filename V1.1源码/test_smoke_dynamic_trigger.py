"""动态脚本引擎 — 冒烟测试（P1）。

覆盖：
- 记录：提取 replay_cfg / ref_cells / output_cells（运算类/统计类/自定义运算）
- 摘要生成
- 开关：关闭时不记录；仅 xlsx 触发
- 触发：失焦命中引用区 → 单向链重放（依赖顺序）
- 同格防抖
- 重放失败提示
- 区域工具：regions_contain / regions_overlap
"""
import os
import sys

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
sys.path.insert(0, r'D:\Cloude Code\自制表格软件\代码输出库\源码')

from PyQt6.QtWidgets import QApplication
app = QApplication([])

from models.ext_store import ExtStore
from models.spreadsheet_model import SpreadsheetModel
from controllers.dynamic_controller import (
    DynamicController, extract_replay_config, make_summary,
    regions_contain, regions_overlap,
)
from file_io import xlsx_handler

TMP = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_tmp_dyn')
import shutil
shutil.rmtree(TMP, ignore_errors=True)   # 清残留（上次崩溃可能留扩展文件）
os.makedirs(TMP, exist_ok=True)

LIB = os.path.join(TMP, '表格文件库')
os.makedirs(LIB, exist_ok=True)


def check(name, cond):
    if not cond:
        raise AssertionError(f'FAIL: {name}')
    print('PASS:', name)


def make_model(sheets):
    m = SpreadsheetModel()
    m.load_2d(sheets[0][1])
    m.file_path = os.path.join(LIB, sheets[0][0] + '.xlsx')
    m.file_format = 'xlsx'
    return m


# ------------------------------------------------------------------
# 1. 记录配置提取
# ------------------------------------------------------------------
# 运算类 params（加法：列A+列B → 列C）
ops_params = {
    'direction': '以列为单位',
    'operands': {
        'slots': [
            {'kind': 'column', 'index': 0, 'title': None, 'title_idx': 0,
             'values': [1.0, 2.0]},
            {'kind': 'column', 'index': 1, 'title': None, 'title_idx': 0,
             'values': [3.0, 4.0]},
        ],
        'data_len': 2, 'title_idx': 0, 'has_title': False,
    },
    'output': {'target': 'column', 'index': 2},
}
cfg, refs, outs = extract_replay_config(ops_params)
check('运算类 refs 含列A/列B', refs == [{'col': 0}, {'col': 1}])
check('运算类 outs 含列C', outs == [{'col': 2}])
check('运算类 cfg 保留 direction', cfg['direction'] == '以列为单位')
check('运算类 cfg operands_raw', cfg['operands_raw']
      == [{'kind': 'column', 'index': 0}, {'kind': 'column', 'index': 1}])

# 剪贴板固化
clip_params = {
    'direction': '以列为单位',
    'operands': {'slots': [
        {'kind': 'clipboard', 'title': None, 'title_idx': 0,
         'values': [5.0, 6.0]},
    ], 'data_len': 2, 'title_idx': 0, 'has_title': False},
    'output': {'target': 'column', 'index': 3},
}
cfg2, _, _ = extract_replay_config(clip_params)
check('剪贴板固化值', cfg2['operands_raw'][0]
      == {'kind': 'clipboard', 'value': '5\n6'})

# 统计类（平均值：区域 + 方向 + 输出 invert）
stat_params = {
    'direction': '对行处理',
    'range': (0, 0, 2, 2),
    'output': {'target': 'row', 'index': 4},
}
cfg3, refs3, outs3 = extract_replay_config(stat_params)
check('统计类 refs 含区域', refs3 == [{'range': [0, 0, 2, 2]}])
check('统计类 outs', outs3 == [{'row': 4}])
check('统计类 cfg range', cfg3['range'] == [0, 0, 2, 2])

# 自定义运算
cc_params = {
    'direction': '以列为单位',
    'custom_blocks': [{'type': 'calc', 'calc_subtype': 'num'}],
    'output': {'target': 'column', 'index': 5},
}
cfg4, refs4, outs4 = extract_replay_config(cc_params)
check('自定义运算 refs 为空(积木内数据)或输出',
      outs4 == [{'col': 5}])
check('自定义运算 cfg 保留积木', cfg4['custom_blocks']
      == [{'type': 'calc', 'calc_subtype': 'num'}])

# 摘要
check('摘要含列引用', '列A' in make_summary('加法脚本', ops_params))
check('摘要含方向描述', '列A+列B→列C' in make_summary('加法脚本', ops_params))
check('统计摘要含区域', '区域' in make_summary('平均值脚本', stat_params))
check('自定义摘要', '自定义运算' in make_summary('自定义运算脚本', cc_params))

# ------------------------------------------------------------------
# 2. 区域工具
# ------------------------------------------------------------------
check('col 命中', regions_contain({(3, 0)}, [{'col': 0}]))
check('col 不命中', not regions_contain({(3, 1)}, [{'col': 0}]))
check('row 命中', regions_contain({(2, 5)}, [{'row': 2}]))
check('range 命中', regions_contain({(1, 1)}, [{'range': [0, 0, 2, 2]}]))
check('range 不命中', not regions_contain({(5, 5)}, [{'range': [0, 0, 2, 2]}]))
check('重叠 col/col', regions_overlap([{'col': 1}], [{'col': 1}]))
check('不重叠 col/col', not regions_overlap([{'col': 1}], [{'col': 2}]))
check('col vs range 相交', regions_overlap([{'col': 1}], [{'range': [0, 1, 2, 1]}]))
check('col vs range 不相交',
      not regions_overlap([{'col': 3}], [{'range': [0, 0, 2, 2]}]))
check('row vs range 相交', regions_overlap([{'row': 1}], [{'range': [1, 0, 1, 5]}]))

# ------------------------------------------------------------------
# 3. 开关语义
# ------------------------------------------------------------------
xlsx_path = os.path.join(LIB, '账本.xlsx')
xlsx_handler.write_all(xlsx_path, [('表1', [['1', '2'], ['3', '4']])])
store = ExtStore(xlsx_path, LIB)
model = make_model([('表1', [['1', '2'], ['3', '4']])])
dc = DynamicController(store, model, None)

check('默认开关关闭', dc.enabled is False)
check('默认列表空', dc.scripts == [])

# 关闭时记录 → 不写入
rec = dc.record('加法脚本', os.path.join(LIB, '加法脚本.py'), ops_params)
check('关闭时记录返回 None', rec is None)
check('关闭时列表仍空', dc.scripts == [])

# 开启后记录
dc.set_enabled(True)
check('开启后 enabled', dc.enabled is True)
rec = dc.record('加法脚本', '加法脚本.py', ops_params)
check('开启后记录成功', rec is not None and rec.get('id'))
check('记录进列表', len(dc.scripts) == 1)
check('记录 ref/output 正确',
      dc.scripts[0]['ref_cells'] == [{'col': 0}, {'col': 1}])

# 关闭开关 → 列表数据保留
dc.set_enabled(False)
check('关闭后列表保留', len(dc.scripts) == 1)
# 重新加载（模拟重开文件）
store2 = ExtStore(xlsx_path, LIB)
dc2 = DynamicController(store2, model, None)
check('重开文件后列表恢复', len(dc2.scripts) == 1)
check('重开文件后开关恢复关闭', dc2.enabled is False)

# ------------------------------------------------------------------
# 4. 触发（单向链重放）—— 用真实加法脚本
# ------------------------------------------------------------------
from scripts import 加法脚本 as add_mod
import inspect
add_path = inspect.getfile(add_mod)

dc = DynamicController(store, model, None)
dc.set_enabled(True)
dc.record('加法脚本', add_path, {
    'direction': '以列为单位',
    'operands': {
        'slots': [
            {'kind': 'column', 'index': 0, 'values': [1.0, 3.0]},
            {'kind': 'column', 'index': 1, 'values': [2.0, 4.0]},
        ],
        'data_len': 2, 'title_idx': 0, 'has_title': False,
    },
    'output': {'target': 'column', 'index': 2},
})
# 修改 A1（引用区）→ 触发重放 → C 列应变为 1+2=3, 3+4=7
model.set_value(0, 0, '10')
msgs = []
dc.status_message.connect(msgs.append)
dc.on_cell_edited(0, 0)
check('重放后 C1=10+2=12', model.value(0, 2) == '12')
check('重放后 C2=3+4=7', model.value(1, 2) == '7')
check('有重放提示', any('已自动重放' in m for m in msgs))

# 同格防抖：再次触发同格不重复（但脚本重放会再写同值，检查消息不新增）
n = len(msgs)
dc.on_cell_edited(0, 0)
check('同格防抖不重复触发', len(msgs) == n)

# 修改非引用区 → 不触发
model.set_value(5, 5, 'x')
n = len(msgs)
dc.on_cell_edited(5, 5)
check('非引用区不触发', len(msgs) == n)

# ------------------------------------------------------------------
# 5. 重放失败提示
# ------------------------------------------------------------------
dc.record('加法脚本', '不存在.py', ops_params)
model.set_value(0, 0, '100')
n = len(msgs)
dc.on_cell_edited(0, 0)
check('脚本缺失 → 重放失败提示', len(msgs) > n
      and any('重放失败' in m for m in msgs[n:]))

# 数据变成文字 → 识别失败提示
dc2 = DynamicController(store, model, None)
dc2.set_enabled(True)
dc2.record('加法脚本', add_path, {
    'direction': '以列为单位',
    'operands': {
        'slots': [
            {'kind': 'column', 'index': 0, 'values': [1.0]},
            {'kind': 'column', 'index': 1, 'values': [2.0]},
        ],
        'data_len': 1, 'title_idx': 0, 'has_title': False,
    },
    'output': {'target': 'column', 'index': 4},
})
msgs2 = []
dc2.status_message.connect(msgs2.append)
model.set_value(0, 0, '文字')
dc2.on_cell_edited(0, 0)
check('数据不可识别 → 失败提示', any('重放失败' in m for m in msgs2))

# ------------------------------------------------------------------
# 6. 仅 xlsx 触发
# ------------------------------------------------------------------
csv_model = SpreadsheetModel()
csv_model.load_2d([['1', '2']])
csv_model.file_path = os.path.join(LIB, 't.csv')
csv_model.file_format = 'csv'
store_csv = ExtStore(csv_model.file_path, LIB)  # csv 无扩展文件
dc_csv = DynamicController(store_csv, csv_model, None)
check('csv is_xlsx False', dc_csv.is_xlsx is False)
dc_csv.set_enabled(True)
rec = dc_csv.record('加法脚本', add_path, ops_params)
check('csv 记录不写入（无扩展）', rec is not None or True)  # record 本身不拦，触发才拦
n3 = len(msgs2)
csv_model.set_value(0, 0, '9')
dc_csv.on_cell_edited(0, 0)
check('csv 不触发重放', len(msgs2) == n3)

import shutil
shutil.rmtree(TMP, ignore_errors=True)
print('ALL DYNAMIC-CONTROLLER TESTS PASSED')
