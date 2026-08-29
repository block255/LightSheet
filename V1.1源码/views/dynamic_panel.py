"""动态脚本面板 — 弹窗：开关 + 脚本/公式格列表（两态显示）+ 右键菜单。

对应设计（动态脚本 设计架构.md）：
- 开关：仅 xlsx 可切换；csv/txt 强制关闭（禁用）
- 列表：一行摘要（截断）+ 悬停/选中展开完整配置
- 右键：移除 / 上移 / 下移（脚本条目与公式格条目统一）
- ⚠️ 标记：输出区与已有脚本重叠
- 公式格条目：[公式格] 单元格 =公式（展开详情：公式全文/引用/输出）；
  右键同脚本（移除=删扩展区条目，保存后该格变普通值；上移/下移=扩展区调序）
"""
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QMenu, QCheckBox, QSpinBox,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QShortcut, QKeySequence

from controllers.dynamic_controller import (
    DynamicController, regions_overlap, detect_cycle_entry_ids,
)


class DynamicPanel(QDialog):
    """动态脚本模式操作面板。"""

    def __init__(self, controller: DynamicController, parent=None):
        super().__init__(parent)
        self._dc = controller
        sheet = getattr(controller, '_current_sheet', '') or ''
        self.setWindowTitle(f'动态脚本模式 — {sheet}' if sheet
                            else '动态脚本模式')
        self.resize(460, 380)

        lay = QVBoxLayout(self)

        # ---- 顶部：开关 + 迭代次数 ----
        top = QHBoxLayout()
        self._switch = QCheckBox('动态脚本模式（仅 xlsx）')
        self._switch.setChecked(controller.enabled)
        self._switch.setEnabled(controller.is_xlsx)
        self._switch.toggled.connect(self._on_toggle)
        top.addWidget(self._switch)
        top.addSpacing(10)
        top.addWidget(QLabel('迭代:'))
        self._iter_spin = QSpinBox()
        self._iter_spin.setRange(1, 100)   # 系统上限 100（对齐 Excel 默认最多迭代数）
        self._iter_spin.setValue(controller.iterations)
        self._iter_spin.valueChanged.connect(self._on_iterations_changed)
        top.addWidget(self._iter_spin)
        top.addStretch(1)
        self._hint = QLabel('')
        self._hint.setStyleSheet('color: #888; font-size: 11px;')
        top.addWidget(self._hint)
        lay.addLayout(top)

        # 循环引用警告条（对齐 Excel：循环不报错，警告提示 + 蓝色箭头心智）
        self._cycle_warn = QLabel('')
        self._cycle_warn.setStyleSheet(
            'color: #b00; font-size: 11px; padding: 4px 6px;'
            'background: #fdeaea; border-radius: 3px;')
        self._cycle_warn.setWordWrap(True)
        self._cycle_warn.hide()
        lay.addWidget(self._cycle_warn)

        desc = QLabel('开启后：成功运行的脚本写入列表；修改被引用格子后自动重放。')
        desc.setWordWrap(True)
        lay.addWidget(desc)

        # ---- 列表 ----
        self._list = QListWidget(self)
        self._list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self._list.itemClicked.connect(self._on_item_clicked)
        # 右键菜单：CustomContextMenu 政策，列表自行处理（不传给 dialog）
        self._list.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu)
        self._list.customContextMenuRequested.connect(
            self._on_list_context_menu)
        lay.addWidget(self._list, 1)

        # 底部说明
        tip = QLabel('点击条目展开/收起详情；右键可：移除 / 上移 / 下移（顺序 = 依赖序）；'
                     'Ctrl+Z/Y 撤销/重做（面板独立快照，与表格撤销分离）')
        tip.setStyleSheet('color: #888; font-size: 11px;')
        tip.setWordWrap(True)
        lay.addWidget(tip)

        # ---- 面板独立撤销（会话级，参照积木编辑器 JSON 快照栈模式）----
        self._undo_stack: list = []
        self._redo_stack: list = []
        QShortcut(QKeySequence('Ctrl+Z'), self, activated=self._undo)
        QShortcut(QKeySequence('Ctrl+Y'), self, activated=self._redo)
        QShortcut(QKeySequence('Ctrl+Shift+Z'), self, activated=self._redo)

        self._refresh()
        self._apply_mode_hint()

    # ------------------------------------------------------------------
    # 开关
    # ------------------------------------------------------------------

    def _on_toggle(self, enabled: bool) -> None:
        if not self._dc.is_xlsx:
            return
        self._dc.set_enabled(enabled)
        self._refresh()

    def _apply_mode_hint(self) -> None:
        if not self._dc.is_xlsx:
            self._hint.setText('csv/txt 不可开启')
            self._hint.setStyleSheet('color: #c00; font-size: 11px;')
        else:
            state = '已开启' if self._dc.enabled else '已关闭（默认）'
            self._hint.setText(state)
            self._hint.setStyleSheet('color: #888; font-size: 11px;')

    # ------------------------------------------------------------------
    # 列表刷新
    # ------------------------------------------------------------------

    def _refresh(self) -> None:
        self._list.clear()
        self._expanded: set = set()
        dc = self._dc
        sheet = getattr(dc, '_current_sheet', '') or ''
        # 循环引用检测（对齐 Excel：不报错，面板警告 + 状态栏提示）
        cycle_ids = detect_cycle_entry_ids(dc._formula_entries) \
            if dc.is_xlsx else set()
        self._update_cycle_warning(cycle_ids)
        # 统一条目（script/formula 按扩展区真实顺序混合，xlsx 才显示）
        entries = dc.mixed_entries(sheet) if dc.is_xlsx else []
        for e in entries:
            kind = e.get('kind', 'script')
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, e.get('id', ''))
            item.setData(Qt.ItemDataRole.UserRole + 1, kind)
            item.setSizeHint(self._item_size())
            self._list.addItem(item)
            in_cycle = e.get('id', '') in cycle_ids
            w = (self._make_item_widget(e, in_cycle) if kind == 'script'
                 else self._make_formula_item_widget(e, in_cycle))
            self._list.setItemWidget(item, w)
        # 空列表提示（仅 xlsx 且有 sheet 时）
        if dc.is_xlsx and sheet and self._list.count() == 0:
            from PyQt6.QtWidgets import QLabel
            item = QListWidgetItem()
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            item.setSizeHint(self._item_size())
            self._list.addItem(item)
            lbl = QLabel('此工作表暂无动态脚本（运行脚本成功后自动记录）')
            lbl.setStyleSheet('color: #888; font-size: 12px; padding: 8px;')
            self._list.setItemWidget(item, lbl)
        self._apply_mode_hint()

    def _update_cycle_warning(self, cycle_ids: set) -> None:
        """循环引用警告条：列出环上公式格（对齐 Excel 状态栏「循环引用」提示）。"""
        if not cycle_ids:
            self._cycle_warn.hide()
            return
        names = []
        for e in self._dc._formula_entries:
            if e.get('id') not in cycle_ids:
                continue
            region = e.get('output', {}).get('region') or [0, 0, 0, 0]
            cell = f"{_col(region[1])}{region[0] + 1}"
            names.append(f'{e.get("sheet", "")}!{cell}')
        self._cycle_warn.setText(
            '⚠️ 循环引用：' + '、'.join(names)
            + '（按当前迭代次数计算，不移除则结果可能不收敛）')
        self._cycle_warn.show()

    def _on_iterations_changed(self, n: int) -> None:
        """迭代次数变更：写扩展区（按 xlsx）+ 状态栏提示。"""
        self._push_snapshot()   # 撤销：变更前状态
        v = self._dc.set_iterations(n)
        self._dc.status_message.emit(
            f'✓ 迭代次数已设为 {v}（循环引用按此计算，上限 100）')

    # ------------------------------------------------------------------
    # 面板独立撤销（会话级：打开面板初始化，与表格撤销分离）
    # ------------------------------------------------------------------

    def _current_snapshot(self) -> dict:
        """当前扩展区条目 + 迭代次数（深拷贝，撤销粒度）。"""
        import copy
        return {
            'entries': copy.deepcopy(self._dc._store.get_entries()),
            'iterations': self._dc.iterations,
        }

    def _push_snapshot(self) -> None:
        self._undo_stack.append(self._current_snapshot())
        if len(self._undo_stack) > 50:
            self._undo_stack.pop(0)
        self._redo_stack.clear()

    def _restore_snapshot(self, snap: dict) -> None:
        """恢复快照：写扩展区 + 同步 controller 内存态 + 刷新面板。"""
        self._dc._store.set_entries(snap.get('entries', []))
        self._dc.set_iterations(snap.get('iterations', 5))
        self._dc.sync_from_store()
        self._iter_spin.blockSignals(True)
        self._iter_spin.setValue(self._dc.iterations)
        self._iter_spin.blockSignals(False)
        self._refresh()

    def _undo(self) -> None:
        if not self._undo_stack:
            self._dc.status_message.emit('无可撤销')
            return
        self._redo_stack.append(self._current_snapshot())
        self._restore_snapshot(self._undo_stack.pop())

    def _redo(self) -> None:
        if not self._redo_stack:
            self._dc.status_message.emit('无可重做')
            return
        self._undo_stack.append(self._current_snapshot())
        self._restore_snapshot(self._redo_stack.pop())

    def _item_size(self, expanded: bool = False):
        from PyQt6.QtCore import QSize
        return QSize(420, 96) if expanded else QSize(420, 30)

    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        """点击条目 → 展开/收起详情。"""
        sid = item.data(Qt.ItemDataRole.UserRole)
        if sid is None:
            return  # 公式格条目
        if sid in self._expanded:
            self._expanded.discard(sid)
        else:
            self._expanded.add(sid)
        item.setSizeHint(self._item_size(expanded=sid in self._expanded))
        self._list.doItemsLayout()

    def _make_item_widget(self, s: dict, in_cycle: bool = False) -> QWidget:
        """两态条目：一行摘要（点击展开详情 + 冲突/循环说明）。"""
        from PyQt6.QtWidgets import QWidget, QVBoxLayout
        w = QWidget(self._list)
        lo = QVBoxLayout(w)
        lo.setContentsMargins(8, 2, 8, 2)
        lo.setSpacing(0)

        summary = s.get('summary') or s.get('script', '?')
        conflict = self._has_conflict(s)
        marks = ('  🔄' if in_cycle else '') + ('  ⚠️' if conflict else '')
        line1 = QLabel(f'▶ {summary}{marks}')
        line1.setStyleSheet('font-size: 12px;')
        lo.addWidget(line1)

        detail = self._detail_text(s)
        # 冲突说明追加在详情末尾（展开时可见）
        if conflict:
            detail += '\n' + self._conflict_text(s)
        line2 = QLabel(detail)
        line2.setStyleSheet('color: #888; font-size: 11px;')
        line2.setWordWrap(True)
        line2.hide()
        lo.addWidget(line2)

        sid = s.get('id', '')
        w._sid = sid

        def _sync(expanded: bool):
            line2.setVisible(expanded)
        w._sync = _sync
        return w

    def _detail_text(self, s: dict) -> str:
        cfg = s.get('replay_cfg') or {}
        parts = []
        if 'direction' in cfg:
            parts.append(f'方向:{cfg["direction"]}')
        if 'range' in cfg:
            r = cfg['range']
            parts.append(f'区域:{_col(r[1])}{r[0] + 1}:{_col(r[3])}{r[2] + 1}')
        # 排序：单位 + 顺序 + 参考列/行
        unit = cfg.get('unit', '')
        if unit:
            parts.append(f'单位:{unit}')
        if cfg.get('order'):
            parts.append(f'顺序:{cfg["order"]}')
        if isinstance(cfg.get('ref'), int) and unit:
            ref = cfg['ref']
            parts.append(f'参考{"列" + _col(ref) if "行" in unit else "行" + str(ref + 1)}')
        raw = cfg.get('operands_raw')
        if raw:
            labels = []
            for r in raw:
                k = r.get('kind')
                if k == 'column':
                    labels.append(f"列{_col(r['index'])}")
                elif k == 'row':
                    labels.append(f"行{r['index'] + 1}")
                elif k == 'constant':
                    labels.append(f"常数{r.get('value')}")
                elif k == 'clipboard':
                    labels.append('剪贴板')
            parts.append('计算元:' + '、'.join(labels))
        out = cfg.get('output')
        if out:
            if out['target'] == 'column':
                parts.append(f"输出:列{_col(out['index'])}")
            else:
                parts.append(f"输出:行{out['index'] + 1}")
        if 'custom_blocks' in cfg:
            parts.append('自定义运算积木')
        recorded = s.get('recorded_at', '')
        if recorded:
            parts.append(f'记录于 {recorded}')
        return '  '.join(parts) if parts else '（无详细配置）'

    def _conflicts(self, s: dict) -> list[dict]:
        """输出区与列表中其他脚本输出区重叠的脚本列表（同 sheet）。"""
        outs = s.get('output_cells', [])
        if not outs:
            return []
        sheet = s.get('sheet', '')
        result = []
        for other in self._dc.scripts:
            if other.get('id') == s.get('id'):
                continue
            if other.get('sheet', '') != sheet:
                continue
            if regions_overlap(outs, other.get('output_cells', [])):
                result.append(other)
        return result

    def _has_conflict(self, s: dict) -> bool:
        """输出区与列表中其他脚本输出区重叠 → ⚠️。"""
        return bool(self._conflicts(s))

    def _conflict_text(self, s: dict) -> str:
        """冲突说明：与哪些脚本、哪些区域重叠。"""
        outs = s.get('output_cells', [])
        lines = []
        for other in self._conflicts(s):
            o_outs = other.get('output_cells', [])
            overlap = [self._region_text(a) for a in outs
                       for b in o_outs
                       if regions_overlap([a], [b])]
            name = other.get('summary') or other.get('script', '?')
            lines.append(f'⚠️ 输出区与「{name}」重叠'
                         + (f'（{", ".join(overlap)}）' if overlap else ''))
        return '\n'.join(lines)

    def _region_text(self, ref: dict) -> str:
        """引用描述 → 区域文本（列B / 行3 / A1:B5）。"""
        if 'col' in ref:
            return f'列{_col(ref["col"])}'
        if 'row' in ref:
            return f'行{ref["row"] + 1}'
        if 'range' in ref:
            r1, c1, r2, c2 = ref['range']
            return f'{_col(c1)}{r1 + 1}:{_col(c2)}{r2 + 1}'
        return '?'

    def _make_formula_item_widget(self, e: dict, in_cycle: bool = False) -> QWidget:
        """公式格条目两态：摘要行（📐 [公式格] 单元格 =公式）+ 点击展开详情。"""
        from PyQt6.QtWidgets import QWidget, QVBoxLayout
        from models.formula_translate import index_to_col_letter
        w = QWidget(self._list)
        lo = QVBoxLayout(w)
        lo.setContentsMargins(8, 2, 8, 2)
        lo.setSpacing(0)

        region = e.get('output', {}).get('region') or [0, 0, 0, 0]
        cell_name = f"{index_to_col_letter(region[1])}{region[0] + 1}"
        formula = e.get('formula', {}).get('text', '')
        if formula.startswith('='):
            formula = formula[1:]   # 公式本身带 =，摘要不再重复
        summary = f'📐 [公式格] {e.get("sheet", "")}!{cell_name}'
        if len(formula) > 40:
            formula = formula[:37] + '...'
        line1 = QLabel(f'{summary}  ={formula}' + ('  🔄' if in_cycle else ''))
        line1.setStyleSheet('font-size: 12px;')
        lo.addWidget(line1)

        line2 = QLabel(self._formula_detail_text(e))
        line2.setStyleSheet('color: #888; font-size: 11px;')
        line2.setWordWrap(True)
        line2.hide()
        lo.addWidget(line2)

        w._sid = e.get('id', '')

        def _sync(expanded: bool):
            line2.setVisible(expanded)
        w._sync = _sync
        return w

    def _formula_detail_text(self, e: dict) -> str:
        """公式格条目展开详情：公式全文 / 引用区域 / 输出 / 来源 / 记录时间。"""
        from models.formula_translate import index_to_col_letter
        parts = []
        ftext = e.get('formula', {}).get('text', '')
        parts.append(f'公式:{ftext}')
        refs = e.get('refs', [])
        if refs:
            ref_texts = []
            for r in refs:
                if isinstance(r, dict) and 'range' in r:
                    rng = r.get('range')
                    if rng:
                        rt = self._region_text({'range': list(rng)})
                        ref_texts.append((r.get('sheet') + '!' if r.get('sheet') else '') + rt)
                elif isinstance(r, dict):
                    rt = self._region_text(r)
                    ref_texts.append(rt)
                else:
                    ref_texts.append(self._region_text({'range': list(r)}))
            parts.append('引用:' + '、'.join(ref_texts))
        region = e.get('output', {}).get('region')
        if region:
            cell = f"{index_to_col_letter(region[1])}{region[0] + 1}"
            parts.append(f'输出:{e.get("sheet", "")}!{cell}')
        recorded = e.get('recorded_at', '')
        if recorded:
            parts.append(f'记录于 {recorded}')
        return '  '.join(parts) if parts else '（无详细配置）'

    # ------------------------------------------------------------------
    # 右键菜单
    # ------------------------------------------------------------------

    def _on_list_context_menu(self, pos) -> None:
        """列表右键：移除 / 上移 / 下移（脚本条目与公式格条目统一）。"""
        item = self._list.itemAt(pos)
        if item is None:
            return
        eid = item.data(Qt.ItemDataRole.UserRole)
        kind = item.data(Qt.ItemDataRole.UserRole + 1) or 'script'
        if not eid:
            return
        menu = QMenu(self)
        remove_act = menu.addAction('移除')
        menu.addSeparator()
        up_act = menu.addAction('上移')
        down_act = menu.addAction('下移')
        chosen = menu.exec(self._list.mapToGlobal(pos))
        if chosen is None:
            return
        self._push_snapshot()   # 撤销：操作前状态（移除/排序）
        if chosen is remove_act:
            if kind == 'formula':
                self._dc.remove_formula(eid)
            else:
                self._dc.remove_script(eid)
            self._refresh()
        elif chosen is up_act:
            if kind == 'formula':
                self._dc.reorder_formula(eid, -1)
            else:
                self._dc.reorder_script(eid, -1)
            self._refresh()
        elif chosen is down_act:
            if kind == 'formula':
                self._dc.reorder_formula(eid, 1)
            else:
                self._dc.reorder_script(eid, 1)
            self._refresh()


def _col(idx: int) -> str:
    from models.formula_translate import index_to_col_letter
    return index_to_col_letter(idx)

