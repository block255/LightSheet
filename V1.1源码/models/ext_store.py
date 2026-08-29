"""扩展信息储存区（External Info Store）— 每个 xlsx 文件一个 JSON 扩展。

位置（方案 A，2026-08-27 用户确认）：
  扩展区根 = Path(表格库).parent / '扩展信息区' / Path(表格库).name
  —— 与有效表格库并列的隐藏兄弟目录，按 xlsx 相对表格库路径镜像存放。

内容：dynamic_mode 开关 + 动态脚本列表（scripts）+ xlsx 公式格清单
     （formula_cells，互译层）。
同步：
  - 软件内操作 → 调用本模块读写；
  - 软件外操作 → reconcile() 对账：xlsx 消失删扩展、新 xlsx 建空扩展。
隐藏属性：用 ctypes SetFileAttributesW（不用 attrib 子进程，避免闪终端/卡顿）。
"""
import ctypes
import json
import os
import uuid
from pathlib import Path


class ExtStore:
    """单个 xlsx 的扩展信息读写。"""

    VERSION = 2

    def __init__(self, file_path: str, library_root: str):
        """
        file_path:    xlsx 文件的绝对路径
        library_root: 当前生效表格库根目录（绝对路径）
        """
        self._file_path = Path(file_path)
        self._library_root = Path(library_root)
        self._rel = self._file_path.relative_to(self._library_root).as_posix()
        self._ext_path = self._ext_path_for(self._file_path, self._library_root)

    # ------------------------------------------------------------------
    # 路径计算（静态，供 reconcile 使用）
    # ------------------------------------------------------------------

    @staticmethod
    def ext_root(library_root: str) -> Path:
        """扩展区根目录：表格库父目录/扩展信息区/表格库名。"""
        lib = Path(library_root)
        return lib.parent / '扩展信息区' / lib.name

    @staticmethod
    def _ext_path_for(file_path: Path, library_root: Path) -> Path:
        rel = file_path.relative_to(library_root).as_posix()
        return ExtStore.ext_root(library_root) / (rel + '.json')

    @property
    def ext_path(self) -> Path:
        return self._ext_path

    @property
    def rel_path(self) -> str:
        """xlsx 相对表格库路径（绑定标识）。"""
        return self._rel

    # ------------------------------------------------------------------
    # 读写
    # ------------------------------------------------------------------

    def load(self) -> dict:
        """读取扩展 JSON；不存在/损坏 → 返回空结构（容错）。

        v1（scripts + formula_cells 双列表）→ v2（entries 统一条目）自动迁移，
        迁移结果写回（用户无感，v2 为唯一持久格式）。
        """
        default = {
            'version': 2,
            'source_path': self._rel,
            'dynamic_mode': False,
            'source_fingerprint': '',
            'entries': [],
        }
        if not self._ext_path.is_file():
            return default
        try:
            with open(self._ext_path, encoding='utf-8') as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            return default
        if not isinstance(data, dict):
            return default
        # v1 → v2 迁移（旧双列表合并为统一条目列表）
        if data.get('version', 1) < 2 or 'entries' not in data:
            data = self._migrate_v1(data)
            self.save(data)
        # 补默认字段（兼容缺字段）
        for k, v in default.items():
            data.setdefault(k, v)
        return data

    @staticmethod
    def _migrate_v1(data: dict) -> dict:
        """v1 结构（scripts + formula_cells）→ v2 统一条目列表。"""
        entries = []
        # 我们的动态脚本 → script 条目（保留 v1 全字段承载，加统一标记）
        for s in data.get('scripts', []) or []:
            e = dict(s)
            e['source'] = 'ours'
            e['kind'] = 'script'
            entries.append(e)
        # 外来公式格 → formula 条目（输出=单格区域，refs 转统一描述）
        for fc in data.get('formula_cells', []) or []:
            cell = fc.get('cell') or [0, 0]
            entries.append({
                'id': uuid.uuid4().hex,
                'source': 'external',
                'kind': 'formula',
                'sheet': fc.get('sheet', ''),
                'output': {'region': [cell[0], cell[1], cell[0], cell[1]]},
                'refs': [{'range': list(r)} for r in fc.get('refs', [])],
                'formula': {'text': fc.get('formula', '')},
                'summary': f"[公式] {fc.get('formula', '')}",
                'recorded_at': '',
            })
        data['version'] = 2
        data['entries'] = entries
        # 清理 v1 遗留字段（不再持久化）
        data.pop('scripts', None)
        data.pop('formula_cells', None)
        return data

    def save(self, data: dict) -> None:
        """写扩展 JSON（自动建目录，设隐藏属性）。"""
        self._ext_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._ext_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        self._hide_dir(self._ext_path.parent)

    def remove(self) -> None:
        """删除扩展文件（xlsx 被删时调用）。"""
        try:
            if self._ext_path.is_file():
                self._ext_path.unlink()
        except OSError:
            pass

    @staticmethod
    def _hide_dir(path: Path) -> None:
        """设置 Windows 隐藏属性（ctypes 直接调用，零进程开销）。

        只对目录本身设置一次（已隐藏时跳过），不递归子文件。
        """
        try:
            attrs = ctypes.windll.kernel32.GetFileAttributesW(str(path))
            if attrs != -1 and not (attrs & 0x2):   # 0x2 = FILE_ATTRIBUTE_HIDDEN
                ctypes.windll.kernel32.SetFileAttributesW(str(path), attrs | 0x2)
        except (OSError, AttributeError):
            pass

    # ------------------------------------------------------------------
    # 数据操作（统一条目列表 / 开关）
    # ------------------------------------------------------------------

    def get_dynamic_mode(self) -> bool:
        return bool(self.load().get('dynamic_mode', False))

    def set_dynamic_mode(self, enabled: bool) -> None:
        data = self.load()
        data['dynamic_mode'] = bool(enabled)
        self.save(data)

    # --- 文件身份指纹（同名同路径替换自动区分） ---

    def get_fingerprint(self) -> str:
        return str(self.load().get('source_fingerprint', '') or '')

    def set_fingerprint(self, fp: str) -> None:
        data = self.load()
        data['source_fingerprint'] = str(fp or '')
        self.save(data)

    # --- 迭代次数（循环引用计算，按 xlsx 为单位，默认 5，上限 100） ---

    def get_iterations(self) -> int:
        try:
            v = int(self.load().get('iterations', 5))
        except (TypeError, ValueError):
            v = 5
        return max(1, min(v, 100))

    def set_iterations(self, n: int) -> int:
        data = self.load()
        data['iterations'] = max(1, min(int(n), 100))
        self.save(data)
        return data['iterations']

    # --- 统一条目接口（v2，脚本与公式同一列表） ---

    def get_entries(self) -> list[dict]:
        return list(self.load().get('entries', []))

    def set_entries(self, entries: list) -> None:
        """整表替换 entries（面板撤销恢复快照用），保留其他顶层字段。"""
        data = self.load()
        data['entries'] = list(entries)
        self.save(data)

    def add_entry(self, entry: dict) -> dict:
        """追加一条统一条目（script/formula 均适用），生成 id，返回完整条目。"""
        data = self.load()
        rec = dict(entry)
        rec.setdefault('id', uuid.uuid4().hex)
        rec.setdefault('kind', 'script')
        rec.setdefault('source', 'ours')
        data['entries'].append(rec)
        self.save(data)
        return rec

    def remove_entry(self, entry_id: str) -> bool:
        data = self.load()
        before = len(data['entries'])
        data['entries'] = [e for e in data['entries']
                           if e.get('id') != entry_id]
        if len(data['entries']) != before:
            self.save(data)
            return True
        return False

    def reorder_entry(self, entry_id: str, direction: int) -> bool:
        """上移(-1)/下移(+1)一条条目，返回是否成功。"""
        data = self.load()
        entries = data['entries']
        idx = next((i for i, e in enumerate(entries)
                    if e.get('id') == entry_id), -1)
        if idx < 0:
            return False
        new_idx = idx + direction
        if not (0 <= new_idx < len(entries)):
            return False
        entries[idx], entries[new_idx] = entries[new_idx], entries[idx]
        self.save(data)
        return True

    def remove_entries_by_sheet(self, sheet: str) -> int:
        """删除指定 sheet 的全部条目（script/formula 都删）。

        删工作表后源头清理用：sheet 删除 = 该 sheet 动态记录作废，
        防止孤儿条目残留（孤儿条目会跨表污染，见 0829 日志）。
        """
        data = self.load()
        before = len(data['entries'])
        data['entries'] = [e for e in data['entries']
                           if e.get('sheet') != sheet]
        if len(data['entries']) != before:
            self.save(data)
        return before - len(data['entries'])

    # --- 脚本形态（旧接口兼容：映射 entries 中 kind=script 的条目） ---

    def get_scripts(self) -> list[dict]:
        return [e for e in self.load().get('entries', [])
                if e.get('kind') == 'script']

    def add_script(self, script: dict) -> dict:
        """追加一条动态脚本记录（生成 id），返回完整记录。"""
        return self.add_entry(script)

    def remove_script(self, script_id: str) -> bool:
        return self.remove_entry(script_id)

    def reorder_script(self, script_id: str, direction: int) -> bool:
        return self.reorder_entry(script_id, direction)

    # --- 公式形态（旧接口兼容：映射 entries 中 kind=formula 的条目） ---

    def get_formula_cells(self) -> list[dict]:
        """formula 条目 → v1 公式格格式（{sheet, cell, formula, refs 纯坐标}）。"""
        out = []
        for e in self.load().get('entries', []):
            if e.get('kind') != 'formula':
                continue
            region = e.get('output', {}).get('region') or [0, 0, 0, 0]
            refs = []
            for r in e.get('refs', []):
                rng = r.get('range') if isinstance(r, dict) else r
                refs.append(tuple(rng) if rng else (0, 0, 0, 0))
            out.append({
                'sheet': e.get('sheet', ''),
                'cell': [region[0], region[1]],
                'formula': e.get('formula', {}).get('text', ''),
                'refs': refs,
            })
        return out

    def set_formula_cells(self, cells: list[dict]) -> None:
        """同步公式格条目（diff 更新，保留用户排序位置）。

        cells（xlsx 扫描结果）的 refs 元素可为 {'sheet','range'}（scan 新格式）
        或纯坐标（兼容）。
        匹配键 (sheet, r, c)：
        - xlsx 仍存在 → 条目原位保留（公式文本变了才更新 refs/formula/summary）
        - xlsx 已消失（用户移除且已保存）→ 删除条目（保留移除语义）
        - xlsx 新增 → 追加末尾
        """
        data = self.load()
        entries = data['entries']
        # xlsx 当前公式格 → 待更新/新增映射（key: (sheet, r, c)）
        update: dict = {}
        for fc in cells:
            cell = fc.get('cell') or [0, 0]
            ftext = fc.get('formula', '')
            refs = []
            for r in fc.get('refs', []):
                if isinstance(r, dict) and 'range' in r:
                    refs.append({'sheet': r.get('sheet'),
                                 'range': list(r['range'])})
                else:
                    refs.append({'sheet': None, 'range': list(r)})
            update[(fc.get('sheet', ''), cell[0], cell[1])] = {
                'cell': cell, 'refs': refs, 'ftext': ftext,
            }
        # 按原顺序重建：formula 条目原位保留/更新，xlsx 已消失的丢弃
        out = []
        for e in entries:
            if e.get('kind') != 'formula':
                out.append(e)
                continue
            region = e.get('output', {}).get('region') or []
            if len(region) == 4 and region[0] == region[2] \
                    and region[1] == region[3]:
                key = (e.get('sheet', ''), region[0], region[1])
                u = update.pop(key, None)
                if u is None:
                    continue   # xlsx 已无此公式格 → 删除（用户移除语义）
                if e.get('formula', {}).get('text', '') != u['ftext']:
                    e['formula'] = {'text': u['ftext']}
                    e['summary'] = f"[公式] {u['ftext']}"
                e['refs'] = u['refs']
                out.append(e)
            else:
                out.append(e)   # 非单格公式条目：保留（罕见）
        # xlsx 新增公式格 → 追加末尾
        for key, u in update.items():
            cell = u['cell']
            out.append({
                'id': uuid.uuid4().hex,
                'source': 'external',
                'kind': 'formula',
                'sheet': key[0],
                'output': {'region': [cell[0], cell[1], cell[0], cell[1]]},
                'refs': u['refs'],
                'formula': {'text': u['ftext']},
                'summary': f"[公式] {u['ftext']}",
                'recorded_at': '',
            })
        data['entries'] = out
        self.save(data)


# ----------------------------------------------------------------------
# 对账（软件外文件变动同步）
# ----------------------------------------------------------------------

def reconcile(library_root: str) -> int:
    """对账：扫描表格库所有 xlsx，清理无源扩展、补齐新文件空扩展。

    同时清理孤儿扩展区目录：扩展信息区/ 下每个子目录名 N 若对应
    的表格库目录（父目录/N）已不存在（库被删/移走）→ 该扩展区是
    孤儿，删除（避免隐藏垃圾堆积；库还在则保留，切回可复用）。
    返回处理的操作数（删除 + 新建计数）。
    """
    lib = Path(library_root)
    if not lib.is_dir():
        return 0
    root = ExtStore.ext_root(library_root)

    # 孤儿扩展区目录清理：扩展信息区/ 与表格库并列
    parent = lib.parent
    ext_area = parent / '扩展信息区'
    handled = 0
    if ext_area.is_dir():
        for d in ext_area.iterdir():
            if d.is_dir() and not (parent / d.name).is_dir():
                try:
                    import shutil
                    shutil.rmtree(d)
                    handled += 1
                except OSError:
                    pass

    if not root.is_dir():
        return handled
    # 当前所有 xlsx 相对路径
    existing: set[str] = set()
    for p in lib.rglob('*.xlsx'):
        existing.add(p.relative_to(lib).as_posix())
    # 扩展目录里所有 *.json 的相对路径
    for ext in root.rglob('*.json'):
        rel = ext.relative_to(root).as_posix()
        if not rel.endswith('.json'):
            continue
        src_rel = rel[:-len('.json')]
        if src_rel not in existing:
            try:
                ext.unlink()
                handled += 1
            except OSError:
                pass
            continue
        # 条目级对账：条目 sheet 不在对应 xlsx → 孤儿条目删除
        # （删工作表/外部改名后残留，防跨表污染；script/formula 都清）
        try:
            with open(ext, encoding='utf-8') as f:
                data = json.load(f)
            entries = data.get('entries') or []
            if not entries:
                continue
            from openpyxl import load_workbook as _lwb
            wb = _lwb(lib / src_rel, read_only=True)
            valid = {ws.title for ws in wb.worksheets}
            wb.close()
        except Exception:
            continue
        kept = [e for e in entries
                if not e.get('sheet') or e.get('sheet') in valid]
        if len(kept) != len(entries):
            data['entries'] = kept
            try:
                with open(ext, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                handled += 1
            except OSError:
                pass
    return handled
