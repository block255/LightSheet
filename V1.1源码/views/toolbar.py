"""工具栏构建。"""
from PyQt6.QtWidgets import QToolBar, QFileIconProvider
from PyQt6.QtGui import QAction
from PyQt6.QtCore import QSize, QFileInfo, Qt


def create_toolbar(parent) -> tuple[QToolBar, dict[str, QAction]]:
    """创建工具栏，返回 (toolbar, actions_dict)。"""
    toolbar = QToolBar('主工具栏', parent)
    toolbar.setObjectName('mainToolbar')
    toolbar.setMovable(False)
    toolbar.setIconSize(QSize(20, 20))
    # 图标+文字并排（py 图标按钮需要；emoji 按钮无图标只显示文字，行为一致）
    toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)

    actions: dict[str, QAction] = {}

    actions['new'] = _add_btn(toolbar, '新建', '📄', '新建表格')
    actions['open'] = _add_btn(toolbar, '打开', '📂', '打开文件')
    actions['save'] = _add_btn(toolbar, '保存', '💾', '保存')
    actions['dynamic'] = _add_py_icon_btn(toolbar, '动态脚本', '动态脚本模式')
    toolbar.addSeparator()
    actions['cut'] = _add_btn(toolbar, '剪切', '✂️', '剪切')
    actions['copy'] = _add_btn(toolbar, '复制', '📋', '复制')
    actions['paste'] = _add_btn(toolbar, '粘贴', '📌', '粘贴')
    toolbar.addSeparator()
    actions['insert_row'] = _add_btn(toolbar, '插入行', '⬇️', '插入行')
    actions['insert_col'] = _add_btn(toolbar, '插入列', '➡️', '插入列')
    toolbar.addSeparator()
    actions['pad_decimals'] = _add_btn(toolbar, '小数补齐', '🔟', '补齐选中区域的小数位数')
    actions['deselect'] = _add_btn(toolbar, '取消选中', '🚫', '取消所有选中')

    return toolbar, actions


def _add_btn(toolbar: QToolBar, text: str, icon: str, tooltip: str) -> QAction:
    action = QAction(f'{icon} {text}', toolbar)
    action.setToolTip(tooltip)
    toolbar.addAction(action)
    return action


def _add_py_icon_btn(toolbar: QToolBar, text: str, tooltip: str) -> QAction:
    """带 .py 文件系统图标的按钮（动态脚本，跟随系统图标，20px 对齐）。"""
    provider = QFileIconProvider()
    icon = provider.icon(QFileInfo('script.py'))
    action = QAction(icon, f' {text}', toolbar)
    action.setToolTip(tooltip)
    toolbar.addAction(action)
    return action
