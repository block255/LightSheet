"""扩展区 v2 数据层测试：v1→v2 迁移 + 统一条目接口 + 旧接口兼容。"""
import os, sys, json, tempfile
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
sys.path.insert(0, r'D:\Cloude Code\自制表格软件\代码输出库\源码')

from models.ext_store import ExtStore

def check(name, cond):
    if not cond:
        raise AssertionError('FAIL: ' + name)
    print('PASS:', name)

# 用临时目录构造扩展区（不碰真实库；系统 TEMP 受沙箱限制 → 用源码目录下临时目录）
_tmp_base = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_tmp_v2test')
import shutil
shutil.rmtree(_tmp_base, ignore_errors=True)
os.makedirs(_tmp_base)
tmp = _tmp_base
lib = os.path.join(tmp, 'lib')
os.makedirs(lib)
xlsx_path = os.path.join(lib, 'test.xlsx')
open(xlsx_path, 'w').close()
ext_dir = os.path.join(tmp, '扩展信息区', 'lib')
os.makedirs(ext_dir)
ext_file = os.path.join(ext_dir, 'test.xlsx.json')

# ==== 1. v1 → v2 迁移 ====
v1 = {
    'version': 1,
    'dynamic_mode': True,
    'scripts': [
        {'id': 's1', 'script': '加法脚本.py', 'script_path': 'D:/x/加法脚本.py',
         'sheet': '表1', 'summary': '列A+列B→列C',
         'replay_cfg': {'direction': '以列为单位'},
         'ref_cells': [{'col': 0}, {'col': 1}], 'output_cells': [{'col': 2}],
         'recorded_at': '2026-08-28 20:00'},
    ],
    'formula_cells': [
        {'sheet': '表1', 'cell': [1, 1], 'formula': '=SUM(A1:A3)',
         'refs': [(0, 0, 2, 0)]},
    ],
}
with open(ext_file, 'w', encoding='utf-8') as f:
    json.dump(v1, f, ensure_ascii=False)

store = ExtStore(xlsx_path, lib)
data = store.load()
check('v1 迁移到 version 2', data.get('version') == 2)
check('v1 迁移生成 entries', len(data.get('entries', [])) == 2)
check('迁移后无 scripts/formula_cells 遗留',
      'scripts' not in data and 'formula_cells' not in data)

# 磁盘已写 v2
on_disk = json.load(open(ext_file, encoding='utf-8'))
check('迁移已写回磁盘 v2', on_disk.get('version') == 2
      and 'entries' in on_disk and 'scripts' not in on_disk)

# ==== 2. 旧接口兼容（script 形态）====
scripts = store.get_scripts()
check('get_scripts 返回 script 条目', len(scripts) == 1
      and scripts[0]['id'] == 's1' and scripts[0]['kind'] == 'script'
      and scripts[0]['ref_cells'] == [{'col': 0}, {'col': 1}])

added = store.add_script({'script': '统计脚本.py', 'script_path': 'D:/x/统计.py',
                          'sheet': '表1', 'summary': '均值', 'replay_cfg': {},
                          'ref_cells': [{'range': [0, 0, 5, 6]}],
                          'output_cells': [{'row': 6}], 'recorded_at': ''})
check('add_script 走 add_entry（带 id/kind/source）',
      added.get('id') and added['kind'] == 'script' and added['source'] == 'ours')
check('get_scripts 数量 +1', len(store.get_scripts()) == 2)

check('remove_script 生效', store.remove_script(added['id'])
      and len(store.get_scripts()) == 1)

# ==== 3. 旧接口兼容（formula 形态）====
fcs = store.get_formula_cells()
check('get_formula_cells 转回 v1 格式', len(fcs) == 1
      and fcs[0]['cell'] == [1, 1] and fcs[0]['formula'] == '=SUM(A1:A3)'
      and fcs[0]['refs'] == [(0, 0, 2, 0)])

store.set_formula_cells([
    {'sheet': '表1', 'cell': [2, 2], 'formula': '=AVERAGE(B1:B4)',
     'refs': [(0, 1, 3, 1)]},
])
fcs2 = store.get_formula_cells()
check('set_formula_cells 重建 formula 条目', len(fcs2) == 1
      and fcs2[0]['cell'] == [2, 2] and fcs2[0]['formula'] == '=AVERAGE(B1:B4)')

# ==== 4. 统一条目接口 ====
entries = store.get_entries()
check('get_entries 混合列表（script + formula）',
      len(entries) == 2 and sorted(e['kind'] for e in entries)
      == ['formula', 'script'])

e = store.add_entry({'source': 'ours', 'kind': 'script', 'sheet': '表2',
                     'summary': '测试条目', 'ref_cells': [], 'output_cells': []})
check('add_entry 通用添加', e.get('id') and e['kind'] == 'script')
check('reorder_entry 排序', store.reorder_entry(e['id'], -1))
check('remove_entry 移除', store.remove_entry(e['id'])
      and len(store.get_entries()) == 2)

# ==== 5. 空/新文件 → 默认 v2 ====
ext2 = os.path.join(tmp, '扩展信息区', 'lib', 'new.xlsx.json')
store2 = ExtStore(os.path.join(lib, 'new.xlsx'), lib)
d2 = store2.load()
check('新文件默认 v2 空结构', d2['version'] == 2 and d2['entries'] == []
      and d2['dynamic_mode'] is False)

print()
print('ALL EXT-STORE V2 TESTS PASSED')
print('ALL EXT-STORE V2 TESTS PASSED')
print('ALL EXT-STORE V2 TESTS PASSED')
# 清理临时目录
shutil.rmtree(_tmp_base, ignore_errors=True)
