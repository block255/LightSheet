"""小数补齐控制器 — 区域选择 → 位数选择 → 执行补齐（撤销可回退）。

复用：侧栏脚本面板（提示/按钮/确定）、表格网格（点选表头/框选）、
模型（data_bounds/value/set_value）、撤销快照机制。
"""

from PyQt6.QtCore import QObject

from models.spreadsheet_model import SpreadsheetModel
from views.spreadsheet_grid import SpreadsheetGrid
from views.side_panel import SidePanel

_STEP_AREA = 'area'          # 第一步：选处理区域
_STEP_DECIMALS = 'decimals'  # 第二步：选补齐位数


class DecimalPadController(QObject):
    """管理小数补齐流程：选区域 → 选位数 → 执行。"""

    def __init__(self, model: SpreadsheetModel, grid: SpreadsheetGrid,
                 side_panel: SidePanel, push_snapshot=None):
        super().__init__()
        self._model = model
        self._grid = grid
        self._panel = side_panel
        self._push_snapshot = push_snapshot  # 外部注入的快照函数（撤销用）

        self._running = False
        self._step = ''
        self._area: tuple[int, int, int, int] | None = None  # (r1, c1, r2, c2)
        self._pick_mode = ''  # 'row' | 'col'（点选模式）
        self._decimals_mode = 'default'  # 'default' | 'custom'
        self._decimals_digits: int | None = None

    # ------------------------------------------------------------------
    # 流程控制
    # ------------------------------------------------------------------

    def set_model(self, model: SpreadsheetModel) -> None:
        """切换到另一个 sheet 的模型（多 sheet）。运行中切换则中止流程。"""
        self._model = model
        if self._running:
            self.abort()

    def start(self) -> None:
        """开始补齐流程：显示区域选择面板。"""
        if self._running:
            return
        self._running = True
        self._step = _STEP_AREA
        self._area = None
        self._pick_mode = ''
        self._decimals_mode = 'default'
        self._decimals_digits = None
        self._panel.show_script_mode()  # 切换到脚本库模式，显示脚本面板
        self._panel.set_script_prompt('选择补齐处理区域')
        self._panel.show_pad_area_panel()
        self._connect_area_signals()

    def abort(self) -> None:
        """中止补齐流程。"""
        if not self._running:
            return
        self._running = False
        self._disconnect_all()
        self._panel.clear_script_panel()

    # ------------------------------------------------------------------
    # 第一步：区域选择
    # ------------------------------------------------------------------

    def _connect_area_signals(self) -> None:
        self._panel.pad_mode_changed.connect(self._on_mode_changed)
        self._panel.option_changed.connect(self._on_area_option_changed)
        self._panel.confirm_clicked.connect(self._on_area_confirmed)

    def _on_mode_changed(self, mode: str) -> None:
        """区域模式：auto/row/col/range。"""
        if not self._running or self._step != _STEP_AREA:
            return
        self._pick_mode = ''
        if mode == '自动识别整个表格':
            self._on_auto_select()
        elif mode == '点选行':
            self._pick_mode = 'row'
            self._panel.set_script_prompt('请点击行头选择处理行')
            self._connect_pick_mode('row')
        elif mode == '点选列':
            self._pick_mode = 'col'
            self._panel.set_script_prompt('请点击列头选择处理列')
            self._connect_pick_mode('col')
        elif mode == '自行框选':
            self._pick_mode = 'range'
            self._panel.set_script_prompt('请在表格中框选处理区域')
            # 监听选区变化，正确识别后亮确定
            self._grid.selectionModel().selectionChanged.connect(
                self._on_range_selected)

    def _on_auto_select(self) -> None:
        """自动识别整个表格数据区域。"""
        bounds = self._model.data_bounds()
        if bounds is None:
            self._panel.set_script_prompt('❌ 表格为空，无法自动识别')
            return
        r1, c1, r2, c2 = bounds
        self._grid.set_selection_range(r1, c1, r2, c2)
        self._area = bounds
        self._panel.set_script_prompt(
            f'已自动识别 {r2 - r1 + 1} 行 × {c2 - c1 + 1} 列，点「确定」继续')
        self._panel.set_confirm_enabled(True)

    def _on_pick_row(self, section: int) -> None:
        if not self._running or self._step != _STEP_AREA or self._pick_mode != 'row':
            return
        # 处理行 = 该行所有有内容的列范围
        c1, c2 = self._row_content_cols(section)
        if c1 is None:
            self._panel.set_script_prompt(f'❌ 第 {section + 1} 行无内容')
            return
        self._area = (section, c1, section, c2)
        self._disconnect_pick_mode()
        self._panel.set_script_prompt(f'已选择第 {section + 1} 行，点「确定」继续')
        self._panel.set_confirm_enabled(True)

    def _on_pick_col(self, section: int) -> None:
        if not self._running or self._step != _STEP_AREA or self._pick_mode != 'col':
            return
        r1, r2 = self._col_content_rows(section)
        if r1 is None:
            self._panel.set_script_prompt(f'❌ 列 {section + 1} 无内容')
            return
        self._area = (r1, section, r2, section)
        self._disconnect_pick_mode()
        self._panel.set_script_prompt(f'已选择第 {section + 1} 列，点「确定」继续')
        self._panel.set_confirm_enabled(True)

    def _on_range_selected(self) -> None:
        """自行框选：正确识别框选区域后亮确定。"""
        if not self._running or self._step != _STEP_AREA or self._pick_mode != 'range':
            return
        rng = self._grid.get_selection_range()
        if rng is None:
            self._panel.set_confirm_enabled(False)
            return
        r1, c1, r2, c2 = rng
        # 校验区域内有内容
        has_data = any(
            self._model.value(r, c).strip() != ''
            for r in range(r1, r2 + 1) for c in range(c1, c2 + 1))
        if not has_data:
            self._panel.set_script_prompt('❌ 框选区域无内容')
            self._panel.set_confirm_enabled(False)
            return
        self._area = rng
        self._panel.set_script_prompt(
            f'已框选 {r2 - r1 + 1} 行 × {c2 - c1 + 1} 列，点「确定」继续')
        self._panel.set_confirm_enabled(True)

    def _on_area_option_changed(self, key: str, value: str) -> None:
        if not self._running or key != 'pad_mode':
            return
        # 互斥按钮切换：重新进入对应模式
        self._disconnect_pick_mode()
        self._disconnect_quietly(self._grid.selectionModel().selectionChanged,
                                 self._on_range_selected)
        self._area = None
        self._panel.set_confirm_enabled(False)
        self._on_mode_changed(value)

    def _on_area_confirmed(self) -> None:
        if not self._running or self._step != _STEP_AREA or self._area is None:
            return
        self._disconnect_area_signals()
        # 进入第二步：位数选择
        self._step = _STEP_DECIMALS
        self._panel.set_script_prompt('选择补齐小数位数')
        self._panel.show_pad_decimals_panel()
        self._panel.pad_decimals_mode_changed.connect(self._on_decimals_mode)
        self._panel.pad_decimals_value_submitted.connect(self._on_decimals_value)
        self._panel.pad_decimals_cancelled.connect(self._on_decimals_cancel)
        self._panel.confirm_clicked.connect(self._on_decimals_confirmed)

    # ------------------------------------------------------------------
    # 第二步：位数选择
    # ------------------------------------------------------------------

    def _on_decimals_mode(self, mode: str) -> None:
        """位数模式：'default' 或 'custom'。"""
        if not self._running or self._step != _STEP_DECIMALS:
            return
        if mode == 'custom':
            self._panel.show_pad_decimals_editor()
            self._panel.set_script_prompt('请输入补齐位数（0-10 整数），回车确认（Esc 取消）')
            self._refresh_decimals_confirm()  # 编辑中 → 确定禁用
        else:
            self._decimals_mode = 'default'
            self._decimals_digits = None
            self._panel.reset_pad_decimals()
            self._panel.set_pad_decimals_value('default')
            self._panel.set_script_prompt('选择补齐小数位数')
            self._refresh_decimals_confirm()

    def _on_decimals_value(self, text: str) -> None:
        """自定义位数提交：校验 0-10 整数。"""
        if not self._running or self._step != _STEP_DECIMALS:
            return
        text = text.strip()
        if not text.isdigit():
            self._panel.set_script_prompt('❌ 位数无效，请输入 0-10 的整数（Esc 取消）')
            return
        n = int(text)
        if n > 10:
            self._panel.set_script_prompt('❌ 位数超出范围（0-10），请重新输入（Esc 取消）')
            return
        self._decimals_mode = 'custom'
        self._decimals_digits = n
        self._panel.set_pad_decimals_display(f'自定义 {n} 位')
        self._panel.set_pad_decimals_value(str(n))
        self._panel.set_script_prompt('选择补齐小数位数')
        self._refresh_decimals_confirm()

    def _on_decimals_cancel(self) -> None:
        if not self._running or self._step != _STEP_DECIMALS:
            return
        self._panel.set_script_prompt('选择补齐小数位数')

    def _refresh_decimals_confirm(self) -> None:
        ready = self._panel.pad_decimals_ready()
        self._panel.set_confirm_enabled(ready)

    def _on_decimals_confirmed(self) -> None:
        if not self._running or self._step != _STEP_DECIMALS or self._area is None:
            return
        if not self._panel.pad_decimals_ready():
            return
        self._execute()
        self.abort()

    # ------------------------------------------------------------------
    # 执行补齐
    # ------------------------------------------------------------------

    def _execute(self) -> None:
        """对区域内纯数据格补齐小数位数；含字符的跳过；支持撤销。"""
        r1, c1, r2, c2 = self._area
        # 计算目标位数：默认 = 区域内最大小数位数；自定义 = 用户输入
        if self._decimals_mode == 'custom':
            target = self._decimals_digits
        else:
            target = self._max_decimals_in_area(r1, c1, r2, c2)
        if target is None:
            self._panel.set_script_prompt('❌ 区域内无纯数据格，未执行补齐')
            return
        # 撤销快照
        if self._push_snapshot is not None:
            self._push_snapshot()
        count = 0
        for r in range(r1, r2 + 1):
            for c in range(c1, c2 + 1):
                v = self._model.value(r, c).strip()
                if v == '':
                    continue
                try:
                    num = float(v)
                except ValueError:
                    continue  # 含字符 → 跳过
                padded = f'{num:.{target}f}'
                if self._model.value(r, c) != padded:
                    self._model.set_value(r, c, padded)
                    count += 1
        self._panel.set_script_prompt(
            f'✅ 补齐完成：处理 {count} 个纯数据格，统一到 {target} 位小数')

    def _max_decimals_in_area(self, r1, c1, r2, c2) -> int | None:
        """区域内纯数据格的最大小数位数；无纯数据格返回 None。"""
        max_d = -1
        found = False
        for r in range(r1, r2 + 1):
            for c in range(c1, c2 + 1):
                v = self._model.value(r, c).strip()
                if v == '':
                    continue
                try:
                    float(v)
                except ValueError:
                    continue
                found = True
                d = self._count_dec(v)
                if d > max_d:
                    max_d = d
        return max_d if found else None

    @staticmethod
    def _count_dec(text: str) -> int:
        t = text.strip()
        if 'e' in t.lower():
            t = format(float(t), 'f')
        if '.' not in t:
            return 0
        return len(t.split('.', 1)[1])

    # ------------------------------------------------------------------
    # 工具
    # ------------------------------------------------------------------

    def _row_content_cols(self, row: int) -> tuple[int | None, int | None]:
        cols = [c for c in range(self._model.col_total)
                if self._model.value(row, c).strip() != '']
        return (min(cols), max(cols)) if cols else (None, None)

    def _col_content_rows(self, col: int) -> tuple[int | None, int | None]:
        rows = [r for r in range(self._model.row_total)
                if self._model.value(r, col).strip() != '']
        return (min(rows), max(rows)) if rows else (None, None)

    def _connect_pick_mode(self, kind: str) -> None:
        if kind == 'row':
            self._grid.verticalHeader().sectionClicked.connect(self._on_pick_row)
        else:
            self._grid.horizontalHeader().sectionClicked.connect(self._on_pick_col)

    def _disconnect_pick_mode(self) -> None:
        self._disconnect_quietly(self._grid.verticalHeader().sectionClicked,
                                 self._on_pick_row)
        self._disconnect_quietly(self._grid.horizontalHeader().sectionClicked,
                                 self._on_pick_col)

    def _disconnect_area_signals(self) -> None:
        self._disconnect_quietly(self._panel.pad_mode_changed, self._on_mode_changed)
        self._disconnect_quietly(self._panel.option_changed, self._on_area_option_changed)
        self._disconnect_quietly(self._panel.confirm_clicked, self._on_area_confirmed)
        self._disconnect_pick_mode()
        self._disconnect_quietly(self._grid.selectionModel().selectionChanged,
                                 self._on_range_selected)

    def _disconnect_all(self) -> None:
        self._disconnect_area_signals()
        self._disconnect_quietly(self._panel.pad_decimals_mode_changed,
                                 self._on_decimals_mode)
        self._disconnect_quietly(self._panel.pad_decimals_value_submitted,
                                 self._on_decimals_value)
        self._disconnect_quietly(self._panel.pad_decimals_cancelled,
                                 self._on_decimals_cancel)
        self._disconnect_quietly(self._panel.confirm_clicked, self._on_decimals_confirmed)

    @staticmethod
    def _disconnect_quietly(signal, slot) -> None:
        try:
            signal.disconnect(slot)
        except TypeError:
            pass
