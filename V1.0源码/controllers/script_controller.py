"""脚本控制器 — 加载脚本、逐步交互、执行脚本、管理撤销。"""
import importlib.util
import sys
import time
from pathlib import Path

from PyQt6.QtCore import QObject
from PyQt6.QtWidgets import QApplication

from scripts.base_script import (
    BaseScript, SelectRangeStep, SelectRangeExStep, ChooseOptionStep,
    ChooseQuantileStep, ChooseModeStep, ChooseCountStep, ChooseInspectStep,
    CustomCalcStep, SelectHeaderStep, OperandInputStep, TextOperandStep,
    OutputTargetStep, TrigFunctionStep, FindLookupStep, FindOutputStep,
)
from models.spreadsheet_model import SpreadsheetModel
from views.spreadsheet_grid import SpreadsheetGrid
from views.status_bar import StatusBar

_INVALID_RATIO_THRESHOLD = 0.3
_TITLE_RATIO_THRESHOLD = 0.3  # 计算元识别：标题/文字格占比上限（沿用排序脚本的 30%）


class ScriptController(QObject):
    """管理脚本执行的生命周期。

    所有交互提示通过侧栏脚本面板（_panel.set_script_prompt）展示，
    状态栏仅用于执行结果。
    """

    def __init__(self, model: SpreadsheetModel, grid: SpreadsheetGrid,
                 status_bar: StatusBar, side_panel):
        super().__init__()
        self._model = model
        self._grid = grid
        self._status = status_bar
        self._panel = side_panel

        self._script: BaseScript | None = None
        self._steps: list = []
        self._step_idx: int = 0
        self._params: dict = {}
        self._running = False
        self._executing = False

        # 计算元 / 输出位置步骤状态
        self._operand_step: OperandInputStep | None = None
        self._output_step: OutputTargetStep | None = None
        self._operand_slots: list = []   # 每个槽位的数据（None=空）
        self._pending_slot: int = -1     # 正在点选的槽位索引
        self._pick_kind: str = ''        # 'column' | 'row'（点选模式）
        # 保留小数位数状态（仅 step.decimals=True 时生效）
        self._decimals_mode: str = 'auto'      # 'auto' | 'manual'
        self._decimals_digits: int | None = None  # 手动输入的位数
        # 三角函数步骤状态
        self._trig_step: TrigFunctionStep | None = None
        self._trig_function: str = ''
        # 分位数步骤状态
        self._quantile_step: ChooseQuantileStep | None = None
        self._quantile_value: str = 'median'
        # 模式选择步骤状态
        self._mode_step: ChooseModeStep | None = None
        # 计数条件步骤状态
        self._count_step: ChooseCountStep | None = None
        # 检定步骤状态
        self._inspect_step: ChooseInspectStep | None = None
        # 框选排除 / 字符串计算元步骤状态
        self._range_ex_step: SelectRangeExStep | None = None
        self._text_operand_step: TextOperandStep | None = None
        # 自定义运算步骤状态
        self._custom_calc_step: CustomCalcStep | None = None
        self._custom_editor = None   # 编辑器实例（打开时创建，关闭保留）
        # 查找脚本步骤状态
        self._find_step: FindLookupStep | None = None
        self._find_picking = False   # 点选参考模式（点「选择参考」按钮后激活）

    # ------------------------------------------------------------------
    # 公开 API
    # ------------------------------------------------------------------

    def run_script(self, path: str) -> None:
        if self._running:
            return

        script = self._load_script(path)
        if script is None:
            return  # 错误已在 _load_script 内提示

        self._script = script
        self._steps = list(script.steps())
        self._step_idx = 0
        self._params = {}
        self._running = True

        self._panel.set_script_prompt(f'▶ {script.name}')
        self._start_step()

    def abort(self) -> None:
        if not self._running or self._executing:
            return
        self._cleanup()
        self._panel.clear_script_panel()

    # ------------------------------------------------------------------
    # 脚本加载
    # ------------------------------------------------------------------

    def _load_script(self, path: str) -> BaseScript | None:
        file_path = Path(path)
        if not file_path.exists():
            self._panel.set_script_prompt(f'❌ 文件不存在: {file_path.name}')
            return None

        old_dont_write = sys.dont_write_bytecode
        try:
            sys.dont_write_bytecode = True
            module_name = file_path.stem
            spec = importlib.util.spec_from_file_location(module_name, file_path)
            if spec is None or spec.loader is None:
                return None
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)

            for name in dir(module):
                obj = getattr(module, name)
                if (isinstance(obj, type) and
                        issubclass(obj, BaseScript) and
                        obj is not BaseScript):
                    return obj()
        except Exception as e:
            self._panel.set_script_prompt(f'❌ 脚本错误: {e}')
            return None
        finally:
            sys.dont_write_bytecode = old_dont_write

        self._panel.set_script_prompt('❌ 未找到有效的脚本类')
        return None

    # ------------------------------------------------------------------
    # 步骤状态机
    # ------------------------------------------------------------------

    def _start_step(self) -> None:
        if self._step_idx >= len(self._steps):
            self._execute()
            return

        step = self._steps[self._step_idx]
        self._panel.clear_script_panel()

        if isinstance(step, SelectRangeStep):
            self._begin_select_range(step)
        elif isinstance(step, SelectRangeExStep):
            self._begin_range_ex(step)
        elif isinstance(step, ChooseOptionStep):
            self._begin_choose_option(step)
        elif isinstance(step, ChooseQuantileStep):
            self._begin_quantile(step)
        elif isinstance(step, ChooseModeStep):
            self._begin_mode(step)
        elif isinstance(step, ChooseCountStep):
            self._begin_count(step)
        elif isinstance(step, ChooseInspectStep):
            self._begin_inspect(step)
        elif isinstance(step, CustomCalcStep):
            self._begin_custom_calc(step)
        elif isinstance(step, SelectHeaderStep):
            self._begin_select_header(step)
        elif isinstance(step, FindLookupStep):
            self._begin_find_lookup(step)
        elif isinstance(step, FindOutputStep):
            self._begin_find_output(step)
        elif isinstance(step, OperandInputStep):
            self._begin_operand_input(step)
        elif isinstance(step, TextOperandStep):
            self._begin_text_operand(step)
        elif isinstance(step, TrigFunctionStep):
            self._begin_trig_function(step)
        elif isinstance(step, OutputTargetStep):
            self._begin_output_target(step)

    def _advance_step(self) -> None:
        self._step_idx += 1
        self._start_step()

    # ------------------------------------------------------------------
    # 步骤 1：框选区域
    # ------------------------------------------------------------------

    def _begin_select_range(self, step: SelectRangeStep) -> None:
        self._panel.set_script_prompt(step.prompt)
        self._panel.show_auto_select_button()
        self._panel.auto_select_clicked.connect(self._on_auto_select)
        self._panel.show_confirm_button(
            enabled=self._grid.get_selection_range() is not None)
        self._panel.confirm_clicked.connect(self._on_range_confirmed)
        sel_model = self._grid.selectionModel()
        if sel_model:
            sel_model.selectionChanged.connect(self._on_range_selected)

    def _on_auto_select(self) -> None:
        """自动识别整个表格的数据外接矩形，并选中为排序区域。"""
        if not self._running:
            return
        bounds = self._model.data_bounds()
        if bounds is None:
            self._panel.set_script_prompt('❌ 表格为空，无法自动识别')
            return
        r1, c1, r2, c2 = bounds
        self._grid.set_selection_range(r1, c1, r2, c2)
        rows = r2 - r1 + 1
        cols = c2 - c1 + 1
        self._panel.set_script_prompt(f'已自动识别 {rows} 行 × {cols} 列，点「确定」继续')

    def _on_range_selected(self) -> None:
        """框选过程中只更新确定按钮状态，不推进步骤。"""
        if not self._running:
            return
        has_sel = self._grid.get_selection_range() is not None
        self._panel.set_confirm_enabled(has_sel)

    def _on_range_confirmed(self) -> None:
        """用户点确定后，才把当前选区存入 params 并推进。"""
        if not self._running:
            return
        step = self._steps[self._step_idx]
        if not isinstance(step, SelectRangeStep):
            return
        rng = self._grid.get_selection_range()
        if rng is None:
            return
        self._params[step.key] = rng
        self._panel.confirm_clicked.disconnect(self._on_range_confirmed)
        try: self._panel.auto_select_clicked.disconnect(self._on_auto_select)
        except TypeError: pass
        self._disconnect_range()
        self._advance_step()

    # ------------------------------------------------------------------
    # 步骤 1.5：框选 + 排除首行/首列（选区热更新）
    # ------------------------------------------------------------------

    def _begin_range_ex(self, step: SelectRangeExStep) -> None:
        self._range_ex_step = step
        self._panel.set_script_prompt(step.prompt)
        self._panel.show_range_ex_panel()
        self._panel.auto_select_clicked.connect(self._on_auto_select)
        self._panel.exclude_row_clicked.connect(self._on_exclude_row)
        self._panel.exclude_col_clicked.connect(self._on_exclude_col)
        self._panel.show_confirm_button(
            enabled=self._grid.get_selection_range() is not None)
        self._panel.confirm_clicked.connect(self._on_range_ex_confirmed)
        sel_model = self._grid.selectionModel()
        if sel_model:
            sel_model.selectionChanged.connect(self._on_range_selected)

    def _on_exclude_row(self) -> None:
        """排除首行：选区上边界 +1（热更新，直到只剩一行）。"""
        if not self._running:
            return
        rng = self._grid.get_selection_range()
        if rng is None:
            self._panel.set_script_prompt('❌ 请先框选区域')
            return
        r1, c1, r2, c2 = rng
        if r1 >= r2:
            self._panel.set_script_prompt('区域已无可排除的行')
            return
        self._grid.set_selection_range(r1 + 1, c1, r2, c2)
        self._panel.set_script_prompt(f'已排除首行，剩余 {r2 - r1} 行')

    def _on_exclude_col(self) -> None:
        """排除首列：选区左边界 +1（热更新，直到只剩一列）。"""
        if not self._running:
            return
        rng = self._grid.get_selection_range()
        if rng is None:
            self._panel.set_script_prompt('❌ 请先框选区域')
            return
        r1, c1, r2, c2 = rng
        if c1 >= c2:
            self._panel.set_script_prompt('区域已无可排除的列')
            return
        self._grid.set_selection_range(r1, c1 + 1, r2, c2)
        self._panel.set_script_prompt(f'已排除首列，剩余 {c2 - c1} 列')

    def _on_range_ex_confirmed(self) -> None:
        if not self._running:
            return
        step = self._steps[self._step_idx]
        if not isinstance(step, SelectRangeExStep):
            return
        rng = self._grid.get_selection_range()
        if rng is None:
            return
        self._params[step.key] = rng
        self._disconnect_quietly(self._panel.confirm_clicked, self._on_range_ex_confirmed)
        self._disconnect_quietly(self._panel.auto_select_clicked, self._on_auto_select)
        self._disconnect_quietly(self._panel.exclude_row_clicked, self._on_exclude_row)
        self._disconnect_quietly(self._panel.exclude_col_clicked, self._on_exclude_col)
        self._disconnect_range()
        self._advance_step()

    def _disconnect_range_ex_signals(self) -> None:
        self._disconnect_quietly(self._panel.auto_select_clicked, self._on_auto_select)
        self._disconnect_quietly(self._panel.exclude_row_clicked, self._on_exclude_row)
        self._disconnect_quietly(self._panel.exclude_col_clicked, self._on_exclude_col)
        self._disconnect_quietly(self._panel.confirm_clicked, self._on_range_ex_confirmed)

    # ------------------------------------------------------------------
    # 信号工具
    # ------------------------------------------------------------------

    @staticmethod
    def _disconnect_quietly(signal, slot) -> None:
        """静默断开信号：未连接时忽略 TypeError。"""
        try:
            signal.disconnect(slot)
        except TypeError:
            pass

    def _disconnect_range(self) -> None:
        sel_model = self._grid.selectionModel()
        if sel_model:
            self._disconnect_quietly(sel_model.selectionChanged, self._on_range_selected)

    def _disconnect_header_clicks(self) -> None:
        self._disconnect_quietly(self._grid.horizontalHeader().sectionClicked,
                                 self._on_header_clicked)
        self._disconnect_quietly(self._grid.verticalHeader().sectionClicked,
                                 self._on_header_clicked)

    # ------------------------------------------------------------------
    # 步骤 2：选择选项
    # ------------------------------------------------------------------

    def _begin_choose_option(self, step: ChooseOptionStep) -> None:
        self._panel.set_script_prompt(step.prompt)
        self._panel.show_script_buttons(step.groups, step.labels)
        self._panel.option_changed.connect(self._on_option_changed)
        self._panel.confirm_clicked.connect(self._on_options_confirmed)
        self._panel.show_confirm_button(enabled=False)

    def _on_option_changed(self, key: str, value: str) -> None:
        self._panel.show_confirm_button(enabled=self._panel.all_options_selected())

    def _on_options_confirmed(self) -> None:
        if not self._panel.all_options_selected():
            return
        step = self._steps[self._step_idx]
        if not isinstance(step, ChooseOptionStep):
            return
        for key in step.groups:
            val = self._panel.get_option(key)
            if val:
                self._params[key] = val
        self._panel.option_changed.disconnect(self._on_option_changed)
        self._panel.confirm_clicked.disconnect(self._on_options_confirmed)
        self._advance_step()

    # ------------------------------------------------------------------
    # 步骤 2.5：分位数（方向互斥按钮 + 分位数输入框）
    # ------------------------------------------------------------------

    def _begin_quantile(self, step: ChooseQuantileStep) -> None:
        self._quantile_step = step
        self._panel.set_script_prompt(step.prompt)
        self._panel.show_quantile_panel(step.direction_options)
        # 分位数输入框信号（模式切换 / 手动值提交 / 取消）
        self._panel.quantile_mode_changed.connect(self._on_quantile_mode)
        self._panel.quantile_value_submitted.connect(self._on_quantile_value)
        self._panel.quantile_cancelled.connect(self._on_quantile_cancel)
        # 方向按钮变化 → 刷新确定可用
        self._panel.option_changed.connect(self._on_quantile_option_changed)
        # 确定
        self._panel.confirm_clicked.connect(self._on_quantile_confirmed)

    def _on_quantile_mode(self, mode: str) -> None:
        """分位数框菜单选择：中位数 或 手动输入。"""
        if not self._running or self._quantile_step is None:
            return
        if mode == 'manual':
            self._panel.show_quantile_editor()
            self._panel.set_script_prompt('请输入分位数（0-1 之间的小数），回车确认（Esc 取消）')
        else:
            # 中位数：恢复默认，值记为 median
            self._quantile_value = 'median'
            self._panel.reset_quantile('中位数')
            self._panel.set_quantile_value('median')
            self._panel.set_script_prompt(self._quantile_step.prompt)
            self._refresh_quantile_confirm()

    def _on_quantile_value(self, text: str) -> None:
        """手动分位数提交：校验 (0,1) 内，通过则记录并启用确定；失败则报错恢复默认。"""
        if not self._running or self._quantile_step is None:
            return
        text = text.strip()
        try:
            v = float(text)
        except ValueError:
            self._panel.set_script_prompt('❌ 分位数无效，请输入 0-1 之间的数')
            self._panel.reset_quantile('中位数')
            self._quantile_value = 'median'
            self._refresh_quantile_confirm()
            return
        if not (0 < v < 1):
            self._panel.set_script_prompt('❌ 分位数需在 (0,1) 内，当前输入无效')
            self._panel.reset_quantile('中位数')
            self._quantile_value = 'median'
            self._refresh_quantile_confirm()
            return
        self._quantile_value = text
        self._panel.set_quantile_display(f'分位数 {text}')
        self._panel.set_quantile_value(text)
        self._panel.set_script_prompt(self._quantile_step.prompt)
        self._refresh_quantile_confirm()

    def _on_quantile_cancel(self) -> None:
        """用户 Esc 取消手动输入：恢复主提示。"""
        if not self._running or self._quantile_step is None:
            return
        self._panel.set_script_prompt(self._quantile_step.prompt)

    def _on_quantile_option_changed(self, key: str, value: str) -> None:
        """方向按钮变化：刷新确定按钮可用性。"""
        if not self._running or key != 'direction':
            return
        self._refresh_quantile_confirm()

    def _refresh_quantile_confirm(self) -> None:
        """确定按钮可用 = 方向已选 且 分位数已确认。"""
        ready = (self._panel.direction_ready and self._panel.quantile_readable())
        self._panel.set_confirm_enabled(ready)

    def _on_quantile_confirmed(self) -> None:
        if not self._running or self._quantile_step is None:
            return
        step = self._quantile_step
        if not (self._panel.direction_ready and self._panel.quantile_readable()):
            return  # 按钮未亮，防御
        direction = self._panel.get_direction_option()
        if direction:
            self._params[step.direction_key] = direction
        # 分位数值：median 或 小数字符串
        qv = self._panel.get_quantile_value()
        self._params[step.quantile_key] = 0.5 if qv == 'median' else float(qv)
        # 断开信号
        self._disconnect_quietly(self._panel.quantile_mode_changed, self._on_quantile_mode)
        self._disconnect_quietly(self._panel.quantile_value_submitted, self._on_quantile_value)
        self._disconnect_quietly(self._panel.quantile_cancelled, self._on_quantile_cancel)
        self._disconnect_quietly(self._panel.option_changed, self._on_quantile_option_changed)
        self._disconnect_quietly(self._panel.confirm_clicked, self._on_quantile_confirmed)
        self._advance_step()

    def _disconnect_quantile_signals(self) -> None:
        self._disconnect_quietly(self._panel.quantile_mode_changed, self._on_quantile_mode)
        self._disconnect_quietly(self._panel.quantile_value_submitted, self._on_quantile_value)
        self._disconnect_quietly(self._panel.quantile_cancelled, self._on_quantile_cancel)
        self._disconnect_quietly(self._panel.option_changed, self._on_quantile_option_changed)
        self._disconnect_quietly(self._panel.confirm_clicked, self._on_quantile_confirmed)

    # ------------------------------------------------------------------
    # 步骤 2.6：模式选择（方向互斥按钮 + 模式选择框）
    # ------------------------------------------------------------------

    def _begin_mode(self, step: ChooseModeStep) -> None:
        self._mode_step = step
        self._panel.set_script_prompt(step.prompt)
        self._panel.show_mode_panel(step.direction_options,
                                    mode_options=step.mode_options)
        # 模式选择信号
        self._panel.mode_selected.connect(self._on_mode_selected)
        # 方向按钮变化 → 刷新确定可用
        self._panel.option_changed.connect(self._on_mode_option_changed)
        # 确定
        self._panel.confirm_clicked.connect(self._on_mode_confirmed)

    def _on_mode_selected(self, text: str) -> None:
        """模式选择框菜单选择（默认/精确），记录并刷新确定。"""
        if not self._running or self._mode_step is None:
            return
        self._panel.set_mode_value(text)
        self._refresh_mode_confirm()

    def _on_mode_option_changed(self, key: str, value: str) -> None:
        """方向按钮变化：刷新确定按钮可用性。"""
        if not self._running or key != 'direction':
            return
        self._refresh_mode_confirm()

    def _refresh_mode_confirm(self) -> None:
        """确定按钮可用 = 方向已选 且 模式已选（默认恒满足）。"""
        ready = (self._panel.direction_ready and self._panel.mode_readable())
        self._panel.set_confirm_enabled(ready)

    def _on_mode_confirmed(self) -> None:
        if not self._running or self._mode_step is None:
            return
        step = self._mode_step
        if not (self._panel.direction_ready and self._panel.mode_readable()):
            return  # 按钮未亮，防御
        direction = self._panel.get_direction_option()
        if direction:
            self._params[step.direction_key] = direction
        mode = self._panel.get_mode_value()
        self._params[step.mode_key] = mode
        # 断开信号
        self._disconnect_quietly(self._panel.mode_selected, self._on_mode_selected)
        self._disconnect_quietly(self._panel.option_changed, self._on_mode_option_changed)
        self._disconnect_quietly(self._panel.confirm_clicked, self._on_mode_confirmed)
        self._advance_step()

    def _disconnect_mode_signals(self) -> None:
        self._disconnect_quietly(self._panel.mode_selected, self._on_mode_selected)
        self._disconnect_quietly(self._panel.option_changed, self._on_mode_option_changed)
        self._disconnect_quietly(self._panel.confirm_clicked, self._on_mode_confirmed)

    # ------------------------------------------------------------------
    # 步骤 2.7：计数条件（方向互斥按钮 + 符号下拉 + 常数输入框）
    # ------------------------------------------------------------------

    def _begin_count(self, step: ChooseCountStep) -> None:
        self._count_step = step
        self._panel.set_script_prompt(step.prompt)
        self._panel.show_count_panel(step.direction_options,
                                     operator_options=step.operator_options)
        # 符号下拉 / 常数输入信号
        self._panel.operator_changed.connect(self._on_count_operator)
        self._panel.constant_submitted.connect(self._on_count_constant)
        self._panel.constant_cancelled.connect(self._on_count_constant_cancel)
        self._panel.constant_changed.connect(self._on_count_constant_changed)
        # 方向按钮变化 → 刷新确定可用
        self._panel.option_changed.connect(self._on_count_option_changed)
        # 确定
        self._panel.confirm_clicked.connect(self._on_count_confirmed)

    def _on_count_constant_changed(self) -> None:
        """常数内容变化：重置为未确认并刷新确定按钮。"""
        if not self._running:
            return
        if self._count_step is not None:
            self._refresh_count_confirm()
        elif self._inspect_step is not None:
            self._refresh_inspect_confirm()

    def _on_count_operator(self, text: str) -> None:
        if not self._running or (self._count_step is None and self._inspect_step is None):
            return
        self._panel.set_operator(text)

    def _on_count_constant(self, text: str) -> None:
        """常数回车提交：校验任意实数，通过则记录并刷新确定。

        计数与检定脚本共用（对应 _count_step 或 _inspect_step）。
        """
        if not self._running or (self._count_step is None and self._inspect_step is None):
            return
        text = text.strip()
        try:
            float(text)
        except ValueError:
            self._panel.set_script_prompt('❌ 常数无效，请输入任意实数（Esc 取消）')
            return
        self._panel.set_count_constant(text)
        if self._count_step is not None:
            self._panel.set_script_prompt(self._count_step.prompt)
            self._refresh_count_confirm()
        else:
            self._panel.set_script_prompt(self._inspect_step.prompt)
            self._refresh_inspect_confirm()

    def _on_count_constant_cancel(self) -> None:
        """用户 Esc 取消常数输入：恢复主提示。"""
        if not self._running or (self._count_step is None and self._inspect_step is None):
            return
        step = self._count_step if self._count_step is not None else self._inspect_step
        self._panel.set_script_prompt(step.prompt)

    def _on_count_option_changed(self, key: str, value: str) -> None:
        if not self._running or key != 'direction':
            return
        self._refresh_count_confirm()

    def _refresh_count_confirm(self) -> None:
        """确定可用 = 方向已选 且 常数已确认。"""
        ready = (self._panel.direction_ready and self._panel.count_ready())
        self._panel.set_confirm_enabled(ready)

    def _on_count_confirmed(self) -> None:
        if not self._running or self._count_step is None:
            return
        step = self._count_step
        if not (self._panel.direction_ready and self._panel.count_ready()):
            return  # 按钮未亮，防御
        direction = self._panel.get_direction_option()
        if direction:
            self._params[step.direction_key] = direction
        self._params[step.operator_key] = self._panel.get_count_operator()
        # 常数以原文文本存储（≡ 严格相等需比较文本；脚本内数值比较时再转 float）
        self._params[step.constant_key] = self._panel.get_count_constant()
        # 断开信号
        self._disconnect_quietly(self._panel.operator_changed, self._on_count_operator)
        self._disconnect_quietly(self._panel.constant_submitted, self._on_count_constant)
        self._disconnect_quietly(self._panel.constant_cancelled, self._on_count_constant_cancel)
        self._disconnect_quietly(self._panel.constant_changed, self._on_count_constant_changed)
        self._disconnect_quietly(self._panel.option_changed, self._on_count_option_changed)
        self._disconnect_quietly(self._panel.confirm_clicked, self._on_count_confirmed)
        self._advance_step()

    def _disconnect_count_signals(self) -> None:
        self._disconnect_quietly(self._panel.operator_changed, self._on_count_operator)
        self._disconnect_quietly(self._panel.constant_submitted, self._on_count_constant)
        self._disconnect_quietly(self._panel.constant_cancelled, self._on_count_constant_cancel)
        self._disconnect_quietly(self._panel.constant_changed, self._on_count_constant_changed)
        self._disconnect_quietly(self._panel.option_changed, self._on_count_option_changed)
        self._disconnect_quietly(self._panel.confirm_clicked, self._on_count_confirmed)

    # ------------------------------------------------------------------
    # 步骤 2.8：检定（方向 + 检定条件 + 检定类型 + 输出结果）
    # ------------------------------------------------------------------

    def _begin_inspect(self, step: ChooseInspectStep) -> None:
        self._inspect_step = step
        self._panel.set_script_prompt(step.prompt)
        self._panel.show_inspect_panel(step.direction_options,
                                       operator_options=step.operator_options,
                                       type_options=step.type_options)
        # 符号 / 常数（复用计数逻辑）
        self._panel.operator_changed.connect(self._on_count_operator)
        self._panel.constant_submitted.connect(self._on_count_constant)
        self._panel.constant_cancelled.connect(self._on_count_constant_cancel)
        self._panel.constant_changed.connect(self._on_count_constant_changed)
        # 检定类型
        self._panel.inspect_type_changed.connect(self._on_inspect_type)
        self._panel.inspect_value_submitted.connect(self._on_inspect_value)
        self._panel.inspect_value_cancelled.connect(self._on_inspect_value_cancel)
        # 输出结果两框
        self._panel.fail_mode_changed.connect(self._on_fail_mode)
        self._panel.fail_value_submitted.connect(self._on_fail_value)
        self._panel.fail_value_cancelled.connect(self._on_fail_cancel)
        self._panel.pass_mode_changed.connect(self._on_pass_mode)
        self._panel.pass_value_submitted.connect(self._on_pass_value)
        self._panel.pass_value_cancelled.connect(self._on_pass_cancel)
        # 方向变化 → 刷新确定可用
        self._panel.option_changed.connect(self._on_inspect_option_changed)
        # 确定
        self._panel.confirm_clicked.connect(self._on_inspect_confirmed)

    def _on_inspect_type(self, text: str) -> None:
        """检定类型菜单选择。数量/比例自定义 → 打开输入框。"""
        if not self._running or self._inspect_step is None:
            return
        self._panel.set_inspect_type(text)
        if text in ('存在型数量自定义', '存在型比例自定义'):
            self._panel.show_inspect_type_editor()
            hint = ('请输入自然数（≥0 整数），回车确认（Esc 取消）'
                    if text == '存在型数量自定义'
                    else '请输入比例（0-1 之间小数），回车确认（Esc 取消）')
            self._panel.set_script_prompt(hint)
        else:
            self._panel.set_inspect_type_display(text)
            self._panel.set_script_prompt(self._inspect_step.prompt)
        self._refresh_inspect_confirm()

    def _on_inspect_value(self, text: str) -> None:
        """检定类型自定义值提交：数量→自然数；比例→[0,1]；失败报错并恢复未输入。"""
        if not self._running or self._inspect_step is None:
            return
        text = text.strip()
        t = self._panel.get_inspect_type()
        ok = False
        if t == '存在型数量自定义':
            if text.isdigit():
                ok = True
            else:
                self._panel.set_script_prompt('❌ 数量无效，请输入自然数（≥0 整数）')
        else:  # 存在型比例自定义
            try:
                v = float(text)
            except ValueError:
                self._panel.set_script_prompt('❌ 比例无效，请输入 0-1 之间小数')
            else:
                if 0 <= v <= 1:
                    ok = True
                else:
                    self._panel.set_script_prompt('❌ 比例需在 [0,1] 内')
        if not ok:
            # 恢复未输入状态：显示类型名（不带值），清除已记录值
            self._panel.set_inspect_value(None)
            self._panel.reset_inspect_type(t)
            self._refresh_inspect_confirm()
            return
        self._panel.set_inspect_value(text)
        self._panel.set_inspect_type_display(f'{t}：{text}')
        self._panel.set_script_prompt(self._inspect_step.prompt)
        self._refresh_inspect_confirm()

    def _on_inspect_value_cancel(self) -> None:
        if not self._running or self._inspect_step is None:
            return
        self._panel.set_script_prompt(self._inspect_step.prompt)

    def _on_fail_mode(self, mode: str) -> None:
        if not self._running or self._inspect_step is None:
            return
        if mode == 'custom':
            self._panel.show_fail_editor()
            self._panel.set_fail_result(None)  # 编辑中视为未确认
            self._panel.set_script_prompt('请输入不通过时的输出内容，回车确认（Esc 取消）')
        else:
            self._panel.reset_fail()
            self._panel.set_fail_result('0')
            self._panel.set_script_prompt(self._inspect_step.prompt)
        self._refresh_inspect_confirm()

    def _on_fail_value(self, text: str) -> None:
        if not self._running or self._inspect_step is None:
            return
        self._panel.set_fail_result(text)
        self._panel.set_fail_display(text)
        self._panel.set_script_prompt(self._inspect_step.prompt)
        self._refresh_inspect_confirm()

    def _on_fail_cancel(self) -> None:
        if not self._running or self._inspect_step is None:
            return
        # 取消：恢复默认不通过结果 0
        self._panel.reset_fail()
        self._panel.set_fail_result('0')
        self._panel.set_script_prompt(self._inspect_step.prompt)
        self._refresh_inspect_confirm()

    def _on_pass_mode(self, mode: str) -> None:
        if not self._running or self._inspect_step is None:
            return
        if mode == 'custom':
            self._panel.show_pass_editor()
            self._panel.set_pass_result(None)  # 编辑中视为未确认
            self._panel.set_script_prompt('请输入通过时的输出内容，回车确认（Esc 取消）')
        else:
            self._panel.reset_pass()
            self._panel.set_pass_result('1')
            self._panel.set_script_prompt(self._inspect_step.prompt)
        self._refresh_inspect_confirm()

    def _on_pass_value(self, text: str) -> None:
        if not self._running or self._inspect_step is None:
            return
        self._panel.set_pass_result(text)
        self._panel.set_pass_display(text)
        self._panel.set_script_prompt(self._inspect_step.prompt)
        self._refresh_inspect_confirm()

    def _on_pass_cancel(self) -> None:
        if not self._running or self._inspect_step is None:
            return
        # 取消：恢复默认通过结果 1
        self._panel.reset_pass()
        self._panel.set_pass_result('1')
        self._panel.set_script_prompt(self._inspect_step.prompt)
        self._refresh_inspect_confirm()

    def _on_inspect_option_changed(self, key: str, value: str) -> None:
        if not self._running or key != 'direction':
            return
        self._refresh_inspect_confirm()

    def _refresh_inspect_confirm(self) -> None:
        ready = self._panel.inspect_ready()
        self._panel.set_confirm_enabled(ready)

    def _on_inspect_confirmed(self) -> None:
        if not self._running or self._inspect_step is None:
            return
        step = self._inspect_step
        if not self._panel.inspect_ready():
            return  # 按钮未亮，防御
        direction = self._panel.get_direction_option()
        if direction:
            self._params[step.direction_key] = direction
        self._params[step.operator_key] = self._panel.get_count_operator()
        self._params[step.constant_key] = self._panel.get_count_constant()  # 文本（≡ 需原文）
        self._params[step.type_key] = self._panel.get_inspect_type()
        iv = self._panel.get_inspect_value()
        self._params[step.type_value_key] = iv  # 数量/比例值（文本或 None）
        self._params[step.fail_key] = self._panel.get_fail_result()
        self._params[step.pass_key] = self._panel.get_pass_result()
        # 断开信号
        self._disconnect_inspect_signals()
        self._advance_step()

    def _disconnect_inspect_signals(self) -> None:
        self._disconnect_quietly(self._panel.operator_changed, self._on_count_operator)
        self._disconnect_quietly(self._panel.constant_submitted, self._on_count_constant)
        self._disconnect_quietly(self._panel.constant_cancelled, self._on_count_constant_cancel)
        self._disconnect_quietly(self._panel.constant_changed, self._on_count_constant_changed)
        self._disconnect_quietly(self._panel.inspect_type_changed, self._on_inspect_type)
        self._disconnect_quietly(self._panel.inspect_value_submitted, self._on_inspect_value)
        self._disconnect_quietly(self._panel.inspect_value_cancelled, self._on_inspect_value_cancel)
        self._disconnect_quietly(self._panel.fail_mode_changed, self._on_fail_mode)
        self._disconnect_quietly(self._panel.fail_value_submitted, self._on_fail_value)
        self._disconnect_quietly(self._panel.fail_value_cancelled, self._on_fail_cancel)
        self._disconnect_quietly(self._panel.pass_mode_changed, self._on_pass_mode)
        self._disconnect_quietly(self._panel.pass_value_submitted, self._on_pass_value)
        self._disconnect_quietly(self._panel.pass_value_cancelled, self._on_pass_cancel)
        self._disconnect_quietly(self._panel.option_changed, self._on_inspect_option_changed)
        self._disconnect_quietly(self._panel.confirm_clicked, self._on_inspect_confirmed)

    # ------------------------------------------------------------------
    # 步骤 2.9：自定义运算（打开编辑器构建表达式）
    # ------------------------------------------------------------------

    def _begin_custom_calc(self, step: CustomCalcStep) -> None:
        """自定义运算步骤：显示 打开编辑器/检查报错/确定 三按钮。

        设计记录（02-操作类型.md 92-105 行）：选方向后侧栏显示三按钮
        （编辑器关闭时），点「打开编辑器」才打开编辑器弹窗，不自动弹窗。
        """
        self._custom_calc_step = step
        self._custom_editor = None   # 编辑器实例（打开时创建）
        self._panel.set_script_prompt(step.prompt)
        self._panel.show_custom_calc_buttons(confirm_enabled=False)
        self._panel.open_editor_clicked.connect(self._on_open_custom_editor)
        self._panel.check_errors_clicked.connect(self._on_check_custom_errors)
        self._panel.confirm_clicked.connect(self._on_custom_calc_confirmed)

    def _on_open_custom_editor(self):
        """点「打开编辑器」：打开编辑器弹窗，关闭后存积木树到 params。

        编辑器关闭 = 隐藏保留（设计约定），无论 exec 返回值都存积木。
        """
        from custom_calc.editor import CustomCalcEditor
        step = self._custom_calc_step
        if step is None:
            return
        if self._custom_editor is None:
            direction = self._params.get(step.direction_key, '')
            self._custom_editor = CustomCalcEditor(direction=direction,
                                                   model=self._model)
        editor = self._custom_editor
        editor.exec()  # 模态；关闭（Esc/X/右上角）即隐藏保留
        blocks = editor.get_blocks()
        self._params[step.key] = blocks
        self._params[step.direction_key] = self._params.get(
            step.direction_key, '')
        if blocks:
            # 关闭编辑器即校验：有错 → 确定按钮不亮（用户反馈，10 计划）
            from custom_calc.editor import validate_blocks
            errs = validate_blocks(
                blocks, model=self._model,
                direction=self._params.get(step.direction_key, ''))
            if errs:
                self._panel.show_confirm_button(enabled=False)
                self._panel.set_script_prompt(
                    f'积木存在 {len(errs)} 个问题，请修复'
                    '（点「检查报错」查看详情）')
            else:
                self._panel.show_confirm_button(enabled=True)
                self._panel.set_script_prompt(
                    f'已构建 {len(blocks)} 个积木，点「确定」执行')
        else:
            self._panel.show_confirm_button(enabled=False)
            self._panel.set_script_prompt(step.prompt)

    def _on_check_custom_errors(self):
        """点「检查报错」：对临时储存区积木校验，独立弹窗列出。"""
        from custom_calc.editor import validate_blocks
        from PyQt6.QtWidgets import QMessageBox
        step = self._custom_calc_step
        if step is None:
            return
        blocks = self._params.get(step.key, [])
        if not blocks:
            QMessageBox.information(self._panel, '检查报错',
                                    '尚未构建积木，请先点「打开编辑器」')
            return
        errs = validate_blocks(blocks,
                               model=self._model,
                               direction=self._params.get(
                                   step.direction_key, ''))
        if not errs:
            QMessageBox.information(self._panel, '检查报错',
                                    '没有语法错误，允许输出')
        else:
            text = '\n'.join(f'• {e}' for e in errs)
            QMessageBox.warning(self._panel, '检查报错',
                                f'存在以下问题：\n\n{text}')

    def _on_custom_calc_confirmed(self) -> None:
        """侧栏确定：无积木则提示先构建；有则推进执行（脚本 run 做求值输出）。"""
        if not self._running or self._custom_calc_step is None:
            return
        step = self._custom_calc_step
        blocks = self._params.get(step.key)
        if not blocks:
            self._panel.set_script_prompt('❌ 尚未构建积木，请先点「打开编辑器」')
            return
        self._panel.confirm_clicked.disconnect(self._on_custom_calc_confirmed)
        self._advance_step()

    def _disconnect_custom_calc_signals(self) -> None:
        self._disconnect_quietly(self._panel.confirm_clicked,
                                 self._on_custom_calc_confirmed)
        self._disconnect_quietly(self._panel.open_editor_clicked,
                                 self._on_open_custom_editor)
        self._disconnect_quietly(self._panel.check_errors_clicked,
                                 self._on_check_custom_errors)

    # ------------------------------------------------------------------
    # 步骤 3：点击列头/行头选参考
    # ------------------------------------------------------------------

    def _begin_select_header(self, step: SelectHeaderStep) -> None:
        self._apply_dynamic_fields(step)
        self._panel.set_script_prompt(self._resolve_prompt(step))

        h_header = self._grid.horizontalHeader()
        v_header = self._grid.verticalHeader()

        if step.orientation == 'column':
            h_header.sectionClicked.connect(self._on_header_clicked)
        else:
            v_header.sectionClicked.connect(self._on_header_clicked)

    def _apply_dynamic_fields(self, step: SelectHeaderStep) -> None:
        unit = self._params.get('unit', '')
        rng = self._params.get('range')
        step.orientation = 'column' if '行' in unit else 'row'
        step.key = 'ref'
        if rng:
            r1, c1, r2, c2 = rng
            step.bounds = (c1, c2) if step.orientation == 'column' else (r1, r2)

    def _on_header_clicked(self, section: int) -> None:
        if not self._running:
            return
        step = self._steps[self._step_idx]
        if not isinstance(step, SelectHeaderStep):
            return
        rng = self._params.get('range')
        if rng is None:
            return
        r1, c1, r2, c2 = rng

        lo, hi = step.bounds
        if section < lo or section > hi:
            self._panel.set_script_prompt(f'❌ 请在选区范围内选择')
            return

        cells: list[str] = []
        if step.orientation == 'column':
            for r in range(r1, r2 + 1):
                cells.append(self._model.value(r, section))
        else:
            for c in range(c1, c2 + 1):
                cells.append(self._model.value(section, c))

        valid_indices, error = (step.validate(cells) if step.validate
                                else self._validate_numeric_reference(cells))
        if error:
            self._panel.set_script_prompt(f'❌ {error}')
            return

        self._params[step.key] = section
        self._params['_valid_indices'] = valid_indices
        self._disconnect_header_clicks()
        self._advance_step()

    def _disconnect_header_clicks(self) -> None:
        h = self._grid.horizontalHeader()
        v = self._grid.verticalHeader()
        try: h.sectionClicked.disconnect(self._on_header_clicked)
        except TypeError: pass
        try: v.sectionClicked.disconnect(self._on_header_clicked)
        except TypeError: pass

    # ------------------------------------------------------------------
    # 查找脚本：选参考 + 条件 + 确定；输出位置
    # ------------------------------------------------------------------

    def _begin_find_lookup(self, step: FindLookupStep) -> None:
        self._find_step = step
        self._find_picking = False   # 点选模式：点「选择参考」按钮后激活
        unit = self._params.get(step.unit_key, '')
        lookup_type = self._params.get(step.lookup_type_key, '')
        by_row = '行' in unit
        rng = self._params.get('range') or (0, 0, 0, 0)
        self._find_bounds = (rng[1], rng[3]) if by_row else (rng[0], rng[2])
        ref_label = '参考列' if by_row else '参考行'
        self._panel.set_script_prompt(
            f'请先点「选择{ref_label}」按钮，再点击{ref_label}头'
            f'（以{unit}，查找：{lookup_type}）')
        self._panel.show_find_lookup_panel(lookup_type, step.operator_options,
                                           ref_label=ref_label)
        # 点选参考：点按钮后激活点选模式（此时点列头/行头才生效）
        self._panel.find_pick_ref_clicked.connect(self._on_find_pick_ref)
        # 条件信号（对照计数/检定脚本）
        self._panel.operator_changed.connect(self._on_find_operator)
        self._panel.constant_submitted.connect(self._on_find_constant)
        self._panel.constant_changed.connect(self._on_find_constant_changed)
        self._panel.constant_cancelled.connect(self._on_find_constant_cancel)
        self._panel.text_submitted.connect(self._on_find_text)
        self._panel.text_changed.connect(self._on_find_text_changed)
        self._panel.text_cancelled.connect(self._on_find_text_cancel)
        self._panel.ignore_head_changed.connect(self._on_find_ignore_head)
        self._panel.confirm_clicked.connect(self._on_find_lookup_confirmed)
        # 默认条件（数据：operator 默认第一个；文本：不忽略首格）
        self._params[step.operator_key] = step.operator_options[0]
        self._params[step.ignore_head_key] = '不忽略首格'
        self._params.pop(step.constant_key, None)
        self._params.pop(step.text_key, None)
        self._params.pop(step.ref_key, None)
        self._refresh_find_confirm()

    def _on_find_pick_ref(self) -> None:
        """点「选择参考列/行」：进入点选模式，提示点列头/行头。"""
        if not self._running or self._find_step is None:
            return
        unit = self._params.get(self._find_step.unit_key, '')
        by_row = '行' in unit
        ref_label = '参考列' if by_row else '参考行'
        self._find_picking = True
        header = self._grid.horizontalHeader() if by_row \
            else self._grid.verticalHeader()
        header.sectionClicked.connect(self._on_find_ref_clicked)
        self._panel.set_script_prompt(f'请点击{ref_label}头（{ref_label}）')

    def _on_find_ref_clicked(self, section: int) -> None:
        if not self._running or not getattr(self, '_find_picking', False):
            return   # 未点「选择参考」按钮：点列头不生效
        if self._find_step is None:
            self._panel.set_script_prompt('❌ 查找流程未就绪，请重新运行脚本')
            return
        lo, hi = self._find_bounds
        if section < lo or section > hi:
            self._panel.set_script_prompt('❌ 请在选区范围内选择参考')
            return
        step = self._find_step
        # 数据查找：校验参考列/行（空格报错、排除标题单位），生成有效索引
        if '数据' in self._params.get(step.lookup_type_key, ''):
            rng = self._params.get('range')
            if rng:
                r1, c1, r2, c2 = rng
                by_row = '行' in self._params.get(step.unit_key, '')
                cells = [self._model.value(r, section)
                         for r in range(r1, r2 + 1)] if by_row else \
                        [self._model.value(section, c)
                         for c in range(c1, c2 + 1)]
                # 用户设计：参考格为空 → 报错拒绝
                if any(not c.strip() for c in cells):
                    self._panel.set_script_prompt(
                        '❌ 参考列/行存在空格，无法判定')
                    return
                valid, error = self._validate_find_reference(cells)
                if error:
                    self._panel.set_script_prompt(f'❌ {error}')
                    return
                self._params['_valid_indices'] = valid
            else:
                self._params.pop('_valid_indices', None)
        self._params[step.ref_key] = section
        self._find_picking = False   # 点选完成，退出点选模式
        self._refresh_find_confirm()
        self._panel.set_script_prompt(
            f'已选参考{"列" if section >= 0 else "行"}'
            f'，{"请输常数后点确定" if "数据" in self._params.get(step.lookup_type_key, "") else "请输入查找文本后点确定"}')

    def _on_find_operator(self, text: str) -> None:
        if not self._running or self._find_step is None:
            return
        self._params[self._find_step.operator_key] = text

    def _on_find_constant(self, text: str) -> None:
        if not self._running or self._find_step is None:
            return
        text = text.strip()
        try:
            float(text)
        except ValueError:
            self._panel.set_script_prompt('❌ 常数无效，请输入任意实数（Esc 取消）')
            return
        # 对照计数/检定：先面板记录确认态（set_count_constant → clearFocus → 恢复 Enter）
        self._panel.set_count_constant(text)
        self._params[self._find_step.constant_key] = text
        self._panel.set_script_prompt(self._find_step.prompt)
        self._refresh_find_confirm()

    def _on_find_constant_changed(self) -> None:
        if self._find_step is not None:
            self._params.pop(self._find_step.constant_key, None)
            self._refresh_find_confirm()

    def _on_find_constant_cancel(self) -> None:
        if self._find_step is not None:
            self._params.pop(self._find_step.constant_key, None)
            self._refresh_find_confirm()

    def _on_find_text(self, text: str) -> None:
        if not self._running or self._find_step is None:
            return
        text = text.strip()
        if not text:
            self._panel.set_script_prompt('❌ 查找文本不能为空（Esc 取消）')
            return
        self._params[self._find_step.text_key] = text
        # 退出输入态（恢复 Enter 快捷键，与常数输入一致）
        fe = getattr(self._panel, '_find_text_edit', None)
        if fe is not None:
            fe.clearFocus()
        self._panel.set_script_prompt(self._find_step.prompt)
        self._refresh_find_confirm()

    def _on_find_text_changed(self) -> None:
        if self._find_step is not None:
            self._params.pop(self._find_step.text_key, None)
            self._refresh_find_confirm()

    def _on_find_text_cancel(self) -> None:
        if self._find_step is not None:
            self._params.pop(self._find_step.text_key, None)
            self._refresh_find_confirm()

    def _on_find_ignore_head(self, value: str) -> None:
        if self._find_step is not None:
            self._params[self._find_step.ignore_head_key] = value

    def _refresh_find_confirm(self) -> None:
        step = self._find_step
        if step is None:
            return
        ref_ok = step.ref_key in self._params
        if '数据' in self._params.get(step.lookup_type_key, ''):
            # 对照计数/检定：以面板确认态判定（set_count_constant 记录）
            cond_ok = self._panel.get_count_constant() is not None
        else:
            cond_ok = step.text_key in self._params
        self._panel.show_confirm_button(enabled=ref_ok and cond_ok)

    def _on_find_lookup_confirmed(self) -> None:
        step = self._find_step
        if step is None:
            return
        if step.ref_key not in self._params:
            return
        if '数据' in self._params.get(step.lookup_type_key, ''):
            if step.constant_key not in self._params:
                return
        elif step.text_key not in self._params:
            return
        self._disconnect_find_lookup_signals()
        self._advance_step()

    def _disconnect_find_lookup_signals(self) -> None:
        if self._find_step is None:
            return
        self._find_step = None
        self._find_picking = False
        self._disconnect_header_clicks()
        p = self._panel
        for sig in (p.operator_changed, p.constant_submitted, p.constant_changed,
                    p.constant_cancelled, p.text_submitted, p.text_changed,
                    p.text_cancelled, p.ignore_head_changed,
                    p.find_pick_ref_clicked):
            try:
                sig.disconnect()
            except TypeError:
                pass
        try:
            p.confirm_clicked.disconnect(self._on_find_lookup_confirmed)
        except TypeError:
            pass

    def _begin_find_output(self, step: FindOutputStep) -> None:
        self._panel.set_script_prompt(step.prompt)
        self._panel.show_find_output_panel()
        self._panel.find_output_chosen.connect(self._on_find_output)

    def _on_find_output(self, action: str) -> None:
        if not self._running:
            return
        step = self._steps[self._step_idx]
        if not isinstance(step, FindOutputStep):
            return
        self._params[step.key] = action
        try:
            self._panel.find_output_chosen.disconnect(self._on_find_output)
        except TypeError:
            pass
        self._advance_step()

    # ------------------------------------------------------------------
    # 数值校验
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_numeric_reference(cells: list[str]) -> tuple[list[int], str | None]:
        non_empty = [(i, c) for i, c in enumerate(cells) if c.strip()]
        if not non_empty:
            return [], '参考区域无数据'

        invalid = [(i, c) for i, c in non_empty
                   if not _is_numeric(c)]
        ratio = len(invalid) / len(non_empty)

        if ratio > _INVALID_RATIO_THRESHOLD:
            examples = ', '.join(f'[{v}]' for _, v in invalid[:3])
            return [], f'无效数据过多 ({len(invalid)}/{len(non_empty)}): {examples}'

        bad_idx = {i for i, _ in invalid}
        valid = [i for i in range(len(cells))
                 if i not in bad_idx and cells[i].strip()]
        return valid, None

    @staticmethod
    def _validate_find_reference(cells: list[str]) -> tuple[list[int], str | None]:
        """查找脚本参考校验：文本格=标题单位跳过（单标题豁免，>30% 报错）。

        空格已在调用处单独报错（用户设计：参考格为空 → 拒绝）。
        """
        non_empty = [(i, c) for i, c in enumerate(cells) if c.strip()]
        if not non_empty:
            return [], '参考区域无数据'
        text_idx = [i for i, c in non_empty if not _is_numeric(c)]
        if len(text_idx) > 1 and len(text_idx) / len(non_empty) > 0.3:
            return [], f'无效数据过多（标题占比 >30%，共 {len(text_idx)} 个）'
        text_set = set(text_idx)
        valid = [i for i in range(len(cells))
                 if i not in text_set and cells[i].strip()]
        return valid, None

    # ------------------------------------------------------------------
    # 步骤 4：计算元收集（列/行/常数/剪贴板，可添加多个）
    # ------------------------------------------------------------------

    def _begin_operand_input(self, step: OperandInputStep) -> None:
        self._operand_step = step
        self._operand_slots = []
        self._pending_slot = -1
        self._pick_kind = ''
        self._decimals_mode = 'auto'
        self._decimals_digits = None
        direction = self._params.get(step.direction_key, '')
        pick_kind = 'row' if '行' in direction else 'column'
        self._panel.set_script_prompt(step.prompt)
        self._panel.show_operand_slots(step.min_count, pick_kind,
                                       with_decimals=step.decimals,
                                       operator=getattr(step, 'operator', ''),
                                       fixed_count=getattr(step, 'fixed_count', 0),
                                       slot_labels=getattr(step, 'slot_labels', None))
        for _ in range(step.min_count):
            self._operand_slots.append(None)
        self._panel.operand_action.connect(self._on_operand_action)
        self._panel.operand_constant_submitted.connect(self._on_operand_constant)
        self._panel.operand_constant_cancelled.connect(self._on_operand_constant_cancelled)
        self._panel.operand_added.connect(self._on_operand_added)
        self._panel.operand_removed.connect(self._on_operand_removed)
        self._panel.decimals_mode_changed.connect(self._on_decimals_mode)
        self._panel.decimals_digits_submitted.connect(self._on_decimals_digits)
        self._panel.decimals_cancelled.connect(self._on_decimals_cancelled)
        self._panel.show_confirm_button(enabled=False)
        self._panel.confirm_clicked.connect(self._on_operands_confirmed)

    # ------------------------------------------------------------------
    # 步骤 3.5：字符串计算元（点选列/行、手动文本、剪贴板单/多文本）
    # ------------------------------------------------------------------

    def _begin_text_operand(self, step: TextOperandStep) -> None:
        self._operand_step = step
        self._text_operand_step = step
        self._operand_slots = []
        self._pending_slot = -1
        self._pick_kind = ''
        direction = self._params.get(step.direction_key, '')
        pick_kind = 'row' if '行' in direction else 'column'
        self._panel.set_script_prompt(step.prompt)
        self._panel.show_operand_slots(step.min_count, pick_kind,
                                       fixed_count=step.fixed_count,
                                       text_mode=True)
        for _ in range(step.min_count):
            self._operand_slots.append(None)
        self._panel.operand_action.connect(self._on_text_operand_action)
        self._panel.operand_constant_submitted.connect(self._on_text_operand_submitted)
        self._panel.operand_constant_cancelled.connect(self._on_operand_constant_cancelled)
        self._panel.operand_added.connect(self._on_operand_added)
        self._panel.operand_removed.connect(self._on_operand_removed)
        self._panel.show_confirm_button(enabled=False)
        self._panel.confirm_clicked.connect(self._on_text_operands_confirmed)

    _TEXT_OPERAND_ACTION_HANDLERS = {
        'clear': '_on_operand_clear',
        'column': '_on_operand_pick',
        'row': '_on_operand_pick',
        'text': '_on_text_input_start',
        'clipboard_single': '_on_text_clipboard_single',
        'clipboard_multi': '_on_text_clipboard_multi',
    }

    def _on_text_operand_action(self, index: int, action: str) -> None:
        if not self._running or self._text_operand_step is None:
            return
        handler = self._TEXT_OPERAND_ACTION_HANDLERS.get(action)
        if handler is not None:
            getattr(self, handler)(index, action)

    def _on_text_input_start(self, index: int, action: str) -> None:
        """手动输入文本：打开输入框。"""
        self._panel.show_slot_editor(index)
        self._panel.set_script_prompt('请输入文本，回车确认（Esc 取消）')

    def _on_text_operand_submitted(self, index: int, text: str) -> None:
        """手动输入文本提交：任意文本直接存储。"""
        if not self._running or self._text_operand_step is None:
            return
        display = text if text else '(空文本)'
        self._store_operand(index, {
            'kind': 'text', 'text': text, 'display': display,
            'values': [text],
        })

    def _on_text_clipboard_single(self, index: int, action: str) -> None:
        """剪贴板单文本：整个剪贴板作为一个字符串。"""
        if not self._running or self._text_operand_step is None:
            return
        text = QApplication.clipboard().text()
        if not text:
            self._panel.set_script_prompt('❌ 剪贴板为空')
            return
        self._store_operand(index, {
            'kind': 'text', 'text': text, 'display': '剪贴板单文本',
            'values': [text],
        })

    def _on_text_clipboard_multi(self, index: int, action: str) -> None:
        """剪贴板多文本：按方向切分（对行→Tab横排 / 对列→换行竖排）。"""
        if not self._running or self._text_operand_step is None:
            return
        text = QApplication.clipboard().text()
        if not text:
            self._panel.set_script_prompt('❌ 剪贴板为空')
            return
        direction = self._params.get(self._text_operand_step.direction_key, '')
        if '行' in direction:
            rows = text.replace('\r\n', '\n').replace('\r', '\n').split('\t')
        else:
            lines = text.replace('\r\n', '\n').replace('\r', '\n').split('\n')
            rows = [ln.split('\t')[0] for ln in lines]
        # 去尾部空行
        while rows and rows[-1] == '':
            rows.pop()
        if not rows:
            self._panel.set_script_prompt('❌ 剪贴板无有效内容')
            return
        display = '剪贴板多文本'
        self._store_operand(index, {
            'kind': 'text_multi', 'values': rows, 'display': display,
        })

    def _on_text_operands_confirmed(self) -> None:
        if not self._running or self._text_operand_step is None:
            return
        step = self._text_operand_step
        threshold = self._operand_threshold()
        slots = [s for s in self._operand_slots if s is not None]
        if len(slots) < threshold:
            return
        # 对齐检查：非常数/单文本计算元的数据长度必须一致
        lengths = [len(s.get('values', [])) for s in slots
                   if s['kind'] in ('column', 'row', 'text_multi')]
        if lengths and len(set(lengths)) > 1:
            self._panel.set_script_prompt(
                f'❌ 计算元未对齐（数据长度 {lengths}），请调整后重试')
            return
        data_len = lengths[0] if lengths else 1
        self._params[step.key] = {
            'slots': slots,
            'data_len': data_len,
            'has_title': False,
        }
        self._disconnect_text_operand_signals()
        self._advance_step()

    def _disconnect_text_operand_signals(self) -> None:
        self._leave_pick_mode()
        self._disconnect_quietly(self._panel.operand_action, self._on_text_operand_action)
        self._disconnect_quietly(self._panel.operand_constant_submitted,
                                 self._on_text_operand_submitted)
        self._disconnect_quietly(self._panel.operand_constant_cancelled,
                                 self._on_operand_constant_cancelled)
        self._disconnect_quietly(self._panel.operand_added, self._on_operand_added)
        self._disconnect_quietly(self._panel.operand_removed, self._on_operand_removed)
        self._disconnect_quietly(self._panel.confirm_clicked, self._on_text_operands_confirmed)

    def _on_operand_added(self) -> None:
        if self._operand_step is not None and self._operand_step.fixed_count > 0:
            return
        self._operand_slots.append(None)
        # 添加空槽位不改变"已填 ≥2"判定，无需刷新

    def _on_operand_removed(self, index: int) -> None:
        if self._operand_step is not None and self._operand_step.fixed_count > 0:
            return
        if 0 <= index < len(self._operand_slots):
            self._operand_slots.pop(index)
        # 删除槽位时退出点选模式，避免索引错乱
        self._leave_pick_mode()
        self._pending_slot = -1
        self._refresh_operand_confirm()

    # 计算元框菜单动作 → 处理方法名
    _OPERAND_ACTION_HANDLERS = {
        'clear': '_on_operand_clear',
        'column': '_on_operand_pick',
        'row': '_on_operand_pick',
        'constant': '_on_operand_constant_start',
        'clipboard': '_on_operand_clipboard',
    }

    def _on_operand_action(self, index: int, action: str) -> None:
        if not self._running or self._operand_step is None:
            return
        handler = self._OPERAND_ACTION_HANDLERS.get(action)
        if handler is not None:
            getattr(self, handler)(index, action)

    def _on_operand_clear(self, index: int, action: str) -> None:
        if 0 <= index < len(self._operand_slots):
            self._operand_slots[index] = None
        self._panel.reset_slot(index)
        self._panel.set_script_prompt(self._operand_step.prompt)
        self._refresh_operand_confirm()

    def _validate_slot_values(self, index: int, values: list[float]) -> str | None:
        """按步骤的 slot_validators 校验某槽位的数值列表；无校验器返回 None。

        用 getattr 防御：TextOperandStep 等无 slot_validators 属性的步骤
        安全返回 None（不做槽位级校验）。
        """
        validators = getattr(self._operand_step, 'slot_validators', None)
        if self._operand_step is None or not validators:
            return None
        if not (0 <= index < len(validators)):
            return None
        validator = validators[index]
        if validator is None:
            return None
        return validator(values)

    def _on_operand_pick(self, index: int, action: str) -> None:
        self._pending_slot = index
        self._enter_pick_mode(action)

    def _on_operand_constant_start(self, index: int, action: str) -> None:
        self._panel.show_slot_editor(index)
        self._panel.set_script_prompt('请输入常数，回车确认（Esc 取消）')

    def _on_operand_clipboard(self, index: int, action: str) -> None:
        self._pick_clipboard(index)

    def _enter_pick_mode(self, kind: str) -> None:
        """进入"点列头/行头"模式，等待用户点选。"""
        self._leave_pick_mode()
        self._pick_kind = kind
        if kind == 'column':
            self._grid.horizontalHeader().sectionClicked.connect(self._on_pick_column)
            self._panel.set_script_prompt('请点击列头选择计算元列')
        else:
            self._grid.verticalHeader().sectionClicked.connect(self._on_pick_row)
            self._panel.set_script_prompt('请点击行头选择计算元行')

    def _leave_pick_mode(self) -> None:
        self._disconnect_quietly(self._grid.horizontalHeader().sectionClicked,
                                 self._on_pick_column)
        self._disconnect_quietly(self._grid.verticalHeader().sectionClicked,
                                 self._on_pick_row)
        self._pick_kind = ''

    def _on_pick_column(self, section: int) -> None:
        if not self._running or self._pending_slot < 0:
            return
        if self._text_operand_step is not None:
            # 文本模式：限定在框选区域范围内
            rng = self._params.get('range')
            if rng is None:
                self._leave_pick_mode()
                self._panel.set_script_prompt('❌ 未检测到框选区域，请先框选')
                return
            r1, c1, r2, c2 = rng
            if section < c1 or section > c2:
                self._leave_pick_mode()
                self._panel.set_script_prompt(
                    f'❌ 列 {SpreadsheetModel.col_letter(section)} 不在框选区域内')
                return
            cells = [self._model.value(r, section) for r in range(r1, r2 + 1)]
            values, err = self._parse_text_cells(cells)
            title, title_idx, decimals = None, 0, [0] * len(values)
        else:
            cells = [self._model.value(r, section) for r in range(self._model.row_total)]
            title, title_idx, values, decimals, err = self._parse_numeric_cells(cells)
        self._leave_pick_mode()
        if err:
            self._panel.set_script_prompt(
                f'❌ 列 {SpreadsheetModel.col_letter(section)}：{err}')
            return
        verr = self._validate_slot_values(self._pending_slot, values)
        if verr:
            self._panel.set_script_prompt(
                f'❌ 列 {SpreadsheetModel.col_letter(section)}：{verr}')
            return
        display = title or f'列{SpreadsheetModel.col_letter(section)}'
        self._store_operand(self._pending_slot, {
            'kind': 'column', 'index': section, 'title': title,
            'title_idx': title_idx, 'display': display, 'values': values,
            'decimals': decimals,
        })

    def _on_pick_row(self, section: int) -> None:
        if not self._running or self._pending_slot < 0:
            return
        if self._text_operand_step is not None:
            # 文本模式：限定在框选区域范围内
            rng = self._params.get('range')
            if rng is None:
                self._leave_pick_mode()
                self._panel.set_script_prompt('❌ 未检测到框选区域，请先框选')
                return
            r1, c1, r2, c2 = rng
            if section < r1 or section > r2:
                self._leave_pick_mode()
                self._panel.set_script_prompt(
                    f'❌ 行 {section + 1} 不在框选区域内')
                return
            cells = [self._model.value(section, c) for c in range(c1, c2 + 1)]
            values, err = self._parse_text_cells(cells)
            title, title_idx, decimals = None, 0, [0] * len(values)
        else:
            cells = [self._model.value(section, c) for c in range(self._model.col_total)]
            title, title_idx, values, decimals, err = self._parse_numeric_cells(cells)
        self._leave_pick_mode()
        if err:
            self._panel.set_script_prompt(f'❌ 行 {section + 1}：{err}')
            return
        verr = self._validate_slot_values(self._pending_slot, values)
        if verr:
            self._panel.set_script_prompt(f'❌ 行 {section + 1}：{verr}')
            return
        display = title or f'行{section + 1}'
        self._store_operand(self._pending_slot, {
            'kind': 'row', 'index': section, 'title': title,
            'title_idx': title_idx, 'display': display, 'values': values,
            'decimals': decimals,
        })

    def _pick_clipboard(self, index: int) -> None:
        text = QApplication.clipboard().text()
        if not text:
            self._panel.set_script_prompt('❌ 剪贴板为空')
            return
        direction = self._params.get(self._operand_step.direction_key, '') \
            if self._operand_step else ''
        # 剪贴板按运算方向切分：对行处理 → Tab 横排（每列一个值）；
        # 对列处理 → 换行竖排（每行一个值），与计算元数据形态保持一致
        if '行' in direction:
            rows = text.replace('\r\n', '\n').replace('\r', '\n').split('\t')
        else:
            lines = text.replace('\r\n', '\n').replace('\r', '\n').split('\n')
            # 每行取第一个 Tab 字段（兼容从表格复制的列）
            rows = [ln.split('\t')[0] for ln in lines]
        title, title_idx, values, decimals, err = self._parse_numeric_cells(rows)
        if err:
            self._panel.set_script_prompt(f'❌ 剪贴板：{err}')
            return
        verr = self._validate_slot_values(index, values)
        if verr:
            self._panel.set_script_prompt(f'❌ 剪贴板：{verr}')
            return
        display = title or ('粘贴行' if '行' in direction else '粘贴列')
        self._store_operand(index, {
            'kind': 'clipboard', 'title': title, 'title_idx': title_idx,
            'display': display, 'values': values, 'decimals': decimals,
        })

    def _store_operand(self, index: int, data: dict) -> None:
        if 0 <= index < len(self._operand_slots):
            self._operand_slots[index] = data
        self._panel.set_slot_display(index, data['display'])
        if self._operand_step is not None:
            self._panel.set_script_prompt(self._operand_step.prompt)
        self._refresh_operand_confirm()

    def _operand_threshold(self) -> int:
        """确定按钮的已填槽位数阈值：固定槽位=全部填满，否则 2 个。"""
        if self._operand_step is not None and self._operand_step.fixed_count > 0:
            return self._operand_step.fixed_count
        return 2

    def _refresh_operand_confirm(self) -> None:
        filled = sum(1 for s in self._operand_slots if s is not None)
        self._panel.set_confirm_enabled(filled >= self._operand_threshold())

    def _on_operand_constant(self, index: int, text: str) -> None:
        if not self._running:
            return
        try:
            val = float(text)
        except ValueError:
            self._panel.set_script_prompt('❌ 常数无效，请输入数字')
            self._panel.reset_slot(index)
            self._refresh_operand_confirm()
            return
        verr = self._validate_slot_values(index, [val])
        if verr:
            self._panel.set_script_prompt(f'❌ {verr}')
            self._panel.reset_slot(index)
            self._refresh_operand_confirm()
            return
        self._store_operand(index, {
            'kind': 'constant', 'value': val, 'display': f'{val:g}',
            'title': None, 'title_idx': 0, 'values': [],
            'decimals': [_count_decimals(text)],
        })

    def _on_operand_constant_cancelled(self, index: int) -> None:
        """用户 Esc 取消常数输入：恢复步骤主提示。"""
        if not self._running or self._operand_step is None:
            return
        self._panel.set_script_prompt(self._operand_step.prompt)

    # --- 保留小数位数 ---

    def _on_decimals_mode(self, mode: str) -> None:
        """用户选择「默认（自动）」或「手动输入位数」。"""
        if not self._running or self._operand_step is None:
            return
        if mode == 'manual':
            self._panel.show_decimals_editor()
            self._panel.set_script_prompt('请输入保留小数位数（0-10），回车确认（Esc 取消）')
        else:
            self._decimals_mode = 'auto'
            self._decimals_digits = None
            self._panel.set_decimals_display('保留位数：默认（自动）')
            self._panel.set_script_prompt(self._operand_step.prompt)

    def _on_decimals_digits(self, text: str) -> None:
        """手动位数提交：校验 0-10 整数，合格后记录并恢复提示；失败报错并恢复默认。"""
        if not self._running or self._operand_step is None:
            return
        text = text.strip()
        if not text.isdigit():
            self._panel.set_script_prompt('❌ 位数无效，请输入 0-10 的整数')
            self._decimals_mode = 'auto'
            self._decimals_digits = None
            self._panel.set_decimals_display('保留位数：默认（自动）')
            return
        n = int(text)
        if n > 10:
            self._panel.set_script_prompt('❌ 位数超出范围（0-10），请重新输入')
            self._decimals_mode = 'auto'
            self._decimals_digits = None
            self._panel.set_decimals_display('保留位数：默认（自动）')
            return
        self._decimals_mode = 'manual'
        self._decimals_digits = n
        self._panel.set_decimals_display(f'保留位数：{n} 位')
        self._panel.set_script_prompt(self._operand_step.prompt)

    def _on_decimals_cancelled(self) -> None:
        """用户 Esc 取消手动位数输入：恢复步骤主提示。"""
        if not self._running or self._operand_step is None:
            return
        self._panel.set_script_prompt(self._operand_step.prompt)

    def _on_operands_confirmed(self) -> None:
        if not self._running or self._operand_step is None:
            return
        threshold = self._operand_threshold()
        slots = [s for s in self._operand_slots if s is not None]
        if len(slots) < threshold:
            return  # 按钮未亮，防御
        # 全局对齐检查：非常数计算元的数据长度必须一致
        lengths = [len(s.get('values', [])) for s in slots if s['kind'] != 'constant']
        if lengths and len(set(lengths)) > 1:
            self._panel.set_script_prompt(
                f'❌ 计算元未对齐（数据长度 {lengths}），请调整后重试')
            return
        data_len = lengths[0] if lengths else 1
        first_data = next((s for s in slots if s['kind'] != 'constant'), None)
        self._params[self._operand_step.key] = {
            'slots': slots,
            'data_len': data_len,
            'title_idx': first_data.get('title_idx', 0) if first_data else 0,
            'has_title': any(s.get('title') is not None for s in slots),
            'decimals': {
                'mode': self._decimals_mode,
                'digits': (self._decimals_digits
                           if self._decimals_mode == 'manual' else None),
            },
        }
        self._disconnect_operand_signals()
        self._advance_step()

    def _disconnect_operand_signals(self) -> None:
        self._leave_pick_mode()
        self._disconnect_quietly(self._panel.operand_action, self._on_operand_action)
        self._disconnect_quietly(self._panel.operand_constant_submitted,
                                 self._on_operand_constant)
        self._disconnect_quietly(self._panel.operand_constant_cancelled,
                                 self._on_operand_constant_cancelled)
        self._disconnect_quietly(self._panel.operand_added, self._on_operand_added)
        self._disconnect_quietly(self._panel.operand_removed, self._on_operand_removed)
        self._disconnect_quietly(self._panel.decimals_mode_changed, self._on_decimals_mode)
        self._disconnect_quietly(self._panel.decimals_digits_submitted,
                                 self._on_decimals_digits)
        self._disconnect_quietly(self._panel.decimals_cancelled, self._on_decimals_cancelled)
        self._disconnect_quietly(self._panel.confirm_clicked, self._on_operands_confirmed)

    # ------------------------------------------------------------------
    # 步骤 4.5：三角函数（函数下拉 + 单计算元 + 角度单位）
    # ------------------------------------------------------------------

    def _begin_trig_function(self, step: TrigFunctionStep) -> None:
        """三角函数步骤：渲染函数下拉/单位/单计算元/保留小数，连接信号。

        复用 OperandInputStep 的计算元槽位逻辑（self._operand_step = step），
        但确认走 _on_trig_confirmed 以先做定义域校验。
        """
        self._trig_step = step
        self._operand_step = step  # 复用计算元槽位逻辑
        self._operand_slots = []
        self._pending_slot = -1
        self._decimals_mode = 'auto'
        self._decimals_digits = None
        direction = self._params.get(step.direction_key, '')
        pick_kind = 'row' if '行' in direction else 'column'
        self._trig_function = step.functions[0] if step.functions else ''

        self._panel.set_script_prompt(step.prompt)
        self._panel.show_trig_function_panel(
            step.functions, pick_kind, units=step.units,
            with_decimals=step.decimals,
        )
        self._operand_slots.append(None)  # 单个计算元槽位
        # 计算元 / 保留小数信号（复用）
        self._panel.operand_action.connect(self._on_operand_action)
        self._panel.operand_constant_submitted.connect(self._on_operand_constant)
        self._panel.operand_constant_cancelled.connect(self._on_operand_constant_cancelled)
        self._panel.decimals_mode_changed.connect(self._on_decimals_mode)
        self._panel.decimals_digits_submitted.connect(self._on_decimals_digits)
        self._panel.decimals_cancelled.connect(self._on_decimals_cancelled)
        # 函数 / 单位信号
        self._panel.function_changed.connect(self._on_trig_function_changed)
        self._panel.unit_changed.connect(self._on_trig_unit_changed)
        # 确认
        self._panel.show_confirm_button(enabled=False)
        self._panel.confirm_clicked.connect(self._on_trig_confirmed)

    def _on_trig_function_changed(self, text: str) -> None:
        if not self._running:
            return
        self._trig_function = text

    def _on_trig_unit_changed(self, text: str) -> None:
        # 单位变化不影响确定可用性，仅记录（unit 在 params 存 text）
        pass

    def _on_trig_confirmed(self) -> None:
        """确认：先做定义域校验，通过才存储并推进。"""
        if not self._running or self._trig_step is None:
            return
        step = self._trig_step
        slots = [s for s in self._operand_slots if s is not None]
        if len(slots) < self._operand_threshold():
            return  # 按钮未亮，防御

        function = self._trig_function
        unit = self._panel.get_unit() or (step.units[0] if step.units else '弧度制')
        data_slot = slots[0]

        # 计算元数据长度（单计算元，无需对齐；常数则 data_len=1 由 run 广播）
        if data_slot['kind'] == 'constant':
            data_len = 1
        else:
            data_len = len(data_slot['values'])

        # 定义域校验：遍历计算元每个值，结合函数/单位
        err = self._validate_trig_domain(step, function, unit,
                                         data_slot, data_len)
        if err:
            self._panel.set_script_prompt(f'❌ {err}')
            return

        self._params[step.key] = {
            'slots': slots,
            'data_len': data_len,
            'title_idx': data_slot.get('title_idx', 0),
            'has_title': data_slot.get('title') is not None,
            'decimals': {
                'mode': self._decimals_mode,
                'digits': (self._decimals_digits
                           if self._decimals_mode == 'manual' else None),
            },
        }
        self._params[step.function_key] = function
        self._params[step.unit_key] = unit
        # 运算方向：函数结果本身与方向无关，但输出时用（这里不额外存）
        self._disconnect_trig_signals()
        self._advance_step()

    def _validate_trig_domain(self, step: TrigFunctionStep, function: str,
                              unit: str, data_slot: dict, data_len: int) -> str | None:
        """根据函数/单位校验计算元所有值的定义域。返回错误或 None。

        规则：
        - arcsin / arccos：输入必须在 [-1, 1]（弧度/度单位对反三角无影响）；
        - 弧度下 tan/cot/sec/csc 无定义点按公式检查；
        - 角度制下把输入视为角度（0-360），tan 90°、cot 0°/180°、sec 90°、csc 0° 无定义。
        """
        import math
        if data_slot['kind'] == 'constant':
            values = [data_slot['value']]
        else:
            values = data_slot['values']

        is_deg = ('角度' in unit)
        func = function.lower().strip()

        for i, v in enumerate(values):
            if func in ('arcsin', 'arccos'):
                if v < -1 or v > 1:
                    return (f'{function}({v}) 超出定义域 [-1,1]'
                            f'（第 {i + 1} 格），拒绝')
                continue

            # sin/cos 全实数；tan/sec/cot/csc 需检查无定义点
            if is_deg:
                angle = v % 360
                if func == 'tan' and (angle % 180) == 90:
                    return f'第 {i + 1} 格：tan({v}°) 无定义，拒绝'
                if func == 'cot' and (angle % 180) == 0:
                    return f'第 {i + 1} 格：cot({v}°) 无定义，拒绝'
                if func == 'sec' and (angle % 180) == 90:
                    return f'第 {i + 1} 格：sec({v}°) 无定义，拒绝'
                if func == 'csc' and (angle % 180) == 0:
                    return f'第 {i + 1} 格：csc({v}°) 无定义，拒绝'
            else:
                # 弧度
                if func in ('tan', 'sec') and abs(math.cos(v)) < 1e-12:
                    return f'第 {i + 1} 格：{function}({v}) 无定义，拒绝'
                if func in ('cot', 'csc') and abs(math.sin(v)) < 1e-12:
                    return f'第 {i + 1} 格：{function}({v}) 无定义，拒绝'
        return None

    def _disconnect_trig_signals(self) -> None:
        self._leave_pick_mode()
        self._disconnect_quietly(self._panel.operand_action, self._on_operand_action)
        self._disconnect_quietly(self._panel.operand_constant_submitted,
                                 self._on_operand_constant)
        self._disconnect_quietly(self._panel.operand_constant_cancelled,
                                 self._on_operand_constant_cancelled)
        self._disconnect_quietly(self._panel.decimals_mode_changed, self._on_decimals_mode)
        self._disconnect_quietly(self._panel.decimals_digits_submitted,
                                 self._on_decimals_digits)
        self._disconnect_quietly(self._panel.decimals_cancelled, self._on_decimals_cancelled)
        self._disconnect_quietly(self._panel.function_changed, self._on_trig_function_changed)
        self._disconnect_quietly(self._panel.unit_changed, self._on_trig_unit_changed)
        self._disconnect_quietly(self._panel.confirm_clicked, self._on_trig_confirmed)

    # ------------------------------------------------------------------
    # 步骤 5：选择结果输出位置（剪贴板 / 点选输出列或行）
    # ------------------------------------------------------------------

    def _begin_output_target(self, step: OutputTargetStep) -> None:
        self._output_step = step
        self._panel.set_script_prompt(step.prompt)
        self._panel.show_output_buttons()
        self._panel.output_clipboard.connect(self._on_output_clipboard)
        self._panel.output_pick.connect(self._on_output_pick)

    def _on_output_clipboard(self) -> None:
        if not self._running or self._output_step is None:
            return
        self._params[self._output_step.key] = {'target': 'clipboard'}
        self._disconnect_output_signals()
        self._execute()

    def _on_output_pick(self) -> None:
        if not self._running or self._output_step is None:
            return
        direction = self._params.get(self._output_step.direction_key, '')
        # 统计类脚本 invert=True：输出轴与处理单位垂直（对列处理 → 输出行）
        pick_row = ('行' in direction) != bool(
            getattr(self._output_step, 'invert', False))
        if pick_row:
            self._grid.verticalHeader().sectionClicked.connect(self._on_pick_output_row)
            self._panel.set_script_prompt('请点击行头选择输出行')
        else:
            self._grid.horizontalHeader().sectionClicked.connect(self._on_pick_output_col)
            self._panel.set_script_prompt('请点击列头选择输出列')

    def _on_pick_output_col(self, section: int) -> None:
        if not self._running or self._output_step is None:
            return
        self._params[self._output_step.key] = {'target': 'column', 'index': section}
        self._finish_output_pick()

    def _on_pick_output_row(self, section: int) -> None:
        if not self._running or self._output_step is None:
            return
        self._params[self._output_step.key] = {'target': 'row', 'index': section}
        self._finish_output_pick()

    def _finish_output_pick(self) -> None:
        self._disconnect_quietly(self._grid.horizontalHeader().sectionClicked,
                                 self._on_pick_output_col)
        self._disconnect_quietly(self._grid.verticalHeader().sectionClicked,
                                 self._on_pick_output_row)
        self._disconnect_output_signals()
        self._execute()

    def _disconnect_output_signals(self) -> None:
        self._disconnect_quietly(self._panel.output_clipboard, self._on_output_clipboard)
        self._disconnect_quietly(self._panel.output_pick, self._on_output_pick)

    # ------------------------------------------------------------------
    # 计算元识别
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_text_cells(cells: list[str]) -> tuple[list[str], str | None]:
        """识别一列/一行字符串数据：返回 (文本列表, 错误)。

        规则（字符串运算）：
        - 尾部空格忽略；前导空格跳过；
        - 数据区空格 → 空文本 ''（占位，不报错）；
        - 数字/文字一律当字符串，不区分。
        """
        raw = [str(c) for c in cells]
        while raw and raw[-1].strip() == '':
            raw.pop()
        if not raw:
            return [], '所选内容为空'
        start = 0
        while start < len(raw) and raw[start].strip() == '':
            start += 1
        values = [c.strip() for c in raw[start:]]
        return values, None

    @staticmethod
    def _parse_numeric_cells(cells: list[str]) -> tuple[str | None, int, list[float], list[int], str | None]:
        """识别一列/一行数据：返回 (标题, 标题索引, 数值列表, 逐位小数位数列表, 错误)。

        规则（数学运算）：
        - 尾部空格忽略；前导空格跳过；
        - 数据区空格 → 报错拒绝；
        - 含文字格 → 识别为标题（第一个文字格作为显示标题）；
        - 标题/文字格占比 >30% → 报错拒绝。

        decimals 与 values 一一对齐：从原始文本推导小数位数
        （'2.50' → 2 位，先转 float 会丢失末尾 0）。
        """
        raw = [str(c) for c in cells]
        while raw and raw[-1].strip() == '':
            raw.pop()
        if not raw:
            return None, 0, [], [], '所选内容为空'
        start = 0
        while start < len(raw) and raw[start].strip() == '':
            start += 1
        title: str | None = None
        title_idx = 0
        values: list[float] = []
        decimals: list[int] = []
        text_count = 0
        for i in range(start, len(raw)):
            v = raw[i].strip()
            if v == '':
                return None, 0, [], [], f'第 {i + 1} 格为空，拒绝'
            try:
                values.append(float(v))
            except ValueError:
                text_count += 1
                if title is None:
                    title = v
                    title_idx = i
                continue
            decimals.append(_count_decimals(v))
        total = len(raw) - start
        # 白名单：仅 1 个标题格（文字格）时豁免阈值 —— 单标题是正常表格结构；
        # 2 个及以上标题格才按 30% 占比判定
        if text_count > 1 and total > 0 and text_count / total > _TITLE_RATIO_THRESHOLD:
            return None, 0, [], [], f'标题/文字格过多 ({text_count}/{total})'
        return title, title_idx, values, decimals, None

    @staticmethod
    def _recognize_cells(cells: list[str]) -> tuple[str | None, int, list[float], str | None]:
        """兼容旧签名：返回 (标题, 标题索引, 数值列表, 错误)，丢弃小数位数。"""
        title, title_idx, values, _, err = ScriptController._parse_numeric_cells(cells)
        return title, title_idx, values, err

    # ------------------------------------------------------------------
    # 执行
    # ------------------------------------------------------------------

    def _execute(self) -> None:
        if self._script is None:
            return
        self._executing = True
        self._push_undo_snapshot()
        self._panel.clear_script_panel()
        self._panel.set_script_prompt('⏳ 正在执行...')
        QApplication.processEvents()  # 立即重绘，让「正在执行」在长脚本运行时可见

        try:
            start = time.perf_counter()
            error = self._script.run(self._model, self._params)
            elapsed = time.perf_counter() - start
            if error:
                self._panel.set_script_prompt(f'❌ {error}')
            else:
                loc = self._describe_output()
                if not loc:
                    loc = self._describe_custom_calc_output()
                suffix = f'，结果{loc}' if loc else ''
                # 查找脚本「输出到提示栏」：完成提示额外显示符合的标题
                find_extra = self._params.get('find_results')
                if find_extra:
                    suffix += f'，符合要求的标题：{find_extra}'
                self._panel.set_script_prompt(
                    f'✅ {self._script.name} 完成{suffix} ({elapsed:.1f}s)')
        except Exception as e:
            self._panel.set_script_prompt(f'❌ 脚本异常: {e}')
        finally:
            self._cleanup()

    def _push_undo_snapshot(self) -> None:
        from views.main_window import MainWindow
        w = self._grid
        while w:
            if isinstance(w, MainWindow):
                ctrl = getattr(w, '_sheet_ctrl', None)
                if ctrl:
                    ctrl._push_snapshot()
                break
            w = w.parent()

    # ------------------------------------------------------------------
    # 辅助
    # ------------------------------------------------------------------

    def _resolve_prompt(self, step: SelectHeaderStep) -> str:
        p = step.prompt
        unit = self._params.get('unit', '')
        is_row = '行' in unit
        if '{ref_label}' in p:
            p = p.replace('{ref_label}', '列' if is_row else '行')
        if '{unit}' in p:
            p = p.replace('{unit}', unit)
        return p

    def _describe_output(self) -> str:
        """根据 params 中的输出目标生成结果位置描述。"""
        out = None
        if self._output_step is not None:
            out = self._params.get(self._output_step.key)
        if not out:
            return ''
        if out.get('target') == 'clipboard':
            return '已复制到剪贴板'
        if out.get('target') == 'column':
            return f'已输出到 {SpreadsheetModel.col_letter(out["index"])} 列'
        if out.get('target') == 'row':
            return f'已输出到 第{out["index"] + 1} 行'
        return ''

    def _describe_custom_calc_output(self) -> str:
        """自定义运算：从积木树收集所有输出积木的目标，生成位置描述。"""
        step = self._custom_calc_step
        if step is None:
            return ''
        blocks = self._params.get(step.key, [])
        if not blocks:
            return ''
        from custom_calc.model import BlockType, OutputTarget
        targets = []

        def _collect(node):
            if node.type == BlockType.OUTPUT and node.output_target is not None:
                targets.append(node)
            for c in node.children:
                _collect(c)
            if node.data is not None and node.data.block is not None:
                _collect(node.data.block)

        for b in blocks:
            _collect(b)
        if not targets:
            return ''
        parts = []
        for t in targets:
            if t.output_target == OutputTarget.CLIPBOARD:
                parts.append('剪贴板')
            elif t.output_target == OutputTarget.COL:
                parts.append(f'{SpreadsheetModel.col_letter(t.output_index)}列')
            elif t.output_target == OutputTarget.ROW:
                parts.append(f'第{t.output_index + 1}行')
        return '已写入 ' + '、'.join(dict.fromkeys(parts))

    def _cleanup(self) -> None:
        self._running = False
        self._executing = False
        self._script = None
        self._steps = []
        self._step_idx = 0
        self._params = {}
        self._operand_step = None
        self._output_step = None
        self._operand_slots = []
        self._pending_slot = -1
        self._pick_kind = ''
        self._decimals_mode = 'auto'
        self._decimals_digits = None
        self._trig_step = None
        self._trig_function = ''
        self._quantile_step = None
        self._quantile_value = 'median'
        self._mode_step = None
        self._count_step = None
        self._inspect_step = None
        self._find_step = None
        self._range_ex_step = None
        self._text_operand_step = None
        self._custom_calc_step = None
        self._custom_editor = None

        self._disconnect_range()
        self._disconnect_range_ex_signals()
        self._disconnect_header_clicks()
        self._disconnect_operand_signals()
        self._disconnect_text_operand_signals()
        self._disconnect_trig_signals()
        self._disconnect_quantile_signals()
        self._disconnect_mode_signals()
        self._disconnect_count_signals()
        self._disconnect_inspect_signals()
        self._disconnect_find_lookup_signals()
        self._disconnect_custom_calc_signals()
        self._disconnect_output_signals()
        self._disconnect_quietly(self._panel.auto_select_clicked, self._on_auto_select)
        self._disconnect_quietly(self._panel.option_changed, self._on_option_changed)
        self._disconnect_quietly(self._panel.confirm_clicked, self._on_options_confirmed)
        self._disconnect_quietly(self._panel.confirm_clicked, self._on_range_confirmed)


def _is_numeric(s: str) -> bool:
    try:
        float(s)
        return True
    except ValueError:
        return False


def _count_decimals(text: str) -> int:
    """从原始文本数小数位数：'2.50' → 2；'3' → 0；'-1.25' → 2。

    注意：必须先于 float() 转换调用（float('2.50') = 2.5 会丢末尾 0）；
    科学计数法（如 '1e-3'）按展开后的十进制数数位数。
    """
    t = text.strip().lower()
    if 'e' in t:
        t = format(float(t), 'f')
    if '.' not in t:
        return 0
    return len(t.split('.', 1)[1])
