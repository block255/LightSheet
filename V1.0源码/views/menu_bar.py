"""菜单栏构建。"""
from PyQt6.QtWidgets import QMenuBar, QMenu
from PyQt6.QtGui import QAction, QKeySequence


def create_menu_bar(parent) -> tuple[QMenuBar, dict[str, QAction]]:
    """创建菜单栏，返回 (menu_bar, actions_dict)。"""
    menu_bar = QMenuBar(parent)
    actions: dict[str, QAction] = {}

    # --- 文件菜单 ---
    file_menu = menu_bar.addMenu('文件(&F)')

    act = _add_action(file_menu, '新建(&N)', QKeySequence.StandardKey.New)
    actions['new'] = act

    act = _add_action(file_menu, '打开(&O)...', QKeySequence.StandardKey.Open)
    actions['open'] = act

    file_menu.addSeparator()

    act = _add_action(file_menu, '保存(&S)', QKeySequence.StandardKey.Save)
    actions['save'] = act

    act = _add_action(file_menu, '另存为(&A)...', QKeySequence('Ctrl+Shift+S'))
    actions['save_as'] = act

    file_menu.addSeparator()

    # 导出子菜单
    export_menu = file_menu.addMenu('导出为')
    act = _add_action(export_menu, 'CSV 文件 (.csv)')
    actions['export_csv'] = act
    act = _add_action(export_menu, 'Excel 文件 (.xlsx)')
    actions['export_xlsx'] = act
    act = _add_action(export_menu, '文本文件 (.txt)')
    actions['export_txt'] = act

    file_menu.addSeparator()

    act = _add_action(file_menu, '退出(&X)', QKeySequence('Alt+F4'))
    actions['exit'] = act

    # --- 编辑菜单 ---
    edit_menu = menu_bar.addMenu('编辑(&E)')

    act = _add_action(edit_menu, '撤销(&Z)', QKeySequence.StandardKey.Undo)
    actions['undo'] = act

    edit_menu.addSeparator()

    act = _add_action(edit_menu, '剪切(&X)', QKeySequence.StandardKey.Cut)
    actions['cut'] = act

    act = _add_action(edit_menu, '复制(&C)', QKeySequence.StandardKey.Copy)
    actions['copy'] = act

    act = _add_action(edit_menu, '粘贴(&V)', QKeySequence.StandardKey.Paste)
    actions['paste'] = act

    act = _add_action(edit_menu, '删除', QKeySequence.StandardKey.Delete)
    actions['delete'] = act

    edit_menu.addSeparator()

    act = _add_action(edit_menu, '插入行', QKeySequence('Ctrl+Shift++'))
    actions['insert_row'] = act

    act = _add_action(edit_menu, '插入列', QKeySequence('Ctrl+Shift+Ins'))
    actions['insert_col'] = act

    act = _add_action(edit_menu, '删除行', QKeySequence('Ctrl+-'))
    actions['remove_row'] = act

    act = _add_action(edit_menu, '删除列', QKeySequence('Ctrl+Shift+-'))
    actions['remove_col'] = act

    # --- 视图菜单 ---
    view_menu = menu_bar.addMenu('视图(&V)')

    act = _add_action(view_menu, '编辑模式', QKeySequence('Ctrl+E'))
    act.setCheckable(True)
    act.setChecked(True)
    actions['toggle_edit_mode'] = act

    view_menu.addSeparator()

    act = _add_action(view_menu, '刷新左侧面板', QKeySequence.StandardKey.Refresh)
    actions['refresh_panel'] = act

    # --- 帮助菜单 ---
    help_menu = menu_bar.addMenu('帮助(&H)')

    act = _add_action(help_menu, '教程(&T)')
    actions['tutorial'] = act

    help_menu.addSeparator()

    act = _add_action(help_menu, '关于(&A)')
    actions['about'] = act

    return menu_bar, actions


def _add_action(menu: QMenu, text: str, shortcut=None) -> QAction:
    """辅助：创建并添加一个 QAction。"""
    if shortcut:
        action = QAction(text, menu)
        action.setShortcut(shortcut)
    else:
        action = QAction(text, menu)
    menu.addAction(action)
    return action
