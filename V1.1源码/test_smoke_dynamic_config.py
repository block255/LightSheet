"""动态脚本配置提取完备性 — 冒烟测试。

对每种脚本类型的典型 params，验证：
1. extract_replay_config 提取的 cfg 覆盖 run 所需全部键
2. build_replay_params 重建后 run 读取的键齐全（无 KeyError）
3. 摘要含关键配置信息
"""
import os
import shutil
import sys

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
sys.path.insert(0, r'D:\Cloude Code\自制表格软件\代码输出库\源码')

from PyQt6.QtWidgets import QApplication
app = QApplication([])

from controllers.dynamic_controller import (
    extract_replay_config, build_replay_params, make_summary,
)
from models.spreadsheet_model import SpreadsheetModel

TMP = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_tmp_complete')
shutil.rmtree(TMP, ignore_errors=True)
os.makedirs(TMP, exist_ok=True)


def check(name, cond):
    if not cond:
        raise AssertionError(f'FAIL: {name}')
    print('PASS:', name)


model = SpreadsheetModel()
model.load_2d([
    ['组别', '一', '二', '三', '四', '五', '六', '平均'],
    ['数据1', '3.5', '2.7', '3.6', '3.5', '3.4', '2.9', '3.267'],
    ['数据2', '4.5', '4.6', '2.8', '2.9', '5.0', '5.1', '4.15'],
    ['数据3', '1.3', '1.2', '1.6', '1.6', '1.8', '2.0', '1.583'],
])


def roundtrip(name, params, required_keys):
    """提取 → 重建 → 断言 run 所需键齐全。"""
    cfg, refs, outs = extract_replay_config(params)
    rebuilt = build_replay_params(cfg, model)
    if rebuilt is None or isinstance(rebuilt, str):
        check(f'{name} 重建失败: {rebuilt}', False)
        return None
    missing = [k for k in required_keys if k not in rebuilt]
    check(f'{name} 键齐全（缺 {missing}）', not missing)
    return cfg


# 1. 排序
roundtrip('数值排序', {
    'range': (0, 0, 3, 7), 'unit': '以行为单位', 'order': '升序排列',
    'ref': 1, '_valid_indices': [1, 2, 3],
}, ['range', 'unit', 'order', 'ref', '_valid_indices'])
check('排序摘要含参考列', '参考列' in make_summary('数值排序', {
    'range': (0, 0, 3, 7), 'unit': '以行为单位', 'order': '升序排列', 'ref': 1}))

# 2. 众数
roundtrip('众数', {
    'range': (0, 0, 3, 7), 'direction': '对列处理',
    'mode': '默认', 'output': {'target': 'row', 'index': 9},
}, ['range', 'direction', 'mode', 'output'])

# 3. 分位数
roundtrip('分位数', {
    'range': (0, 0, 3, 7), 'direction': '对列处理',
    'quantile': 0.5, 'output': {'target': 'row', 'index': 9},
}, ['range', 'direction', 'quantile', 'output'])

# 4. 计数
roundtrip('计数', {
    'range': (0, 0, 3, 7), 'direction': '对列处理',
    'operator': '>', 'constant': '3',
    'output': {'target': 'row', 'index': 9},
}, ['range', 'direction', 'operator', 'constant', 'output'])

# 5. 检定
roundtrip('检定', {
    'range': (0, 0, 3, 7), 'direction': '对列处理',
    'operator': '>', 'constant': '3', 'inspect_type': '任意判定',
    'type_value': None, 'fail_result': '0', 'pass_result': '1',
    'output': {'target': 'row', 'index': 9},
}, ['range', 'direction', 'operator', 'constant', 'inspect_type',
    'type_value', 'fail_result', 'pass_result', 'output'])

# 6. 查找（数据型）
roundtrip('查找-数据', {
    'range': (0, 0, 3, 7), 'unit': '以行为单位',
    'lookup_type': '按数据查找', 'ref': 2, 'operator': '>', 'constant': '3',
    'find_output': 'row', '_valid_indices': [1, 2, 3],
}, ['range', 'unit', 'lookup_type', 'ref', 'operator', 'constant',
    'find_output', '_valid_indices'])

# 7. 查找（文本型）
roundtrip('查找-文本', {
    'range': (0, 0, 3, 7), 'unit': '以行为单位',
    'lookup_type': '按文本查找', 'ref': 1, 'text': '数据',
    'ignore_head': '忽略首格', 'find_output': 'hint',
}, ['range', 'unit', 'lookup_type', 'ref', 'text', 'ignore_head',
    'find_output'])

# 8. 加法
roundtrip('加法', {
    'direction': '以列为单位',
    'operands': {'slots': [
        {'kind': 'column', 'index': 1, 'values': [3.5, 4.5]},
        {'kind': 'constant', 'value': 1.0},
    ]},
    'output': {'target': 'column', 'index': 9},
}, ['direction', 'operands', 'output'])

# 9. 三角
roundtrip('三角', {
    'direction': '以列为单位', 'function': 'sin',
    'operands': {'slots': [
        {'kind': 'column', 'index': 1, 'values': [1.0, 2.0]}]},
    'unit': '弧度', 'output': {'target': 'column', 'index': 9},
}, ['direction', 'function', 'operands', 'unit', 'output'])

# 10. 字符串加法（文本计算元：列 + 手动文本）
roundtrip('字符串加法', {
    'direction': '以列为单位', 'range': (0, 0, 3, 1),
    'operands': {'slots': [
        {'kind': 'column', 'index': 0, 'values': ['甲', '乙']},
        {'kind': 'text', 'value': '后缀'}]},
    'output': {'target': 'column', 'index': 9},
}, ['direction', 'operands', 'output'])

# 11. 自定义运算
roundtrip('自定义运算', {
    'direction': '以列为单位',
    'custom_blocks': [{'type': 'output', 'output_target': 'col',
                       'output_index': 9}],
}, ['direction', 'custom_blocks'])

shutil.rmtree(TMP, ignore_errors=True)
print('ALL CONFIG-COMPLETENESS TESTS PASSED')
