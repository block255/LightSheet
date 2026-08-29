"""应用配置管理 — 基于 JSON 文件 + 相对路径，不使用系统注册表。"""
import json
import os
import sys
from pathlib import Path
from typing import Any


def _app_base_dir() -> str:
    """软件基准目录：打包后 = 可执行文件所在目录；开发时 = 代码输出库。"""
    if getattr(sys, 'frozen', False):   # PyInstaller 打包
        return os.path.dirname(sys.executable)
    return str(Path(__file__).resolve().parent.parent)


def _resolve_path(value: str, default_rel: str) -> str:
    """路径解析：绝对路径原样；相对路径 → 相对软件基准目录；空 → 默认相对。

    设计（2026-08-23 用户确认）：软件内置的脚本库/表格文件库用相对路径
    （随 exe 分发，开箱即用）；用户自行指定的用绝对路径（持久化，优先）。
    """
    v = (value or '').strip()
    if not v:
        v = default_rel
    if os.path.isabs(v):
        return v
    return os.path.normpath(os.path.join(_app_base_dir(), v))


class AppSettings:
    """管理应用配置的持久化。所有路径相对于 `代码输出库/` 目录。"""

    def __init__(self):
        # 基准目录：开发=代码输出库；打包后=exe 所在目录（config.json 可持久化）
        self._app_dir = Path(_app_base_dir())
        self._data_dir = self._app_dir / 'data'
        self._config_path = self._data_dir / 'config.json'
        self._data: dict[str, Any] = {}

    # ------------------------------------------------------------------
    # 公开 API
    # ------------------------------------------------------------------

    def load(self) -> None:
        """从 JSON 文件读取配置到内存。文件不存在时使用默认值。"""
        self._ensure_data_dir()
        if self._config_path.exists():
            try:
                with open(self._config_path, 'r', encoding='utf-8') as f:
                    self._data = json.load(f)
            except (json.JSONDecodeError, OSError):
                self._data = {}
        else:
            self._data = {}

    def save(self) -> None:
        """将内存中的配置写入 JSON 文件。"""
        self._ensure_data_dir()
        with open(self._config_path, 'w', encoding='utf-8') as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._data[key] = value

    # ------------------------------------------------------------------
    # 便捷属性
    # ------------------------------------------------------------------

    @property
    def app_dir(self) -> Path:
        return self._app_dir

    @property
    def data_dir(self) -> Path:
        return self._data_dir

    # --- 文件夹路径（相对默认 + 用户自定义绝对） ---

    @property
    def file_folder(self) -> str:
        return _resolve_path(self._data.get('file_folder', ''), '表格文件库')

    @file_folder.setter
    def file_folder(self, path: str) -> None:
        # 只赋值不写盘：避免"读默认值再写回"污染 config.json
        # （2026-08-27 事故根因）；持久化由显式 save() 负责
        self._data['file_folder'] = path

    @property
    def script_folder(self) -> str:
        return _resolve_path(self._data.get('script_folder', ''), '脚本库')

    @script_folder.setter
    def script_folder(self, path: str) -> None:
        # 同 file_folder：只赋值，持久化走显式 save()
        self._data['script_folder'] = path

    # --- 窗口状态 ---

    @property
    def window_geometry(self) -> str:
        """窗口几何信息（base64 QByteArray）。"""
        return self._data.get('window_geometry', '')

    @window_geometry.setter
    def window_geometry(self, value: str) -> None:
        self._data['window_geometry'] = value

    @property
    def window_state(self) -> str:
        """窗口状态（maximized 等）。"""
        return self._data.get('window_state', '')

    @window_state.setter
    def window_state(self, value: str) -> None:
        self._data['window_state'] = value

    @property
    def splitter_state(self) -> str:
        return self._data.get('splitter_state', '')

    @splitter_state.setter
    def splitter_state(self, value: str) -> None:
        self._data['splitter_state'] = value

    # --- 最近文件 ---

    @property
    def recent_files(self) -> list[str]:
        return self._data.get('recent_files', [])

    def add_recent_file(self, path: str) -> None:
        """添加到最近文件列表（去重，最多 5 个）。"""
        files: list = self._data.get('recent_files', [])
        if path in files:
            files.remove(path)
        files.insert(0, path)
        self._data['recent_files'] = files[:5]

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _ensure_data_dir(self) -> None:
        self._data_dir.mkdir(parents=True, exist_ok=True)
