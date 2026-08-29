"""应用入口。"""
import faulthandler
import os
import sys
import traceback

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt

from config.settings import AppSettings
from views.main_window import MainWindow


def _setup_crash_log() -> str:
    """启用崩溃日志：写入软件 data/error.log。

    - faulthandler：捕获 C 层崩溃（segfault / abort）的 Python 栈
    - sys.excepthook：捕获未处理 Python 异常的 traceback
    崩溃后打开 data/error.log 即可看到报错（终端关闭也不丢）。
    """
    from config.settings import _app_base_dir
    log_path = os.path.join(_app_base_dir(), 'data', 'error.log')
    try:
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        f = open(log_path, 'w', encoding='utf-8')
        faulthandler.enable(file=f)

        def _hook(exc_type, exc_value, exc_tb):
            traceback.print_exception(exc_type, exc_value, exc_tb, file=f)
            f.flush()
            # 同时打到 stderr（有终端时可见）
            traceback.print_exception(exc_type, exc_value, exc_tb)

        sys.excepthook = _hook
        return log_path
    except OSError:
        return ''


def main():
    crash_log = _setup_crash_log()
    if crash_log:
        print(f'崩溃日志: {crash_log}')

    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName('LightSheet')
    app.setOrganizationName('LightSheet')

    # Qt 界面汉化：加载 Qt 自带中文翻译（文件对话框按钮/标准控件文字 → 中文）
    # 仅影响 Qt 标准英文（如自绘文件对话框的 打开/取消），不影响软件自身中文界面
    from PyQt6.QtCore import QTranslator, QLibraryInfo
    _translator = QTranslator(app)
    if _translator.load(
            'qtbase_zh_CN',
            QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)):
        app.installTranslator(_translator)

    settings = AppSettings()
    settings.load()  # 启动时加载配置

    window = MainWindow(settings)
    window.show()

    sys.exit(app.exec())


if __name__ == '__main__':
    main()
