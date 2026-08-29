"""扩展信息储存区 — 冒烟测试（动态脚本模式 P1）。

覆盖：
- 路径计算（扩展区根 = 表格库父目录/扩展信息区/表格库名）
- 读写往返（默认结构 / 保存 / 重新加载）
- 脚本列表操作（add/remove/reorder）
- 开关读写
- 对账 reconcile（xlsx 消失删扩展）
- 损坏 JSON 容错
- 非 xlsx 不建扩展（csv 无扩展）
"""
import json
import os
import sys

sys.path.insert(0, r'D:\Cloude Code\自制表格软件\代码输出库\源码')

from models.ext_store import ExtStore, reconcile

TMP = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_tmp_ext')
LIB = os.path.join(TMP, '表格文件库')
os.makedirs(os.path.join(LIB, '子夹'), exist_ok=True)


def check(name, cond):
    if not cond:
        raise AssertionError(f'FAIL: {name}')
    print('PASS:', name)


# ------------------------------------------------------------------
# 0. 路径计算
# ------------------------------------------------------------------
xlsx_path = os.path.join(LIB, '子夹', '数据.xlsx')
store = ExtStore(xlsx_path, LIB)
ext_root = ExtStore.ext_root(LIB)
check('扩展区根 = 表格库父目录/扩展信息区/表格库名',
      str(ext_root) == os.path.join(TMP, '扩展信息区', '表格文件库'))
check('扩展文件路径镜像', str(store.ext_path).endswith(
    os.path.join('扩展信息区', '表格文件库', '子夹', '数据.xlsx.json')))
check('相对路径绑定', store.rel_path == '子夹/数据.xlsx')

# ------------------------------------------------------------------
# 1. 读写往返（默认结构）
# ------------------------------------------------------------------
d = store.load()
check('默认 dynamic_mode=False', d['dynamic_mode'] is False)
check('默认 entries=[]', d['entries'] == [])
check('默认 source_path 绑定', d['source_path'] == '子夹/数据.xlsx')
check('默认 version=2', d['version'] == 2)

# ------------------------------------------------------------------
# 2. 开关 + 脚本列表操作
# ------------------------------------------------------------------
store.set_dynamic_mode(True)
check('开关写入后重读', store.get_dynamic_mode() is True)

rec = store.add_script({
    'script': '加法脚本.py',
    'params': {'direction': '以列为单位'},
    'summary': '列A+列B→列C',
    'ref_cells': [[0, 0], [1, 0]],
    'output_cells': [[0, 2], [1, 2]],
})
check('add_script 生成 id', rec.get('id'))
sid = rec['id']
store.add_script({
    'script': '自定义运算脚本.py',
    'params': {},
    'summary': '(列A×2)>5',
    'ref_cells': [[0, 0]],
    'output_cells': [[0, 3]],
})
scripts = store.get_scripts()
check('两条脚本', len(scripts) == 2)

# 重新加载（模拟重开文件）
store2 = ExtStore(xlsx_path, LIB)
check('重载后开关保留', store2.get_dynamic_mode() is True)
check('重载后列表保留', len(store2.get_scripts()) == 2)
check('重载后顺序保持', store2.get_scripts()[0]['script'] == '加法脚本.py')

# 上移：把第二条（自定义运算）上移
check('上移成功', store2.reorder_script(store2.get_scripts()[1]['id'], -1))
check('上移后顺序', store2.get_scripts()[0]['script'] == '自定义运算脚本.py')
check('下移成功', store2.reorder_script(store2.get_scripts()[0]['id'], 1))
check('下移后顺序', store2.get_scripts()[0]['script'] == '加法脚本.py')
check('越界上移失败', store2.reorder_script(store2.get_scripts()[0]['id'], -1) is False)
check('越界下移失败', store2.reorder_script(store2.get_scripts()[1]['id'], 1) is False)

# 移除
check('移除成功', store2.remove_script(store2.get_scripts()[1]['id']))
check('移除后一条', len(store2.get_scripts()) == 1)
check('移除不存在 id 返回 False', store2.remove_script('no-such-id') is False)

# 公式格
store2.set_formula_cells([{'cell': [0, 1], 'formula': 'SUM(A1:A3)',
                           'refs': [[0, 0], [1, 0], [2, 0]]}])
check('公式格写入重读', store2.get_formula_cells()[0]['formula'] == 'SUM(A1:A3)')

# ------------------------------------------------------------------
# 3. 对账
# ------------------------------------------------------------------
# 造 2 个 xlsx 假文件 + 1 个孤儿扩展
for rel in ('子夹/数据.xlsx', '根表.xlsx'):
    p = os.path.join(LIB, *rel.split('/'))
    with open(p, 'wb') as f:
        f.write(b'')
# 手动建一个孤儿扩展（无对应 xlsx）
orphan = ext_root / '孤儿.xlsx.json'
orphan.parent.mkdir(parents=True, exist_ok=True)
orphan.write_text('{}', encoding='utf-8')
# 数据.xlsx 的扩展已被上面 save 创建
n = reconcile(LIB)
check('对账删除孤儿扩展', not orphan.exists())
check('对账计数', n >= 1)
# 有源扩展保留
check('有源扩展保留', (ext_root / '子夹' / '数据.xlsx.json').exists())

# ------------------------------------------------------------------
# 3.5 set_formula_cells diff 更新（保留用户排序，2026-08-29）
# ------------------------------------------------------------------
s = ExtStore(xlsx_path, LIB)
s.set_dynamic_mode(True)
# 混合 entries：脚本A, 公式B2, 脚本B, 公式C3（用户排好的顺序）
s.set_entries([
    {'id': 'sA', 'kind': 'script', 'sheet': '表1', 'summary': '脚本A'},
    {'id': 'fB', 'kind': 'formula', 'sheet': '表1',
     'output': {'region': [1, 1, 1, 1]}, 'refs': [], 'formula': {'text': '=1'}},
    {'id': 'sB', 'kind': 'script', 'sheet': '表1', 'summary': '脚本B'},
    {'id': 'fC', 'kind': 'formula', 'sheet': '表1',
     'output': {'region': [2, 2, 2, 2]}, 'refs': [], 'formula': {'text': '=2'}},
])
# 重开同步：xlsx 仍含 B2（文本改为 =9）+ 新增 D4；C3 已消失（用户移除并保存）
s.set_formula_cells([
    {'sheet': '表1', 'cell': [1, 1], 'formula': '=9', 'refs': []},
    {'sheet': '表1', 'cell': [3, 3], 'formula': '=4', 'refs': []},
])
ents = s.get_entries()
kinds = [e['kind'] for e in ents]
check('diff 顺序保留（混合不重排）', kinds ==
      ['script', 'formula', 'script', 'formula'])
check('B2 文本更新且原位', ents[1]['formula']['text'] == '=9'
      and ents[1]['id'] == 'fB')
check('C3 消失删除', 'fC' not in [e['id'] for e in ents])
check('新 D4 追加末尾', ents[3]['formula']['text'] == '=4')

# ------------------------------------------------------------------
# 4. 损坏 JSON 容错
# ------------------------------------------------------------------
bad = ext_root / '子夹' / '数据.xlsx.json'
bad.write_text('{ 不是json', encoding='utf-8')
d3 = ExtStore(xlsx_path, LIB).load()
check('损坏 JSON 容错返回默认', d3['entries'] == [] and d3['dynamic_mode'] is False)

# ------------------------------------------------------------------
# 5. remove 删除扩展
# ------------------------------------------------------------------
ExtStore(xlsx_path, LIB).remove()
check('remove 删除扩展文件', not bad.exists())

# ------------------------------------------------------------------
# 6. 源头清理 + 条目级对账（2026-08-29：孤儿条目防残留）
# ------------------------------------------------------------------
s6 = ExtStore(xlsx_path, LIB)
s6.set_entries([
    {'id': 's1', 'kind': 'script', 'sheet': '表1', 'summary': '脚本1'},
    {'id': 'f1', 'kind': 'formula', 'sheet': '表2', 'output': {'region': [0, 0, 0, 0]},
     'refs': [], 'formula': {'text': '=1'}},
])
# remove_entries_by_sheet：删 表2 的条目
n = s6.remove_entries_by_sheet('表2')
check('源头清理按 sheet 删条目', n == 1 and
      [e['sheet'] for e in s6.get_entries()] == ['表1'])
# 条目级对账：孤儿条目（sheet 不在 xlsx）→ reconcile 删除
# 构造 xlsx（表1 sheet）+ 扩展含 表2 条目
import os
xlsx2 = os.path.join(LIB, '子夹', '数据.xlsx')
from file_io import xlsx_handler
xlsx_handler.write_all(xlsx2, [('表1', [['a']])])
st7 = ExtStore(xlsx2, LIB)
st7.set_entries([
    {'id': 'ok', 'kind': 'script', 'sheet': '表1', 'summary': '正常'},
    {'id': 'orphan', 'kind': 'script', 'sheet': '已删表', 'summary': '孤儿'},
])
n2 = reconcile(LIB)
check('条目级对账删孤儿条目',
      [e['id'] for e in ExtStore(xlsx2, LIB).get_entries()] == ['ok'])

# ------------------------------------------------------------------
# 7. 文件身份指纹（2026-08-29：同名同路径替换自动区分）
# ------------------------------------------------------------------
from models.formula_translate import workbook_fingerprint
s8 = ExtStore(xlsx2, LIB)
check('指纹默认空', s8.get_fingerprint() == '')
fp = workbook_fingerprint(xlsx2)
check('指纹计算非空', bool(fp))
s8.set_fingerprint(fp)
check('指纹写读', ExtStore(xlsx2, LIB).get_fingerprint() == fp)
# 同名同结构 → 指纹相同；sheet 变 → 不同
import os
xlsx3 = os.path.join(LIB, '子夹', '另.xlsx')
xlsx_handler.write_all(xlsx3, [('表1', [['a']])])
fp_same = workbook_fingerprint(xlsx3)
xlsx_handler.write_all(xlsx3, [('改名表', [['a']])])
fp_diff = workbook_fingerprint(xlsx3)
check('同名同结构指纹相同', fp_same == fp)
check('sheet 变指纹不同', fp_diff != fp)

# 清理
import shutil
shutil.rmtree(TMP, ignore_errors=True)
print('ALL EXT-STORE TESTS PASSED')
