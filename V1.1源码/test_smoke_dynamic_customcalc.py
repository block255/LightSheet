"""自定义运算脚本动态记录/重放 — 冒烟测试。

验证：BlockNode 对象 → block_to_dict 序列化 → 存扩展 JSON → 重放
时 block_from_dict 还原 → 自定义运算脚本 run 执行成功。
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
from custom_calc.model import (
    BlockType, BlockNode, CalcSubtype, SymKind, InputKind, OutputTarget,
    DataDef, make_calc_num, make_symbol, make_output, block_to_dict,
    block_from_dict,
)

TMP = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_tmp_cc_dyn')
shutil.rmtree(TMP, ignore_errors=True)
LIB = os.path.join(TMP, '表格文件库')
os.makedirs(LIB, exist_ok=True)


def check(name, cond):
    if not cond:
        raise AssertionError(f'FAIL: {name}')
    print('PASS:', name)


# 构造积木：列A + 列B → 输出到列C（与真实编辑器 get_blocks 相同的 BlockNode）
def make_blocks():
    a = make_calc_num()
    a.data = DataDef(kind=InputKind.COL, index=0)
    b = make_calc_num()
    b.data = DataDef(kind=InputKind.COL, index=1)
    plus = make_symbol('+', SymKind.OP)
    paren = BlockNode(type=BlockType.PAREN)
    paren.children = [a, plus, b]
    out = make_output()
    out.output_target = OutputTarget.COL
    out.output_index = 2
    out.children = [paren]
    return [out]


xlsx_path = os.path.join(LIB, 'cc.xlsx')
xlsx_handler.write_all(xlsx_path, [('表1', [['1', '2', ''], ['3', '4', '']])])
store = ExtStore(xlsx_path, LIB)
model = SpreadsheetModel()
model.load_2d([['1', '2', ''], ['3', '4', '']])
model.file_path = xlsx_path
model.file_format = 'xlsx'

dc = DynamicController(store, model, None)
dc.set_enabled(True)
dc.set_model(model, '表1')
msgs = []
dc.status_message.connect(msgs.append)

# 1. 记录自定义运算（params 里是真实 BlockNode 对象）
import inspect
from scripts import 自定义运算脚本 as cc_mod
cc_path = inspect.getfile(cc_mod)
blocks = make_blocks()
params = {'direction': '以列为单位', 'custom_blocks': blocks}
cfg, refs, outs = extract_replay_config(params)
check('cfg 里是 dict 列表', isinstance(cfg['custom_blocks'][0], dict))
check('序列化往返一致',
      block_from_dict(cfg['custom_blocks'][0]).type == BlockType.OUTPUT)
check('积木引用提取', refs == [{'col': 0}, {'col': 1}])
check('积木输出提取', outs == [{'col': 2}])

rec = dc.record('自定义运算脚本', cc_path, params, '表1')
check('记录成功（无崩溃）', rec is not None)
check('扩展 JSON 可读（BlockNode 已序列化）',
      len(store.get_scripts()) == 1)

# 2. 重放：dict → BlockNode → run
from custom_calc.engine import EvalContext, Evaluator, CalcError
from scripts.base_script import BaseScript

class FakeCCScript(BaseScript):
    name = '自定义运算脚本'
    def steps(self):
        return []
    def run(self, sheet, params):
        blocks = params['custom_blocks']
        # 与真实脚本相同的执行路径
        ctx = EvalContext(sheet, params['direction'])
        ev = Evaluator(ctx)
        for root in blocks:
            if root.type == BlockType.OUTPUT:
                val = ev.evaluate(root.children[0])
                if root.output_target == OutputTarget.COL:
                    col = root.output_index
                    for pos, v in zip(val.positions, val.values):
                        sheet.set_value(pos, col, str(int(v)))
        return None

rebuilt = build_replay_params(rec['replay_cfg'], model)
check('重放 params 是 BlockNode 列表',
      isinstance(rebuilt['custom_blocks'][0], BlockNode)
      if 'BlockNode' in dir() else True)
check('重放 custom_blocks 是对象', hasattr(rebuilt['custom_blocks'][0], 'type'))
err = FakeCCScript().run(model, rebuilt)
check('自定义运算重放成功', err is None)
check('C1=1+2=3', model.value(0, 2) == '3')
check('C2=3+4=7', model.value(1, 2) == '7')

# 3. 触发：改 A1 → 重放自定义运算
model.set_value(0, 0, '10')
msgs.clear()
dc.on_cell_edited(0, 0, '表1')
check('触发重放', any('已自动重放' in m for m in msgs))
check('重放后 C1=10+2=12', model.value(0, 2) == '12')

shutil.rmtree(TMP, ignore_errors=True)
print('ALL CUSTOM-CALC DYNAMIC TESTS PASSED')
