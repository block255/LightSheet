"""文件树自定义排序 — 冒烟测试（上移/下移/置顶/置底/恢复默认/持久化）。"""
import os
import sys

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
sys.path.insert(0, r'D:\Cloude Code\自制表格软件\代码输出库\源码')

from PyQt6.QtWidgets import QApplication
app = QApplication([])

from views.side_panel import SidePanel

# 工作区内临时目录（系统 %TEMP% 受沙箱限制）
TMP = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_tmp_order')
os.makedirs(TMP, exist_ok=True)
for n in ('a.csv', 'b.csv', 'c.csv'):
    with open(os.path.join(TMP, n), 'w') as f:
        f.write('x')


def check(name, cond):
    if not cond:
        raise AssertionError(f'FAIL: {name}')
    print('PASS:', name)


sp = SidePanel()
loaded = []
sp._file_source.directoryLoaded.connect(loaded.append)
sp._file_source.setRootPath(TMP)
for _ in range(200):
    app.processEvents()
    if loaded:
        break

# 先恢复默认（可能残留上次配置）
sp._apply_order('files', TMP, 'a.csv', 'reset')
names0 = sp._displayed_names('files', TMP)
check('默认自然排序', names0 == ['a.csv', 'b.csv', 'c.csv'])

sp._apply_order('files', TMP, 'c.csv', 'top')
check('置顶', sp._displayed_names('files', TMP) == ['c.csv', 'a.csv', 'b.csv'])
sp._apply_order('files', TMP, 'c.csv', 'down')
check('下移', sp._displayed_names('files', TMP) == ['a.csv', 'c.csv', 'b.csv'])
sp._apply_order('files', TMP, 'b.csv', 'up')
check('上移', sp._displayed_names('files', TMP) == ['a.csv', 'b.csv', 'c.csv'])
sp._apply_order('files', TMP, 'a.csv', 'bottom')
check('置底', sp._displayed_names('files', TMP) == ['b.csv', 'c.csv', 'a.csv'])
# 清掉 B1 实例的配置（避免污染后续注入流程）
sp._apply_order('files', TMP, 'a.csv', 'reset')
sp._settings.save()

# 持久化：重新实例化 SidePanel 读配置（模拟 main.py 注入同一 settings 实例）
from config.settings import AppSettings
settingsA = AppSettings()
settingsA.load()
sp1 = SidePanel()
sp1._settings = settingsA   # main_window 现在注入同一实例
loaded1 = []
sp1._file_source.directoryLoaded.connect(loaded1.append)
sp1._file_source.setRootPath(TMP)
for _ in range(200):
    app.processEvents()
    if loaded1:
        break
sp1._apply_order('files', TMP, 'c.csv', 'top')
check('排序操作写入注入实例', settingsA.get('file_tree_order') is not None)
settingsA.save()   # 模拟 main_window 退出保存（同实例，不覆盖）

key = TMP.replace('\\', '/')
sp2 = SidePanel()
check('配置已持久化', sp2._tree_order.get('files', {}).get(key)
      == ['c.csv', 'a.csv', 'b.csv'])
loaded2 = []
sp2._file_source.directoryLoaded.connect(loaded2.append)
sp2._file_source.setRootPath(TMP)
for _ in range(200):
    app.processEvents()
    if loaded2:
        break
check('重启后顺序保持', sp2._displayed_names('files', TMP)
      == ['c.csv', 'a.csv', 'b.csv'])

# 恢复默认并清理配置
sp2._apply_order('files', TMP, 'c.csv', 'reset')
check('恢复默认', sp2._displayed_names('files', TMP)
      == ['a.csv', 'b.csv', 'c.csv'])
sp2._apply_order('files', TMP, 'c.csv', 'reset')   # 确保配置清空

import shutil
shutil.rmtree(TMP, ignore_errors=True)

# ------------------------------------------------------------------
# 打包预置相对 key 兼容（2026-08-23：打包版 config 用相对 exe 目录 key，
# 因为最终解压位置未知；_order_for 绝对路径查不到时退回相对 key）
# ------------------------------------------------------------------
from views.side_panel import _lookup_order

check('绝对路径命中', _lookup_order({'D:/a/b': ['x']}, 'D:/a/b', 'D:/') == ['x'])
check('相对key命中', _lookup_order({'脚本库/排序脚本': ['b.py', 'a.py']},
      r'D:/place/app/脚本库/排序脚本', r'D:/place/app') == ['b.py', 'a.py'])
check('未命中None', _lookup_order({}, r'D:/a/b', r'D:/') is None)
check('不同盘符None', _lookup_order({'x': ['y']}, r'C:/a', r'D:/') is None)

# 端到端：SidePanel scripts 树 + 相对 key 预置（模拟打包版首次运行）。
# 预置顺序故意反转自然序（自然序：日期→数值），只有 fallback 生效时
# 才会得到 [数值, 日期]，从而验证相对 key 匹配确实工作。
script_root = os.path.join(os.path.dirname(os.path.abspath(__file__)), '脚本库')
os.makedirs(os.path.join(script_root, '排序脚本'), exist_ok=True)
for fn in ('数值排序.py', '日期排序.py'):
    open(os.path.join(script_root, '排序脚本', fn), 'w').close()

orig_order = sp2._settings.get('file_tree_order')
try:
    sp3 = SidePanel()
    sp3._tree_order = {'scripts': {
        '脚本库/排序脚本': ['数值排序.py', '日期排序.py'],
    }}
    sp3._script_proxy.set_user_order(sp3._tree_order['scripts'])
    # QFileSystemModel 惰性加载：root 直接设到子目录才加载其内容
    loaded3 = []
    sp3._script_source.directoryLoaded.connect(loaded3.append)
    sp3._script_source.setRootPath(os.path.join(script_root, '排序脚本'))
    got = []
    for _ in range(400):
        app.processEvents()
        got = sp3._displayed_names('scripts', os.path.join(script_root, '排序脚本'))
        if got:
            break
    check('打包预置相对key排序生效',
          got == ['数值排序.py', '日期排序.py'])
finally:
    sp2._settings.set('file_tree_order', orig_order)
    sp2._settings.save()
    shutil.rmtree(script_root, ignore_errors=True)

print('ALL FILE ORDER SMOKE TESTS PASSED')
