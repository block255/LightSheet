"""动态脚本引擎（Dynamic Controller）— 开关 / 记录 / 失焦触发 / 单向链重放。

设计（动态脚本 设计架构.md，2026-08-27）：
- 开关只管「写入列表 + 触发重放」，不影响列表数据与扩展区储存的存在
- 仅 xlsx 可开；csv/txt 面板可开但开关强制关、列表不显示
- 记录：脚本运行成功后，保存"运行配置"（可重放的最小参数集）
- 触发：单格修改失焦 → 命中引用区 → 单向链重放（顺序=依赖序）
- 重放失败：状态栏提示，不弹窗；公式格冲突：跳过 + 提示
"""
import json
import sys
from pathlib import Path

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QApplication

from models.ext_store import ExtStore
from models.formula_translate import formula_cell_map, script_to_formula_template
from models.formula_engine import (
    EvalContext, evaluate, ErrorValue, TableValue,
)


class DynamicController(QObject):
    """动态脚本模式控制器（每打开一个 xlsx 工作簿绑定一个实例）。"""

    status_message = pyqtSignal(str)   # 状态栏提示（不弹窗）

    def __init__(self, store: ExtStore, model, grid, parent=None):
        super().__init__(parent)
        self._store = store
        self._model = model
        self._grid = grid
        self._scripts: list[dict] = store.get_scripts()   # 内存副本
        self._formula_cells: list[dict] = store.get_formula_cells()
        self._formula_map = formula_cell_map(self._formula_cells)
        # 互译 v2：统一条目里的 formula 条目（外来/我们写的公式格）
        self._formula_entries: list[dict] = [
            e for e in store.get_entries() if e.get('kind') == 'formula']
        self._last_triggered: tuple[int, int] | None = None   # 同格防抖
        self._current_sheet: str = ''   # 当前激活 sheet 名
        self._sheet_models: dict = {}   # 互译跨表：{sheet名: model}

    def set_sheet_models(self, sheet_models: dict) -> None:
        """注入全部 sheet 模型（跨表公式求值/触发用）。"""
        self._sheet_models = dict(sheet_models)

    # ------------------------------------------------------------------
    # 开关
    # ------------------------------------------------------------------

    @property
    def enabled(self) -> bool:
        return self._store.get_dynamic_mode()

    def set_enabled(self, on: bool) -> None:
        self._store.set_dynamic_mode(bool(on))

    # ------------------------------------------------------------------
    # 迭代次数（循环引用计算，按 xlsx 为单位，默认 5，上限 100）
    # ------------------------------------------------------------------

    @property
    def iterations(self) -> int:
        return self._store.get_iterations()

    def set_iterations(self, n: int) -> int:
        return self._store.set_iterations(n)

    @property
    def is_xlsx(self) -> bool:
        """当前工作簿是否 xlsx（仅 xlsx 可开动态模式）。"""
        return (self._model.file_format == 'xlsx'
                and self._model.file_path is not None)

    # ------------------------------------------------------------------
    # 列表访问
    # ------------------------------------------------------------------

    @property
    def scripts(self) -> list[dict]:
        return self._scripts

    def mixed_entries(self, sheet: str = '') -> list[dict]:
        """扩展区统一条目（script/formula 混合，按扩展区真实顺序）。

        面板显示用：脚本与译入公式按记录顺序混排（上移/下移跨类型生效）。
        """
        out = []
        for e in self._store.get_entries():
            if e.get('kind') not in ('script', 'formula'):
                continue
            if sheet and e.get('sheet', '') != sheet:
                continue
            out.append(e)
        return out

    def remove_script(self, script_id: str) -> bool:
        if self._store.remove_script(script_id):
            self._scripts = [s for s in self._scripts
                             if s.get('id') != script_id]
            return True
        return False

    def reorder_script(self, script_id: str, direction: int) -> bool:
        if self._store.reorder_script(script_id, direction):
            self._scripts = self._store.get_scripts()
            return True
        return False

    # ------------------------------------------------------------------
    # formula 条目（外来/我们写的公式格）：与脚本条目同套操作（移除/排序）
    # ------------------------------------------------------------------

    def remove_formula(self, entry_id: str) -> bool:
        """移除公式格条目：删扩展区条目 + 同步内存态。

        模型中的当前值保留（不清空格子）；保存时该格不再写公式（变普通值）。
        """
        if self._store.remove_entry(entry_id):
            self._sync_formula_state()
            return True
        return False

    def reorder_formula(self, entry_id: str, direction: int) -> bool:
        """公式格条目上移/下移（扩展区顺序，公式块内生效）。"""
        if self._store.reorder_entry(entry_id, direction):
            self._sync_formula_state()
            return True
        return False

    def _sync_formula_state(self) -> None:
        """从扩展区重建 formula 条目内存态（entries/cells/map 保持一致）。"""
        self._formula_entries = [e for e in self._store.get_entries()
                                 if e.get('kind') == 'formula']
        self._formula_cells = self._store.get_formula_cells()
        self._formula_map = formula_cell_map(self._formula_cells)

    def sync_from_store(self) -> None:
        """从扩展区全量重建内存态（脚本+公式，面板撤销恢复后调用）。"""
        self._scripts = self._store.get_scripts()
        self._sync_formula_state()

    # ------------------------------------------------------------------
    # 记录（脚本运行成功后调用）
    # ------------------------------------------------------------------

    def record(self, script_name: str, script_path: str,
               params: dict, sheet: str = '') -> dict | None:
        """把一次成功运行的脚本记录进动态列表。

        提取运行配置（replay_cfg）与引用/输出区域；
        sheet：脚本运行所在的 sheet 名（xlsx 公式分 sheet，动态脚本也分 sheet）；
        开关关闭时不记录（返回 None）。
        """
        if not self.enabled:
            return None
        cfg, ref_cells, output_cells = extract_replay_config(params)
        rec = {
            'script': script_name,
            'script_path': script_path,
            'sheet': sheet,
            'summary': make_summary(script_name, params),
            'replay_cfg': cfg,
            'ref_cells': ref_cells,
            'output_cells': output_cells,
            'recorded_at': __import__('datetime').datetime.now().strftime(
                '%Y-%m-%d %H:%M'),
        }
        # 互译 P2：尝试翻译成公式模板（不可译则无 formula 字段，用我们机制）
        try:
            f = script_to_formula_template(cfg, script_name)
            if f:
                rec['formula'] = {'text': f,
                                  'cell0': _output_origin(output_cells)}
        except Exception:
            pass
        stored = self._store.add_script(rec)
        self._scripts = self._store.get_scripts()
        # 依赖提示（不自动排序）：同 sheet 内 引用区 ∩ 已有脚本输出区
        deps = [s['summary'] for s in self._scripts
                if s.get('id') != stored['id']
                and s.get('sheet') == sheet
                and regions_overlap(ref_cells, s.get('output_cells', []))]
        if deps:
            self.status_message.emit(
                f'动态脚本已记录「{script_name}」（{sheet}），依赖'
                f'「{"、".join(deps)}」（注意顺序：被依赖的脚本应在上面）')
        return stored

    # ------------------------------------------------------------------
    # 触发（编辑失焦）
    # ------------------------------------------------------------------

    def set_model(self, model, sheet: str = '') -> None:
        """切换 sheet 时更新当前模型（重放目标）与 sheet 名。"""
        self._model = model
        self._current_sheet = sheet
        self._last_triggered = None

    def on_cell_edited(self, row: int, col: int, sheet: str = '') -> None:
        """单格修改确认（失焦）→ 单向链重放。

        仅 xlsx + 开关开启时生效；同格防抖；只处理同 sheet 的脚本
        （xlsx 公式分 sheet，动态脚本同样按 sheet 隔离）。
        """
        if not self.is_xlsx or not self.enabled:
            return
        if self._last_triggered == (row, col):
            return
        self._last_triggered = (row, col)
        touched = {(row, col)}
        for s in self._scripts:
            if s.get('sheet') != sheet:
                continue   # 其他 sheet 的脚本不参与
            refs = s.get('ref_cells', [])
            if not regions_contain(touched, refs):
                continue
            ok = self._replay(s)
            if not ok:
                continue   # 重放失败：输出未写，链中断（下游不触发）
            # 输出描述（col/row/range）展开为坐标并入 touched
            for od in s.get('output_cells', []):
                touched |= _expand_ref(od, self._model)
        # 互译 P3：formula 条目（外来/我们写的公式格）链式迭代触发
        # （跨条目/跨表传播：销售表 D2 更新后 → 汇总表 SUM(D2:D4) 才命中）
        replayed: set[str] = set()
        for _ in range(self.iterations):   # 迭代次数按 xlsx 设置（默认 5，上限 100）
            progressed = False
            for e in self._formula_entries:
                eid = e.get('id', '')
                if eid in replayed:
                    continue
                if not regions_contain(touched, e.get('refs', []), sheet):
                    continue
                # 输出写条目所属 sheet 的模型（跨表条目输出在别表）
                m = self._sheet_models.get(e.get('sheet'), self._model)
                ok, _ = self._replay_formula_on(e, m)
                if not ok:
                    continue
                replayed.add(eid)
                od = e.get('output') or {}
                before = len(touched)
                if 'region' in od:
                    touched |= _expand_ref({'range': od['region']}, m)
                if len(touched) > before:
                    progressed = True
            if not progressed:
                break
        if replayed:
            self.status_message.emit(
                f'↻ {len(replayed)} 个公式格已重算')
        # 防抖清理（下一轮编辑前允许同格再次触发）
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(300, lambda: self._clear_last())

    def _clear_last(self) -> None:
        self._last_triggered = None

    # ------------------------------------------------------------------
    # 重放
    # ------------------------------------------------------------------

    def _replay(self, rec: dict) -> bool:
        """按记录配置重放脚本（重新识别当前数据）。成功返回 True。"""
        cfg = rec.get('replay_cfg') or {}
        script = load_script_instance(rec.get('script_path') or '')
        if script is None:
            self.status_message.emit(
                f'动态脚本「{rec.get("script", "?")}」重放失败：脚本文件不存在')
            return False
        params = build_replay_params(cfg, self._model)
        if params is None:
            self.status_message.emit(
                f'动态脚本「{rec.get("script", "?")}」重放失败：配置不完整')
            return False
        if isinstance(params, str):
            self.status_message.emit(
                f'动态脚本「{rec.get("script", "?")}」重放失败：{params}')
            return False
        try:
            error = script.run(self._model, params)
        except Exception as e:
            self.status_message.emit(
                f'动态脚本「{rec.get("script", "?")}」重放失败：{e}')
            return False
        if error:
            self.status_message.emit(
                f'动态脚本「{rec.get("script", "?")}」重放失败：{error}')
            return False
        self.status_message.emit(
            f'↻ 动态脚本「{rec.get("script", "?")}」已自动重放')
        return True

    # ------------------------------------------------------------------
    # 互译 P3：公式条目重放（外来公式 / 我们翻译的公式格）
    # ------------------------------------------------------------------

    def compute_formula_values(self, sheet_models=None) -> None:
        """打开 xlsx 后：对所有 formula 条目引擎算值填充模型（替代缓存）。

        sheet_models: [(sheet名, model)] 可选——多 sheet 时每个条目用
        对应 sheet 的模型算（否则所有条目都拿当前模型算，会错位污染）；
        缺省用当前模型（单 sheet / 编辑触发场景）。
        迭代直到稳定或达到次数上限（iterations，按 xlsx 设置，默认 5）：
        跨表条目可能依赖同表条目的输出（如汇总表 SUM 引用销售表 D2:D4
        的公式格），多轮传播；循环引用条目不报错（对齐 Excel），用
        第 N 轮结果，面板/状态栏给警告。
        """
        entries = self._formula_entries
        for _ in range(self.iterations):
            changed = False
            for e in entries:
                m = self._model
                if sheet_models:
                    mm = next((mm for n, mm in sheet_models
                               if n == e.get('sheet')), None)
                    if mm is not None:
                        m = mm
                    else:
                        continue   # 孤儿条目（sheet 不存在）：跳过，不回退当前模型（防跨表污染）
                ok, c = self._replay_formula_on(e, m)
                changed = changed or c
            if not changed:
                break
        # 脚本翻译公式（保存时写的 <f>）：打开时同样算值显示——
        # 这些格在脚本输出区（scan 时被过滤不建 formula 条目），
        # 若不在此算，显示的是公式文本而非值（互译适配缺口）。
        self._compute_script_formula_values(sheet_models)

    def _compute_script_formula_values(self, sheet_models=None) -> None:
        """打开 xlsx 后：对 script 条目的翻译公式展开并引擎算值写模型。

        展开范围与保存公式一致（_expand_script_cells，对齐脚本 run 写入范围），
        只算有 formula 模板的 script 条目（可互译的运算类等）。
        孤儿条目（sheet 不存在于 sheet_models）跳过——不回退当前模型，
        避免其他 sheet 的残留条目污染当前表（如「销售表原生脚本测试」残留
        把求和结果写进销售表 D5）。
        """
        from models.formula_engine import expand_template, EvalContext, evaluate
        models_map = dict(sheet_models or [])
        for e in self._scripts:
            f = e.get('formula')
            if not f or not f.get('text'):
                continue
            template = f['text']
            cell0 = f.get('cell0') or [0, 0]
            sheet = e.get('sheet', '')
            m = models_map.get(sheet)
            if m is None:
                continue   # 孤儿条目：sheet 不存在 → 跳过
            ctx = EvalContext(m, sheet,
                              self._sheet_models or models_map)
            for (r, c) in _expand_script_cells(e):
                try:
                    ftext = expand_template(
                        template, r, c, cell0[0], cell0[1])
                    v = evaluate(ftext, ctx)
                    m.set_value(r, c, _formula_value_text(v))
                except Exception:
                    pass

    def _replay_formula(self, entry: dict) -> bool:
        """公式条目：P3 引擎按公式算输出格值（用当前模型）。"""
        ok, _ = self._replay_formula_on(entry, self._model)
        return ok

    def _replay_formula_on(self, entry: dict, model) -> tuple[bool, bool]:
        """公式条目在指定模型上算输出格值，返回 (是否成功, 是否有值变化)。

        多 sheet 按对应模型；跨表引用取全表（self._sheet_models）。
        """
        ftext = entry.get('formula', {}).get('text', '')
        region = entry.get('output', {}).get('region')
        if not ftext or not region:
            return False, False
        try:
            ctx = EvalContext(model, entry.get('sheet', ''),
                              self._sheet_models)
            v = evaluate(ftext, ctx)
            text = _formula_value_text(v)
            r1, c1, r2, c2 = region
            changed = False
            for r in range(r1, r2 + 1):
                for c in range(c1, c2 + 1):
                    if model.value(r, c) != text:
                        model.set_value(r, c, text)
                        changed = True
        except Exception:
            return False, False
        return True, changed

    def script_output_cells(self, row_total=100, col_total=26) -> set:
        """script 条目输出格集合 {(sheet, r, c)}（扫描公式时过滤掉，避免双身份）。

        与公式展开范围一致（_expand_script_cells 精确格）——不按整行/整列
        过滤，避免误删输出行/列上与脚本重叠的外来公式（如求和输出行里的 D5）。
        """
        out = set()
        for e in self._scripts:
            sheet = e.get('sheet', '')
            for (r, c) in _expand_script_cells(e, row_total, col_total):
                out.add((sheet, r, c))
        return out

    def collect_save_formulas(self, row_total=100, col_total=26) -> dict:
        """保存 xlsx 用：收集全部条目的公式 {sheet: {(r,c): 公式文本}}。

        - formula 条目（外来公式）：单格原文保留（<f> 不丢）
        - script 条目（翻译模板）：展开到输出区域（我们写的公式给 Excel）
        """
        from models.formula_engine import expand_template
        formulas: dict = {}
        for e in self._store.get_entries():
            f = e.get('formula')
            if not f or not f.get('text'):
                continue
            sheet = e.get('sheet', '')
            if e.get('kind') == 'formula':
                region = e.get('output', {}).get('region') or []
                if len(region) == 4 and region[0] == region[2] \
                        and region[1] == region[3]:
                    formulas.setdefault(sheet, {})[(region[0], region[1])] \
                        = f['text']
                continue
            # script 条目：模板展开到输出区（对齐脚本 run 的实际写入范围）
            template = f['text']
            cell0 = f.get('cell0') or [0, 0]
            for (r, c) in _expand_script_cells(e, row_total, col_total):
                formulas.setdefault(sheet, {})[(r, c)] = expand_template(
                    template, r, c, cell0[0], cell0[1])
        return formulas


def _formula_value_text(v) -> str:
    """引擎求值结果 → 单元格文本（错误值保留原文，如 #DIV/0!）。"""
    if isinstance(v, ErrorValue):
        return str(v)
    if isinstance(v, TableValue):
        s = v.as_scalar()
        v = s if s is not None else v
    if isinstance(v, bool):
        return 'TRUE' if v else 'FALSE'
    if isinstance(v, float) and v == int(v):
        return str(int(v))
    if v is None:
        return ''
    return str(v)


def _output_origin(output_cells: list) -> list | None:
    """输出区域起点 [r0, c0]（模板展开基准：col→[0,c] row→[r,0] range→[r1,c1]）。"""
    for od in output_cells or []:
        if 'col' in od:
            return [0, od['col']]
        if 'row' in od:
            return [od['row'], 0]
        if 'range' in od:
            return [od['range'][0], od['range'][1]]
    return None


def _expand_script_cells(entry: dict, row_total=100, col_total=26) -> list:
    """脚本条目的公式展开格（对齐脚本 run 的实际写入范围）。

    运算类（replay_cfg 有 data_len）：start = title_idx+1（有标题时），
    只写 data_len 个——列输出 → 跳过标题行（start+i 行）；行输出 →
    跳过标题列（start+i 列）。与脚本 run 的 set_value 范围完全一致。
    统计类等（无 data_len）：按输出区域描述展开（整列/整行/区域——
    聚合输出是离散结果格，区域描述即结果区）。
    兼容旧字段 title_row（有 data_len 缺失时按 title_row 跳过）。
    """
    rcfg = entry.get('replay_cfg') or {}
    data_len = int(rcfg.get('data_len') or 0)
    has_title = rcfg.get('has_title')
    cells: list = []
    if data_len > 0 and has_title is not None:
        title_idx = int(rcfg.get('title_idx') or 0)
        start = (title_idx + 1) if has_title else 0
        for od in entry.get('output_cells', []):
            if 'col' in od:
                cells += [(start + i, od['col']) for i in range(data_len)]
            elif 'row' in od:
                cells += [(od['row'], start + i) for i in range(data_len)]
            elif 'range' in od:
                r1, c1, r2, c2 = od['range']
                cells += [(r, c) for r in range(r1, r2 + 1)
                          for c in range(c1, c2 + 1)]
        return cells
    # 旧字段 title_row 兼容（数据迁移前）
    title_row = rcfg.get('title_row')
    direction = str(rcfg.get('direction', ''))
    rng = rcfg.get('range')
    for od in entry.get('output_cells', []):
        if 'row' in od and isinstance(rng, (list, tuple)) and len(rng) == 4 \
                and '对列' in direction:
            # 统计类对列处理：每列聚合 → 输出行，列范围 = 区域列范围
            # （避免整行展开污染空列，如求和输出行只写区域对应列）
            cells += [(od['row'], c) for c in range(rng[1], rng[3] + 1)]
        elif 'col' in od and isinstance(rng, (list, tuple)) and len(rng) == 4 \
                and '对行' in direction:
            # 统计类对行处理：每行聚合 → 输出列，行范围 = 区域行范围
            cells += [(r, od['col']) for r in range(rng[0], rng[2] + 1)]
        elif 'col' in od:
            cells += [(r, od['col']) for r in range(row_total)
                      if title_row is None or r != title_row]
        elif 'row' in od:
            cells += [(od['row'], c) for c in range(col_total)
                      if title_row is None or od['row'] != title_row]
        elif 'range' in od:
            r1, c1, r2, c2 = od['range']
            cells += [(r, c) for r in range(r1, r2 + 1)
                      for c in range(c1, c2 + 1)
                      if title_row is None or r != title_row]
    return cells


# ----------------------------------------------------------------------
# 运行配置提取 / 摘要 / 区域工具
# ----------------------------------------------------------------------

def extract_replay_config(params: dict) -> tuple[dict, list, list]:
    """从运行成功的 params 提取 (replay_cfg, ref_cells, output_cells)。

    规则按脚本类型（params 结构）：
    - 运算类（加法等）：direction + operands 的原始槽位（列/行/常数/剪贴板固化）
    - 统计类（平均等）：range + direction + 输出
    - 自定义运算：direction + custom_blocks（积木树已序列化）
    - 查找/排序：range + 参考列 + 输出
    """
    cfg: dict = {}
    ref_cells: list = []
    output_cells: list = []

    if 'direction' in params:
        cfg['direction'] = params['direction']

    # 计算元槽位（运算类）
    ops = params.get('operands')
    if isinstance(ops, dict) and 'slots' in ops:
        # 文本计算元（字符串加法）vs 数值计算元：槽位 kind 不同
        text_mode = any(s.get('kind') in ('text', 'clipboard_single',
                                           'clipboard_multi')
                        for s in ops['slots'])
        slots_cfg = []
        for s in ops['slots']:
            kind = s.get('kind')
            if kind in ('column', 'row'):
                slots_cfg.append({'kind': kind, 'index': s['index']})
                # 引用区域：整列/整行（0..数据边界由重放时识别）
                if kind == 'column':
                    ref_cells.append({'col': s['index']})
                else:
                    ref_cells.append({'row': s['index']})
            elif kind == 'constant':
                slots_cfg.append({'kind': 'constant', 'value': s['value']})
            elif kind == 'clipboard':
                # 固化剪贴板内容（记录时值）
                slots_cfg.append({'kind': 'clipboard',
                                  'value': _frozen_clipboard(s)})
            elif kind == 'text':
                slots_cfg.append({'kind': 'text', 'value': s.get('value', '')})
            elif kind == 'clipboard_single':
                slots_cfg.append({'kind': 'clipboard_single',
                                  'value': s.get('value', '')})
            elif kind == 'clipboard_multi':
                slots_cfg.append({'kind': 'clipboard_multi',
                                  'value': s.get('value', '')})
        if text_mode:
            cfg['operands_text'] = True
        cfg['operands_raw'] = slots_cfg
        # 运算类输出精确展开信息（对齐脚本 run：start = title_idx+1，只写
        # data_len 个；标题轴由方向决定——以列为单位 title_idx 是行号，
        # 以行为单位 title_idx 是列号；输出列跳标题行、输出行跳标题列）
        cfg['has_title'] = bool(ops.get('has_title'))
        cfg['title_idx'] = int(ops.get('title_idx', 0) or 0)
        cfg['data_len'] = int(ops.get('data_len', 0) or 0)

    # 框选区域（统计/排序/查找）
    rng = params.get('range')
    if isinstance(rng, (list, tuple)) and len(rng) == 4:
        r1, c1, r2, c2 = rng
        cfg['range'] = list(rng)
        ref_cells.append({'range': list(rng)})
        # 统计类输出（垂直输出 invert）需要方向
        cfg.setdefault('direction', '')  # 排序/查找有 unit

    # 单位（排序/查找）
    if 'unit' in params:
        cfg['unit'] = params['unit']
        cfg['direction'] = params.get('unit', '')

    # 排序顺序（升序/降序）
    if 'order' in params:
        cfg['order'] = params['order']
        # 排序 = 原地重排整个 range：range 同时是引用区与输出区
        if isinstance(rng, (list, tuple)) and len(rng) == 4:
            output_cells.append({'range': list(rng)})

    # 查找参考列/行
    if 'ref' in params and isinstance(params['ref'], int):
        cfg['ref'] = params['ref']

    # 统计类专用参数（众数/分位数/计数/检定）
    if 'mode' in params:
        cfg['mode'] = params['mode']                      # 众数：默认/精确
    if 'quantile' in params:
        cfg['quantile'] = params['quantile']              # 分位数：0.5 或小数
    if 'operator' in params:
        cfg['operator'] = params['operator']              # 计数/检定/查找：符号
    if 'constant' in params:
        cfg['constant'] = params['constant']              # 计数/检定：常数（文本保留）
    if 'inspect_type' in params:
        cfg['inspect_type'] = params['inspect_type']      # 检定类型
    if 'type_value' in params:
        cfg['type_value'] = params['type_value']          # 检定数量/比例自定义值
    if 'fail_result' in params:
        cfg['fail_result'] = params['fail_result']        # 检定不通过输出
    if 'pass_result' in params:
        cfg['pass_result'] = params['pass_result']        # 检定通过输出

    # 查找脚本专用参数
    if 'lookup_type' in params:
        cfg['lookup_type'] = params['lookup_type']        # 按数据/按文本
    if 'text' in params:
        cfg['text'] = params['text']                      # 文本查找关键字
    if 'ignore_head' in params:
        cfg['ignore_head'] = params['ignore_head']        # 忽略首格

    # 三角脚本：函数 + 角度单位
    if 'function' in params:
        cfg['function'] = params['function']              # sin/cos/...
    if 'unit' in params and 'operands' in params:
        # 三角脚本的 unit = 弧度/度（区别于排序的 unit=单位）
        if 'order' not in params:                         # 非排序脚本
            cfg['angle_unit'] = params['unit']

    # 自定义运算积木树（BlockNode 对象 → dict，保证 JSON 可序列化）
    if 'custom_blocks' in params:
        from custom_calc.model import block_to_dict, InputKind, OutputTarget
        blocks = params['custom_blocks']
        if blocks and not isinstance(blocks[0], dict):
            # BlockNode 对象列表 → dict 列表，并提取引用/输出区域
            cfg['custom_blocks'] = [block_to_dict(b) for b in blocks]
            ref_cells.extend(_extract_block_refs(blocks))
            output_cells.extend(_extract_block_outputs(blocks))
        else:
            cfg['custom_blocks'] = blocks
            blist = [_block_from_dict(b) for b in blocks]
            ref_cells.extend(_extract_block_refs(blist))
            output_cells.extend(_extract_block_outputs(blist))

    # 输出目标
    out = params.get('output')
    if isinstance(out, dict) and out.get('target') in ('column', 'row'):
        cfg['output'] = {'target': out['target'], 'index': out['index']}
        if out['target'] == 'column':
            output_cells.append({'col': out['index']})
        else:
            output_cells.append({'row': out['index']})

    # 查找输出
    if 'find_output' in params:
        cfg['find_output'] = params['find_output']

    return cfg, ref_cells, output_cells


def _frozen_clipboard(slot: dict) -> str:
    """计算元槽位 → 固化剪贴板文本（记录时值）。"""
    if slot.get('value') is not None:
        return str(slot['value'])
    # 组装后的剪贴板槽：values + title 还原文本
    vals = slot.get('values', [])
    title = slot.get('title')
    if title:
        vals = [title] + list(vals)

    def _fmt(v):
        if isinstance(v, float) and v == int(v):
            return str(int(v))
        return str(v)

    return '\n'.join(_fmt(v) for v in vals)


def build_replay_params(cfg: dict, model) -> dict | str | None:
    """按运行配置重建 params（重放时重新识别数据）。

    返回 params dict；配置缺失返回 None；数据识别失败返回错误字符串。
    """
    params: dict = {}
    if 'direction' in cfg:
        params['direction'] = cfg['direction']
    if 'unit' in cfg:
        params['unit'] = cfg['unit']
    if 'order' in cfg:
        params['order'] = cfg['order']
    if 'range' in cfg:
        params['range'] = tuple(cfg['range'])
    if 'ref' in cfg:
        params['ref'] = cfg['ref']
    if 'custom_blocks' in cfg:
        # dict 列表 → BlockNode 对象列表（自定义运算脚本 run 需要）
        from custom_calc.model import block_from_dict
        params['custom_blocks'] = [
            block_from_dict(b) for b in cfg['custom_blocks']]
    if 'find_output' in cfg:
        params['find_output'] = cfg['find_output']
    # 统计类专用参数（众数/分位数/计数/检定）
    for k in ('mode', 'quantile', 'operator', 'constant', 'inspect_type',
              'type_value', 'fail_result', 'pass_result'):
        if k in cfg:
            params[k] = cfg[k]
    # 查找脚本专用参数
    for k in ('lookup_type', 'text', 'ignore_head'):
        if k in cfg:
            params[k] = cfg[k]
    # 三角脚本：函数 + 角度单位
    if 'function' in cfg:
        params['function'] = cfg['function']
    if 'angle_unit' in cfg:
        params['unit'] = cfg['angle_unit']
    # 排序类（range+unit+ref）：重放时按当前数据重新识别有效行/列
    if 'range' in cfg and 'ref' in cfg and ('unit' in cfg or 'direction' in cfg):
        valid = _recompute_valid_indices(cfg, model)
        if valid is None:
            return '无有效数据行/列（参考列/行数据无效）'
        params['_valid_indices'] = valid
    # 运算类：重建 operands（可能识别失败）
    raw = cfg.get('operands_raw')
    if raw:
        matrix = model.to_2d()
        if cfg.get('operands_text'):
            # 文本计算元（字符串加法）：文本组装
            from scripts.operand_builder import build_text_operands
            built = build_text_operands(raw, matrix,
                                        cfg.get('direction', ''))
            if isinstance(built, str):
                return built
            params['operands'] = built
        else:
            from scripts.operand_builder import build_operands
            built = build_operands(raw, matrix, cfg.get('direction', ''))
            if isinstance(built, str):
                return built   # 识别错误信息
            params['operands'] = built
    # 输出
    if 'output' in cfg:
        params['output'] = dict(cfg['output'])
    if not params:
        return None
    return params


def _recompute_valid_indices(cfg: dict, model):
    """排序脚本重放：按当前数据重新识别有效行/列索引。

    与桌面版 SelectHeaderStep 校验一致（validate_numeric_reference）。
    返回有效索引列表；数据无效返回 None。
    """
    r1, c1, r2, c2 = cfg['range']
    ref = cfg['ref']
    unit = cfg.get('unit') or cfg.get('direction') or ''
    by_row = '行' in unit
    from scripts.operand_builder import validate_numeric_reference
    if by_row:
        # 以行为单位 → 参考列：取区域内每行的 ref 列值
        cells = [model.value(r, ref) for r in range(r1, r2 + 1)]
    else:
        # 以列为单位 → 参考行：取区域内每列的 ref 行值
        cells = [model.value(ref, c) for c in range(c1, c2 + 1)]
    valid, err = validate_numeric_reference(cells)
    if err:
        return None
    return valid


def make_summary(script_name: str, params: dict) -> str:
    """生成摘要：脚本名 + 简短描述（悬停展开完整配置）。"""
    parts = []
    ops = params.get('operands')
    if isinstance(ops, dict) and 'slots' in ops:
        labels = []
        for s in ops['slots']:
            k = s.get('kind')
            if k == 'column':
                labels.append(f"列{_col_letter(s['index'])}")
            elif k == 'row':
                labels.append(f"行{s['index'] + 1}")
            elif k == 'constant':
                labels.append(str(s.get('value', '')))
            elif k == 'clipboard':
                labels.append('剪贴板')
        out = params.get('output') or {}
        # 运算类：按脚本名推断符号（指数 ^、对数 log()、其余按脚本名）
        op = _summary_operator(script_name)
        if op == 'log(' and len(labels) == 2:
            expr = f"log({labels[0]}, {labels[1]})"
        elif op:
            expr = op.join(labels)
        else:
            expr = '+'.join(labels)
        if out.get('target') == 'column':
            parts.append(f"{expr}→列{_col_letter(out['index'])}")
        elif out.get('target') == 'row':
            parts.append(f"{expr}→行{out['index'] + 1}")
        else:
            parts.append(expr)
    rng = params.get('range')
    if rng:
        parts.append(f"区域{_range_text(rng)}")
    # 排序/查找脚本：单位（三角脚本的 unit 是角度单位，不在此显示）
    unit = params.get('unit', '')
    if unit and 'function' not in params:
        parts.append(unit)
    order = params.get('order', '')
    if order:
        parts.append(order)
    if isinstance(params.get('ref'), int) and unit:
        ref = params['ref']
        # 以行为单位 → 参考列（点列头）；以列为单位 → 参考行（点行头）
        if '行' in unit:
            parts.append(f"参考列{_col_letter(ref)}")
        else:
            parts.append(f"参考行{ref + 1}")
    # 统计类/运算类：方向（三角也是运算类，需显示方向）
    direction = params.get('direction', '')
    if direction:
        parts.append(direction)
    if 'mode' in params:
        parts.append(f"模式{params['mode']}")
    if 'quantile' in params:
        q = params['quantile']
        parts.append('中位数' if q == 0.5 else f"分位{q}")
    if 'operator' in params and 'constant' in params:
        parts.append(f"{params['operator']}{params['constant']}")
    if 'inspect_type' in params:
        t = params['inspect_type']
        v = params.get('type_value')
        parts.append(t if v is None else f'{t}:{v}')
    # 查找脚本
    if 'lookup_type' in params:
        parts.append(params['lookup_type'])
    if 'text' in params:
        parts.append(f"找「{params['text']}」")
    if 'ignore_head' in params:
        parts.append(params['ignore_head'])
    # 三角：函数 + 角度单位（unit 是弧度/度，与排序的 unit 区分）
    if 'function' in params and 'operands' in params and 'order' not in params:
        parts.append(f"{params['function']}({params.get('unit', '弧度')})")
    if 'custom_blocks' in params:
        parts.append('自定义运算')
    if not parts:
        parts.append(script_name)
    return f'{script_name}  {"; ".join(parts)}'


def _col_letter(idx: int) -> str:
    s = ''
    n = idx + 1
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(ord('A') + r) + s
    return s


def _block_from_dict(b: dict):
    from custom_calc.model import block_from_dict
    return block_from_dict(b)


def _extract_block_refs(blocks: list) -> list:
    """遍历积木树，提取数元引用的列/行/范围（触发判定用）。

    返回引用描述列表：[{'col': n} / {'row': n} / {'range': [...]}, ...]
    """
    from custom_calc.model import InputKind
    refs: list = []

    def walk(node):
        if node is None:
            return
        data = getattr(node, 'data', None)
        if data is not None and getattr(data, 'kind', None) is not None:
            k = data.kind
            if k == InputKind.COL and data.index is not None:
                refs.append({'col': data.index})
            elif k == InputKind.ROW and data.index is not None:
                refs.append({'row': data.index})
            elif k == InputKind.RANGE and data.range_start is not None \
                    and data.range_end is not None:
                if data.range_axis == 'row':
                    refs.append({'range': [data.range_start, 0,
                                           data.range_end, 10**6]})
                else:
                    refs.append({'range': [0, data.range_start,
                                           10**6, data.range_end]})
        for c in getattr(node, 'children', []) or []:
            walk(c)
        if data is not None and getattr(data, 'block', None) is not None:
            walk(data.block)

    for b in blocks:
        walk(b)
    return refs


def _extract_block_outputs(blocks: list) -> list:
    """遍历积木树，提取输出积木的位置（触发链下游用）。"""
    from custom_calc.model import OutputTarget
    outs: list = []

    def walk(node):
        if node is None:
            return
        if getattr(node, 'type', None) is not None \
                and str(getattr(node, 'type', '')).endswith('OUTPUT'):
            tgt = getattr(node, 'output_target', None)
            idx = getattr(node, 'output_index', None)
            if tgt == OutputTarget.COL and idx is not None:
                outs.append({'col': idx})
            elif tgt == OutputTarget.ROW and idx is not None:
                outs.append({'row': idx})
        data = getattr(node, 'data', None)
        for c in getattr(node, 'children', []) or []:
            walk(c)
        if data is not None and getattr(data, 'block', None) is not None:
            walk(data.block)

    for b in blocks:
        walk(b)
    return outs


def _summary_operator(script_name: str) -> str:
    """按脚本名推断计算元之间的运算符号（用于摘要）。"""
    for key, op in (('指数', '^'), ('对数', 'log('),
                    ('减法', '－'), ('除法', '÷'),
                    ('乘法', '×'), ('加法', '+')):
        if key in script_name:
            return op
    return ''


def _range_text(rng) -> str:
    r1, c1, r2, c2 = rng
    return f'{_col_letter(c1)}{r1 + 1}:{_col_letter(c2)}{r2 + 1}'


# ----------------------------------------------------------------------
# 区域工具（触发判定）
# ----------------------------------------------------------------------

def _expand_ref(ref: dict, model=None) -> set:
    """引用描述 {'col':n} / {'row':n} / {'range':[...]} → 格子集合。

    col/row 是整列/整行：展开到模型尺寸（无 model 时取全表 100×26 上限）。
    """
    max_r = model.row_total if model is not None else 100
    max_c = model.col_total if model is not None else 26
    if 'col' in ref:
        return {(r, ref['col']) for r in range(max_r)}
    if 'row' in ref:
        return {(ref['row'], c) for c in range(max_c)}
    if 'range' in ref:
        r1, c1, r2, c2 = ref['range']
        return {(r, c) for r in range(r1, r2 + 1) for c in range(c1, c2 + 1)}
    return set()


def detect_cycle_entry_ids(entries: list) -> set:
    """检测公式条目引用环（含间接环），返回环上条目 id 集合。

    对齐 Excel 循环引用语义：环不报错，面板/状态栏给警告，用第 N 轮
    迭代结果计算。依赖边：条目 A 的 refs 命中条目 B 的输出格 → A 依赖 B。
    纯函数（桌面/Web 同源共享）；输出格数量有限，逐格判断避免大区域展开。
    """
    out_index: dict = {}          # (sheet, r, c) -> entry id（单格输出）
    by_id: dict = {}
    for e in entries:
        if e.get('kind') != 'formula':
            continue
        eid = e.get('id')
        if not eid:
            continue
        by_id[eid] = e
        region = e.get('output', {}).get('region') or []
        if len(region) == 4 and region[0] == region[2] \
                and region[1] == region[3]:
            out_index[(e.get('sheet', ''), region[0], region[1])] = eid
    sheets_out: dict = {}         # sheet -> [(r, c, id)]
    for (s, r, c), eid in out_index.items():
        sheets_out.setdefault(s, []).append((r, c, eid))
    # 依赖图
    graph: dict = {eid: [] for eid in by_id}
    for eid, e in by_id.items():
        esheet = e.get('sheet', '')
        for ref in e.get('refs', []) or []:
            if not isinstance(ref, dict):
                continue
            rsheet = ref.get('sheet') or esheet
            rng = ref.get('range')
            if not rng or len(rng) != 4:
                continue
            r1, c1, r2, c2 = rng
            for (or_, oc, oid) in sheets_out.get(rsheet, []):
                if oid == eid:
                    continue
                if r1 <= or_ <= r2 and c1 <= oc <= c2 and oid not in graph[eid]:
                    graph[eid].append(oid)
    # DFS 三色标记找环：0 未访问 / 1 在栈 / 2 完成
    state: dict = {}
    stack: list = []
    in_cycle: set = set()

    def dfs(nid: str):
        state[nid] = 1
        stack.append(nid)
        for nxt in graph.get(nid, []):
            if state.get(nxt, 0) == 0:
                dfs(nxt)
            elif state.get(nxt, 0) == 1:
                idx = stack.index(nxt)
                for x in stack[idx:]:
                    in_cycle.add(x)
        stack.pop()
        state[nid] = 2

    for eid in by_id:
        if state.get(eid, 0) == 0:
            dfs(eid)
    return in_cycle


def regions_contain(touched: set, refs: list, touched_sheet: str = None) -> bool:
    """touched（本次编辑涉及的格子集合）是否命中任一引用描述。

    touched_sheet：被编辑的 sheet 名（跨表触发用）——
    ref 带 sheet 时只匹配同 sheet 的编辑；ref 无 sheet（同表引用）匹配所有。
    """
    for ref in refs:
        if not isinstance(ref, dict):
            ref = {'range': list(ref)}
        rsheet = ref.get('sheet')
        if rsheet and touched_sheet and rsheet != touched_sheet:
            continue   # 跨表引用：只响应被编辑的那个表
        # 整列/整行引用：只需比较行/列是否在 touched 内（避免展开 10^6）
        if 'col' in ref:
            if any(c == ref['col'] for _, c in touched):
                return True
        elif 'row' in ref:
            if any(r == ref['row'] for r, _ in touched):
                return True
        elif 'range' in ref:
            r1, c1, r2, c2 = ref['range']
            if any(r1 <= r <= r2 and c1 <= c <= c2 for r, c in touched):
                return True
    return False


def regions_overlap(a: list, b: list) -> bool:
    """两组引用描述是否有交集（依赖/冲突检测）。"""
    for ra in a:
        for rb in b:
            if _refs_intersect(ra, rb):
                return True
    return False


def _refs_intersect(ra: dict, rb: dict) -> bool:
    """两个引用描述是否相交（col/row/range 组合；跨表 ref 不同表不算）。"""
    sa = ra.get('sheet') if isinstance(ra, dict) else None
    sb = rb.get('sheet') if isinstance(rb, dict) else None
    if sa and sb and sa != sb:
        return False   # 不同 sheet 的引用区域不冲突
    if not isinstance(ra, dict):
        ra = {'range': list(ra)}
    if not isinstance(rb, dict):
        rb = {'range': list(rb)}
    ka, kb = set(ra), set(rb)
    if 'range' in ka or 'range' in kb:
        # 有 range：用范围比较
        ra_rng = ra.get('range')
        rb_rng = rb.get('range')
        if ra_rng and rb_rng:
            r1, c1, r2, c2 = ra_rng
            r3, c3, r4, c4 = rb_rng
            return not (r2 < r3 or r4 < r1 or c2 < c3 or c4 < c1)
        if ra_rng:
            r1, c1, r2, c2 = ra_rng
            if 'col' in rb:
                return c1 <= rb['col'] <= c2
            if 'row' in rb:
                return r1 <= rb['row'] <= r2
            return False
        if rb_rng:
            r1, c1, r2, c2 = rb_rng
            if 'col' in ra:
                return c1 <= ra['col'] <= c2
            if 'row' in ra:
                return r1 <= ra['row'] <= r2
            return False
    if 'col' in ka and 'col' in kb:
        return ra['col'] == rb['col']
    if 'row' in ka and 'row' in kb:
        return ra['row'] == rb['row']
    return False


# ----------------------------------------------------------------------
# 脚本加载（复用 ScriptController 的加载方式）
# ----------------------------------------------------------------------

def load_script_instance(path: str):
    """按路径加载脚本实例（与 ScriptController._load_script 同方式）。"""
    import importlib.util
    from scripts.base_script import BaseScript
    p = Path(path)
    if not p.is_file():
        return None
    old = sys.dont_write_bytecode
    try:
        sys.dont_write_bytecode = True
        spec = importlib.util.spec_from_file_location('_dyn_' + p.stem, p)
        if spec is None or spec.loader is None:
            return None
        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod
        spec.loader.exec_module(mod)
        for name in dir(mod):
            obj = getattr(mod, name)
            if (isinstance(obj, type) and issubclass(obj, BaseScript)
                    and obj is not BaseScript):
                return obj()
        return None
    except Exception:
        return None
    finally:
        sys.dont_write_bytecode = old
