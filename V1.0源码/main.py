"""应用入口。"""
import sys

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt

from config.settings import AppSettings
from views.main_window import MainWindow


def main():
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName('LightSheet')
    app.setOrganizationName('LightSheet')

    settings = AppSettings()
    settings.load()  # 启动时加载配置

    window = MainWindow(settings)
    window.show()

    sys.exit(app.exec())


if __name__ == '__main__':
    main()
