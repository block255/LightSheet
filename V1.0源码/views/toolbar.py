"""工具栏构建。"""
from PyQt6.QtWidgets import QToolBar
from PyQt6.QtGui import QAction
from PyQt6.QtCore import QSize


def create_toolbar(parent) -> tuple[QToolBar, dict[str, QAction]]:
    """创建工具栏，返回 (toolbar, actions_dict)。"""
    toolbar = QToolBar('主工具栏', parent)
    toolbar.setObjectName('mainToolbar')
    toolbar.setMovable(False)
    toolbar.setIconSize(QSize(20, 20))

    actions: dict[str, QAction] = {}

    actions['new'] = _add_btn(toolbar, '新建', '📄', '新建表格')
    actions['open'] = _add_btn(toolbar, '打开', '📂', '打开文件')
    actions['save'] = _add_btn(toolbar, '保存', '💾', '保存')
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
