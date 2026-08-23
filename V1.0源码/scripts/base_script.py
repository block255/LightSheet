"""脚本框架 — Step 步骤类和 BaseScript 基类。"""
from dataclasses import dataclass, field
from typing import Callable


# ══════════════════════════════════════════════════════════════════════
# 步骤类型
# ══════════════════════════════════════════════════════════════════════

@dataclass
class SelectRangeStep:
    """等待用户框选矩形区域。

    属性:
        prompt:     状态栏提示文字，如 "请框选排序区域"
        key:        结果存入 params 的键名，如 'range'
        is_rect:    校验函数，自定义附加校验，返回 None=通过 / str=错误信息
    """
    prompt: str
    key: str = 'range'
    is_rect: Callable[[int, int, int, int], str | None] | None = None


@dataclass
class ChooseOptionStep:
    """状态栏显示互斥按钮组，全部选定后方可点确定。

    属性:
        prompt:     状态栏提示文字
        groups:     按钮组，如 {'unit': ['按行', '按列'], 'order': ['升序', '降序']}
        labels:     按钮组标签，如 {'unit': '单位:', 'order': '顺序:'}
    """
    prompt: str
    groups: dict[str, list[str]]
    labels: dict[str, str] = field(default_factory=dict)


@dataclass
class ChooseQuantileStep:
    """互斥按钮组 + 分位数输入框，全部就绪后确定按钮才亮。

    面板从上到下：互斥按钮组（对行/对列）→ 分位数输入框
    （箭头菜单：「中位数」/「手动输入分位数(小数)」，默认中位数）→ 确定。
    确定按钮可用条件：方向已选 且 分位数已确认（默认中位数恒满足）。

    属性:
        prompt:         面板提示文字
        direction_key:  方向结果存入 params 的键名，如 'direction'
        direction_options: 方向按钮选项，如 ['对行处理', '对列处理']
        quantile_key:   分位数结果存入 params 的键名，如 'quantile'
    """
    prompt: str
    direction_options: list[str]
    direction_key: str = 'direction'
    quantile_key: str = 'quantile'


@dataclass
class ChooseModeStep:
    """互斥按钮组 + 模式选择框，全部就绪后确定按钮才亮。

    面板从上到下：互斥按钮组（对行/对列）→ 模式选择框
    （箭头菜单：「默认」/「精确」，默认「默认」）→ 确定。
    确定按钮可用条件：方向已选 且 模式已选（默认「默认」恒满足）。

    属性:
        prompt:         面板提示文字
        direction_key:  方向结果存入 params 的键名，如 'direction'
        direction_options: 方向按钮选项，如 ['对行处理', '对列处理']
        mode_key:       模式结果存入 params 的键名，如 'mode'
        mode_options:   模式选项，如 ['默认', '精确']，默认第一个
    """
    prompt: str
    direction_options: list[str]
    direction_key: str = 'direction'
    mode_key: str = 'mode'
    mode_options: list[str] = field(default_factory=lambda: ['默认', '精确'])


@dataclass
class ChooseCountStep:
    """互斥按钮组 + 计数条件（符号下拉 + 常数输入框），全部就绪后确定才亮。

    面板从上到下：互斥按钮组（对行/对列）→ 计数条件
    （符号下拉框 + 常数输入框）→ 确定。
    确定按钮可用条件：方向已选 且 常数已输入且为有效实数。

    属性:
        prompt:             面板提示文字
        direction_key:      方向结果存入 params 的键名，如 'direction'
        direction_options:  方向按钮选项，如 ['对行处理', '对列处理']
        operator_key:       符号结果存入 params 的键名，如 'operator'
        operator_options:   符号下拉选项，默认 ['=', '>', '<', '>=', '<=', '≠', '≡']
        constant_key:       常数结果存入 params 的键名，如 'constant'
    """
    prompt: str
    direction_options: list[str]
    direction_key: str = 'direction'
    operator_key: str = 'operator'
    operator_options: list[str] = field(default_factory=lambda: ['=', '>', '<', '>=', '<=', '≠', '≡'])
    constant_key: str = 'constant'


@dataclass
class ChooseInspectStep:
    """互斥按钮组 + 检定条件 + 检定类型 + 输出结果，全部就绪后确定才亮。

    面板从上到下：互斥按钮组（对行/对列）→ 检定条件
    （数据 + 符号按钮 + 常数输入框）→ 检定类型（选择/输入框）→
    输出结果（不通过框 + 通过框）→ 确定。
    确定按钮可用条件：方向已选 且 常数已确认 且 检定类型就绪
    （数量/比例自定义时对应数值已输入且有效）且 输出结果两框已确认。

    属性:
        prompt:             面板提示文字
        direction_key:      方向结果存入 params 的键名，如 'direction'
        direction_options:  方向按钮选项，如 ['对行处理', '对列处理']
        operator_key:       符号结果存入 params 的键名，如 'operator'
        operator_options:   符号下拉选项，默认 ['=', '>', '<', '>=', '<=', '≠', '≡']
        constant_key:       常数结果存入 params 的键名，如 'constant'
        type_key:           检定类型结果存入 params 的键名，如 'inspect_type'
        type_options:       检定类型选项：任意判定/存在判定/存在型数量自定义/存在型比例自定义
        type_value_key:     数量/比例自定义值存入 params 的键名，如 'type_value'
        fail_key:           不通过输出结果存入 params 的键名，如 'fail_result'
        pass_key:           通过输出结果存入 params 的键名，如 'pass_result'
    """
    prompt: str
    direction_options: list[str]
    direction_key: str = 'direction'
    operator_key: str = 'operator'
    operator_options: list[str] = field(default_factory=lambda: ['=', '>', '<', '>=', '<=', '≠', '≡'])
    constant_key: str = 'constant'
    type_key: str = 'inspect_type'
    type_options: list[str] = field(default_factory=lambda: ['任意判定', '存在判定', '存在型数量自定义', '存在型比例自定义'])
    type_value_key: str = 'type_value'
    fail_key: str = 'fail_result'
    pass_key: str = 'pass_result'


@dataclass
class CustomCalcStep:
    """自定义运算：打开积木编辑器构建表达式，确定执行输出。

    面板：打开编辑器 / 检查报错 / 确定 三个按钮。
    编辑器内构建积木树（BlockNode），关闭后临时储存；
    确定执行时把积木树传给脚本 run 求值并输出。

    属性:
        prompt:             面板提示文字
        direction_key:      方向结果存入 params 的键名，如 'direction'
        key:                积木树结果存入 params 的键名，如 'custom_blocks'
    """
    prompt: str
    direction_key: str = 'direction'
    key: str = 'custom_blocks'


@dataclass
class SelectHeaderStep:
    """等待用户点击行头或列头选择参考行列。

    属性:
        prompt:     状态栏提示文字
        key:        结果存入 params 的键名，如 'ref_col'
        orientation: 'column'（点击列头）或 'row'（点击行头）
        bounds:     有效范围 (min, max)，如选区列范围 (c1, c2)
        validate:   校验函数，参数为 (index, cells)，cells 为该行列在选区内的值，
                    返回 (有效行数列表, 错误信息|None)
    """
    prompt: str
    key: str
    orientation: str  # 'column' | 'row'
    bounds: tuple[int, int] = field(default=(0, 0))
    validate: Callable[[list[str]], tuple[list[int], str | None]] | None = None


@dataclass
class SelectRangeExStep:
    """框选区域 + 自动识别 + 排除首行/首列按钮（选区热更新）。

    面板：自动识别按钮 → 「排除首行」「排除首列」两个按钮 → 确定。
    排除按钮点击时选区热更新：排除首行 → 选区上边界 +1；
    排除首列 → 选区左边界 +1（直到不能再缩）。

    属性:
        prompt:     面板提示文字
        key:        结果存入 params 的键名，如 'range'
    """
    prompt: str
    key: str = 'range'


@dataclass
class TextOperandStep:
    """字符串计算元收集：点选列/行、手动输入文本、剪贴板单/多文本，可动态添加。

    面板显示 N 个"计算元框"，每框右侧三角箭头下拉：
    点选列 / 点选行 / 手动输入文本 / 剪贴板单文本 / 剪贴板多文本 / 清除。
    字符串识别：所有非空格格当字符串（数字文字不区分），空格=空文本占位；
    无保留小数位数；确定时做全局对齐检查（按最长计算元）。

    属性:
        prompt:         面板提示文字
        key:            结果存入 params 的键名，如 'operands'
        direction_key:  运算方向所在的 param 键名（值含'行'表示按行运算）
        min_count:      默认生成的槽位数
        fixed_count:    >0 时槽位数量固定（不可添加/删除）
    """
    prompt: str
    key: str = 'operands'
    direction_key: str = 'direction'
    min_count: int = 2
    fixed_count: int = 0


@dataclass
class OperandInputStep:
    """收集多个计算元（点选列/行、手动常数、剪贴板），可动态添加。

    面板显示 N 个"计算元框"，每个框右侧三角箭头下拉：
    点选列 / 点选行 / 手动输入常数 / 从剪贴板接入 / 清除。
    每个计算元选中时立即识别（纯数字有效、空格报错、文字=标题、
    标题占比 >30% 报错），全部填好后点「确定」做全局对齐检查。

    属性:
        prompt:         面板提示文字
        key:            结果存入 params 的键名，如 'operands'
        direction_key:  运算方向所在的 param 键名（值含'行'表示按行运算）
        min_count:      默认生成的槽位数
        decimals:       True 时面板额外显示「保留小数位数」选择框
                        （默认=与计算元逐位置位数最多者一致 / 手动 0-10 位）
        operator:       非空时在第一个计算元与其余计算元之间显示运算符号行
                        （如减法传 '-'，提示第一个为被减数）
        fixed_count:    >0 时槽位数量固定（不可添加/删除），确定条件改为
                        全部 fixed_count 个槽位填满即可（如指数脚本固定
                        底数+指数 2 个槽位）
        slot_validators: 与槽位平行的逐槽校验函数列表，元素为
                         Callable[[list[float]], str | None] 或 None；
                         None 表示该槽不校验。点选列/行/常数时立即调用，
                         返回错误字符串则拒绝（如指数脚本底数槽校验非负）
        slot_labels:    与槽位平行的标签列表，代替默认的「选择计算元」
                        作为槽位初始文字（如指数脚本 ['底数', '指数']，
                        对数脚本 ['底数', '真数']）。None 时保持默认
    """
    prompt: str
    key: str = 'operands'
    direction_key: str = 'direction'
    min_count: int = 2
    decimals: bool = False
    operator: str = ''
    fixed_count: int = 0
    slot_validators: list[Callable[[list[float]], str | None] | None] | None = None
    slot_labels: list[str] | None = None


@dataclass
class OutputTargetStep:
    """选择结果输出位置：输出到剪贴板 / 点选输出列或行。

    面板显示两个按钮，点击即动作（无需再点确定）：
    - 「输出到剪贴板」→ 结果复制进剪贴板
    - 「点选输出列/行」→ 去表格点列头/行头，结果写入该列/行

    属性:
        prompt:         面板提示文字
        key:            结果存入 params 的键名，如 'output'
        direction_key:  运算方向所在的 param 键名
        invert:         True 时输出轴与 direction 推断相反
                        （统计类脚本：结果与处理单位垂直，如对列处理 → 点选输出行）
    """
    prompt: str
    key: str = 'output'
    direction_key: str = 'direction'
    invert: bool = False


@dataclass
class FindLookupStep:
    """查找脚本：选参考数据列/行 + 查找条件 + 确定。

    面板：提示点选参考列/行（方向随 unit 动态）→ 条件区
    （按数据查找：符号下拉 + 常数输入框；按文本查找：文本输入框 + 忽略首格）
    → 确定（参考已选 且 条件完整）。

    属性:
        prompt:             面板提示文字
        unit_key:           单位方向所在 param 键名（'以行为单位'/'以列为单位'）
        lookup_type_key:    查找类型所在 param 键名（'按数据查找'/'按文本查找'）
        ref_key:            参考列/行索引结果键名
        operator_key:       符号结果键名（数据查找）
        constant_key:       常数结果键名（数据查找）
        operator_options:   符号下拉选项（逻辑符号）
        text_key:           文本结果键名（文本查找）
        ignore_head_key:    忽略首格结果键名（文本查找，'忽略首格'/'不忽略首格'）
    """
    prompt: str
    unit_key: str = 'unit'
    lookup_type_key: str = 'lookup_type'
    ref_key: str = 'ref'
    operator_key: str = 'operator'
    constant_key: str = 'constant'
    operator_options: list[str] = field(
        default_factory=lambda: ['=', '>', '<', '>=', '<=', '≠', '≡'])
    text_key: str = 'text'
    ignore_head_key: str = 'ignore_head'


@dataclass
class FindOutputStep:
    """查找脚本：输出位置（提示栏 / 以行剪贴板 / 以列剪贴板），点击即输出。

    属性:
        prompt:  面板提示文字
        key:     输出方式结果键名
    """
    prompt: str
    key: str = 'find_output'


@dataclass
class TrigFunctionStep:
    """三角函数步骤：函数下拉 + 单个计算元 + 角度单位 + 保留小数。

    面板从上到下：函数下拉（9 个三角/反三角函数）→ 单个计算元槽位 →
    角度单位互斥按钮（弧度/度，默认弧度）→ 保留小数位数 → 确定。

    定义域校验：确定时由控制器遍历计算元所有值，结合所选函数/角度单位，
    任一越界即拒绝并报错（不推进）。

    属性:
        prompt:         面板提示文字
        key:            计算元结果存入 params 的键名，如 'operands'
        function_key:   函数选择结果存入 params 的键名，如 'function'
        unit_key:       角度单位结果存入 params 的键名，如 'unit'
        direction_key:  运算方向所在的 param 键名（值含'行'表示按行运算）
        functions:      下拉函数选项列表（9 个）
        units:          角度单位选项，如 ['弧度', '度']，默认第一个
        decimals:       True 时显示「保留小数位数」选择框
    """
    prompt: str
    functions: list[str]
    key: str = 'operands'
    function_key: str = 'function'
    unit_key: str = 'unit'
    direction_key: str = 'direction'
    units: list[str] = field(default_factory=lambda: ['弧度', '度'])
    decimals: bool = True
    # 复用 OperandInputStep 的计算元槽位逻辑
    min_count: int = 1
    fixed_count: int = 1
    slot_validators: list | None = None
    slot_labels: list[str] | None = None


# ══════════════════════════════════════════════════════════════════════
# 脚本基类
# ══════════════════════════════════════════════════════════════════════

class BaseScript:
    """所有用户脚本必须继承此类。

    用法示例::

        class MySort(BaseScript):
            name = '数值排序'
            description = '按数值大小对行或列进行排序'

            def steps(self):
                return [
                    SelectRangeStep('请框选排序区域'),
                    ChooseOptionStep('选择排序方式', {
                        'unit': ['按行', '按列'],
                        'order': ['升序', '降序'],
                    }),
                    SelectHeaderStep('请点击参考列', key='ref_col',
                                     orientation='column'),
                ]

            def run(self, sheet, params):
                # params = {'range': (r1,c1,r2,c2), 'unit': '按行',
                #            'order': '升序', 'ref_col': 2}
                ...
                return None  # 成功
    """

    name: str = ''
    description: str = ''

    def steps(self) -> list:
        """返回交互步骤列表。子类必须重写。"""
        raise NotImplementedError

    def run(self, sheet, params: dict) -> str | None:
        """执行脚本。返回 None 表示成功，返回 str 表示错误信息。子类必须重写。"""
        raise NotImplementedError
