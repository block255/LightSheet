"""自定义运算 — 编辑器（积木区渲染 + 交互）。

基于 QGraphicsScene/QGraphicsView 实现自由画布积木编辑器。
设计文档见 参考信息库/自定义运算/。
"""
from __future__ import annotations

from PyQt6.QtWidgets import (
    QDialog, QGraphicsScene, QGraphicsView, QVBoxLayout, QHBoxLayout,
    QGraphicsItem, QGraphicsRectItem, QGraphicsTextItem, QGraphicsObject,
    QPushButton, QLabel, QGraphicsSceneMouseEvent, QWidget,
)
from PyQt6.QtCore import Qt, QRectF, QPointF, pyqtSignal
from PyQt6.QtGui import QColor, QPen, QBrush, QFont

from custom_calc.model import BlockType, CalcSubtype, SymKind, BlockNode


# ----------------------------------------------------------------------
# 积木配色（颜色区分积木类型）
# ----------------------------------------------------------------------

BLOCK_COLORS = {
    BlockType.CALC:   QColor('#aec6cf'),   # 浅蓝
    BlockType.SYMBOL: QColor('#ffb3ba'),   # 浅粉
    BlockType.PAREN:  QColor('#b5e7a0'),   # 浅绿
    BlockType.COUNT:  QColor('#ffd8b1'),   # 浅橙
    BlockType.CHECK:  QColor('#e6b3ff'),   # 浅紫
    BlockType.OUTPUT: QColor('#ffffb3'),   # 浅黄
}

OUTLINE_COLOR = QColor('#555555')
PENDING_COLOR = QColor('#ff6b6b')   # 待定义接口/临时连接（红）
TEMP_CONNECT = QColor('#ff0000')    # 临时连接红虚线

FONT = QFont('Microsoft YaHei', 9)


# ----------------------------------------------------------------------
# 积木图形项
# ----------------------------------------------------------------------

class BlockItem(QGraphicsObject):
    """一个积木的图形项。子接口/子积木内嵌渲染，尺寸随结构自适应。"""

    clicked = pyqtSignal(object, str)      # (item, 'left'|'right')
    moved = pyqtSignal(object, QPointF)    # (item, 新位置)
    drag_finished = pyqtSignal(object, QPointF)  # (item, 松开位置)
    drag_moved = pyqtSignal(object, QPointF)     # (item, 拖拽中位置) 高亮接口

    _H = 34           # 积木默认高
    _H_TALL = 48      # 容器型积木高（括号/计数/检定/输出，上下露出留白）
    _NUM_W = 88       # 数元接口小积木宽
    _PAD = 8          # 内部留白
    _GAP = 8          # 元素间距

    def __init__(self, node: BlockNode, parent=None):
        super().__init__(parent)
        self._node = node
        self._press_pos = QPointF()
        self._dragging = False
        self._interfaces: list[InterfaceItem] = []
        self._content_right = 0.0    # 内容右边界（relayout 计算）
        self._height = self._layout_height()
        self._label_x: dict = {}     # 标签流式位置（relayout 计算，paint 用）
        self.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemIsMovable
            | QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
            | QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges
        )
        self.setZValue(node.updated_seq)
        self._build_interfaces()
        self._relayout()

    def _layout_height(self) -> int:
        """积木基础高度：容器型（括号/计数/检定/输出）更高。"""
        if self._node.type in (BlockType.PAREN, BlockType.COUNT,
                               BlockType.CHECK, BlockType.OUTPUT):
            return self._H_TALL
        return self._H

    # ------------------------------------------------------------------
    # 布局：动态重排（嵌入/拖出后按 node 内容重新排布）
    # ------------------------------------------------------------------

    def _build_interfaces(self):
        """按 node 结构创建接口（位置由 _relayout 统一排布）。

        括号为动态链式：children 中每个占位节点对应一个接口
        （值位占位 → 计算元接口；符号位占位 → 符号接口）。
        其他积木为固定槽：接口由 _interface_layout 定义。
        """
        self._interfaces = []
        n = self._node
        if n.type == BlockType.PAREN:
            # 链式：children 中每个接口占位 → 一个接口
            # 接口占位 = pending_interface（is_interface）或 未定义符号（sym_value=None）
            # 注：未定义数元（NUM+data 未定义）是真实链成员，不是接口占位
            for idx, child in enumerate(n.children):
                is_iface = child.is_interface or \
                    (child.type == BlockType.SYMBOL and child.sym_value is None)
                if not is_iface:
                    continue
                if child.type == BlockType.SYMBOL:
                    iface = InterfaceItem(self, ('children', idx), kind='sym',
                                          node_ref=child)
                else:
                    iface = InterfaceItem(self, ('children', idx), kind='slot')
                iface.setPos(0, 0)
                self._interfaces.append(iface)
            return
        for slot, kind, node_ref, x in self._interface_layout():
            iface = InterfaceItem(self, slot, kind=kind, node_ref=node_ref)
            iface.setPos(x, 0)   # 初始位置，relayout 会重排
            self._interfaces.append(iface)

    def _rebuild_interfaces(self):
        """重建接口（children 结构变化后调用），同步场景注册。

        setParentItem(None) 必须无条件执行：__init__ 时积木还没加入场景
        （self.scene() 为 None），若放在 scene 判断内会残留旧接口。
        """
        scene = self.scene()
        for iface in self._interfaces:
            iface.setParentItem(None)   # 从父积木分离（接口是子项）
            if isinstance(scene, BlockScene):
                scene.unregister_interface(iface)
                scene.removeItem(iface)
        self._interfaces = []
        self._build_interfaces()
        if isinstance(scene, BlockScene):
            for iface in self._interfaces:
                scene.register_interface(iface)
                iface.clicked.connect(scene._on_interface_clicked)

    def _iface_for_slot(self, slot) -> 'InterfaceItem | None':
        """按 slot 查找接口。"""
        for iface in self._interfaces:
            if iface.slot == slot:
                return iface
        return None

    def _relayout(self):
        """重排内部：接口可见性/位置 + 子积木归位 + 尺寸留白。

        链式框架：嵌入子积木后，被占用槽位的接口隐藏，
        括号链式接口移到链末尾；子积木按位置排列；
        母积木宽高随内容动态调整，保证明显边缘留白。
        """
        self._rebuild_interfaces()
        n = self._node
        # 子积木映射：node id -> BlockItem（childItems 里）
        child_map = {}
        for c in self.childItems():
            if isinstance(c, BlockItem):
                child_map[id(c.node)] = c

        max_h = 0.0   # 内容高度（不含基础高，留白统一加）
        content_right = 0.0

        def _place_item(item, x):
            """放置一个图形项，返回其右边界与高度。"""
            r = x + item.boundingRect().width()
            h = item.boundingRect().height()
            return r, h

        if n.type == BlockType.PAREN:
            # 链式：children 逐个排布（占位→接口，实际积木→子积木）
            # 接口应在链尾（右侧）：空括号时接口在积木右侧基准位
            x = self._PAD
            if all(c.is_interface for c in n.children):
                # 空括号：接口直接放右侧基准（不在左侧）
                x = self._layout_width() - 34
            for idx, child in enumerate(n.children):
                is_iface = child.is_interface or \
                    (child.type == BlockType.SYMBOL and child.sym_value is None)
                if is_iface:
                    iface = self._iface_for_slot(('children', idx))
                    if iface is None:
                        continue
                    iface.setVisible(True)
                    iface.setPos(x, 0)
                    right, h = _place_item(iface, x)
                else:
                    ci = child_map.get(id(child))
                    if ci is None:
                        continue
                    ci.setVisible(True)
                    ci.setPos(x, 0)
                    right, h = _place_item(ci, x)
                x = right + self._GAP
                content_right = max(content_right, right)
                max_h = max(max_h, h)
        else:
            # 固定槽（指数/对数/三角/计数/检定/输出/数元）：流式排布
            # 结构序列 [(标签宽 或 None, slot)]，x 从 PAD 累加，
            # 子积木占实际宽度，接口占接口宽，标签画在对应位置
            self._label_x = {}   # slot -> 标签中心 x（paint 用）
            # 输出积木：接口内嵌右侧（左端显示输出位置标签），不从 PAD 起
            if n.type == BlockType.OUTPUT:
                x = self._layout_width() - 34
            else:
                x = self._PAD
            for label_w, slot in self._fixed_slots():
                if label_w is not None:
                    self._label_x[slot] = x + label_w / 2
                    x += label_w + self._GAP
                occupied_child = self._slot_child(slot, child_map)
                if occupied_child is not None:
                    iface = self._iface_for_slot(slot)
                    if iface is not None:
                        iface.setVisible(False)
                    occupied_child.setPos(x, 0)
                    right, h = _place_item(occupied_child, x)
                else:
                    iface = self._iface_for_slot(slot)
                    if iface is None:
                        continue
                    iface.setVisible(True)
                    iface.setPos(x, 0)
                    right, h = _place_item(iface, x)
                x = right + self._GAP
                content_right = max(content_right, right)
                max_h = max(max_h, h)
            # 数元 data 槽（NUM 无独立接口，接入积木后子积木内嵌显示）
            data_child = self._slot_child(('data',), child_map)
            if data_child is not None:
                data_child.setPos(self._PAD, 0)
                right, h = _place_item(data_child, self._PAD)
                content_right = max(content_right, right)
                max_h = max(max_h, h)

        # 尺寸：内容 + 边缘留白（明显留白）
        self._content_right = content_right
        self._height = max(self._layout_height(), max_h + 2 * self._PAD)
        self.prepareGeometryChange()
        self.update()

    def _fixed_slots(self) -> list:
        """固定槽积木的结构序列：[(标签宽 或 None, slot)]，流式排布用。

        标签用 slot=None 占位（实际是 (标签宽, None)），排布时推进 x，
        paint 用 _label_x[None] 定位标签。设计记录（01-积木类型.md 57-64 行）。
        """
        n = self._node
        if n.type == BlockType.CALC:
            if n.calc_subtype == CalcSubtype.EXP:
                # [数元] ^ [数元]
                return [(None, ('children', 0)), (20, None), (None, ('children', 1))]
            if n.calc_subtype == CalcSubtype.LOG:
                # log [数元] [数元]
                return [(34, None), (None, ('children', 0)), (None, ('children', 1))]
            if n.calc_subtype == CalcSubtype.TRIG:
                # sin [数元]
                return [(46, None), (None, ('children', 0))]
            return []
        if n.type in (BlockType.COUNT, BlockType.CHECK):
            # 计算元 逻辑符号 计算元
            return [(None, ('children', 0)), (None, ('children', 1)),
                    (None, ('children', 2))]
        if n.type == BlockType.OUTPUT:
            return [(None, ('output',))]
        return []

    def _relayout_propagate(self):
        """自身 relayout + 向上传播：本积木尺寸变化后，
        父积木链逐级 relayout（重新包裹 + 同级重排），直到顶层。

        带 seen 集合防环：若图形父子异常成环（理论不应发生，Qt 父子环
        会卡死），循环不会无限进行。
        """
        self._relayout()
        cur = self.parentItem()
        seen = set()
        while isinstance(cur, BlockItem) and id(cur) not in seen:
            seen.add(id(cur))
            cur._relayout()
            cur = cur.parentItem()

    @staticmethod
    def _is_placeholder(node) -> bool:
        """是否为占位接口节点（空槽）。"""
        if node is None:
            return True
        if node.is_interface:
            return True
        # 未定义数元（NUM + data 未定义）也是占位
        if node.type == BlockType.CALC and node.calc_subtype == CalcSubtype.NUM:
            d = node.data
            return d is None or not d.is_defined
        # 未定义符号也是占位
        if node.type == BlockType.SYMBOL:
            return node.sym_value is None
        return False

    @staticmethod
    def _is_value_kind(node) -> bool:
        """是否为链式"值"积木（计算元/括号/计数/检定）。"""
        return node.type in (BlockType.CALC, BlockType.PAREN,
                             BlockType.COUNT, BlockType.CHECK)

    @staticmethod
    def _placeholder_for(node) -> BlockNode:
        """按被拖出积木类型生成对应占位接口节点：
        值积木 → 计算元占位；符号积木 → 符号占位。"""
        if node.type == BlockType.SYMBOL:
            return BlockNode(type=BlockType.SYMBOL)
        return BlockNode(type=BlockType.CALC, state='pending_interface')

    def _slot_child(self, slot, child_map) -> BlockItem | None:
        """槽位对应的已占用子积木（BlockItem），空槽返回 None。

        占用判定：优先看有无图形子项（child_map）——用户拖入的积木
        即使未定义（计算元胚/未定义数元）也算占用，母积木要包住它
        （否则类型切换后尺寸回缩）；无图形子项的原生接口
        （如 make_calc_num 内嵌数元）才是空槽（显示接口）。
        """
        n = self._node
        if slot is None:
            return None
        if slot[0] == 'children':
            idx = slot[1]
            if isinstance(idx, tuple):   # 缝隙嵌入槽：动态链，不算占用
                return None
            if idx < len(n.children):
                child = n.children[idx]
                # 数元节点接入积木：node_ref 本体不在 child_map，
                # 应返回 data.block 对应的积木 BlockItem
                if child.type == BlockType.CALC \
                        and child.calc_subtype == CalcSubtype.NUM \
                        and child.data is not None \
                        and getattr(child.data, 'block', None) is not None:
                    return child_map.get(id(child.data.block))
                found = child_map.get(id(child))
                if found is not None:
                    return found   # 已拖入的图形子项：未定义也算占用（要包住）
                if not self._is_placeholder(child):
                    return None    # 真实成员但无图形子项（异常兜底）
        elif slot[0] == 'output':
            if n.children:
                child = n.children[0]
                found = child_map.get(id(child))
                if found is not None:
                    return found
                if not self._is_placeholder(child):
                    return None
        elif slot[0] == 'data':
            if n.data is not None and getattr(n.data, 'block', None) is not None:
                return child_map.get(id(n.data.block))
        return None

    def _interface_layout(self) -> list:
        """接口布局：返回 [(slot, kind, node_ref, x)]，x 为相对父的 x 坐标。

        设计记录（01-积木类型.md 57-64 行视觉示意）：
        - 数元 → 无独立接口（自身就是数元接口）
        - 指数 → [数元] ^ [数元]；对数 → log [数元] [数元]；三角 → sin [数元]
        - 括号 → 链式积木接口；计数/检定 → 计算元 逻辑符号 计算元
        - 输出 → 1 个计算元接口（内嵌右侧）
        """
        n = self._node
        W = self._NUM_W
        if n.type == BlockType.CALC:
            if n.calc_subtype == CalcSubtype.NUM:
                return []   # 数元积木自身就是数元接口
            if n.calc_subtype == CalcSubtype.EXP:
                # [数元] ^ [数元]
                c0 = n.children[0] if len(n.children) > 0 else None
                c1 = n.children[1] if len(n.children) > 1 else None
                return [
                    (('children', 0), 'num', c0, 8),
                    (('children', 1), 'num', c1, 8 + W + 12 + 20 + 8),
                ]
            if n.calc_subtype == CalcSubtype.LOG:
                # log [数元] [数元]
                c0 = n.children[0] if len(n.children) > 0 else None
                c1 = n.children[1] if len(n.children) > 1 else None
                x0 = 8 + 34 + 8   # log 标签占 34
                return [
                    (('children', 0), 'num', c0, x0),
                    (('children', 1), 'num', c1, x0 + W + 8),
                ]
            if n.calc_subtype == CalcSubtype.TRIG:
                # sin [数元]
                c0 = n.children[0] if len(n.children) > 0 else None
                return [
                    (('children', 0), 'num', c0, 8 + 46 + 8),
                ]
            return []   # 胚计算元：待选子类后才有接口
        if n.type == BlockType.PAREN:
            # 括号：内部偏右放置链式积木接口（内收，容器型）
            return [(('children', 'append'), 'slot', None,
                     self._layout_width() - 34)]
        if n.type in (BlockType.COUNT, BlockType.CHECK):
            # 设计记录（01-积木类型.md 101-127 行）：计算元 逻辑符号 计算元
            # 左计算元（数元接口） + 中间逻辑符号（符号接口） + 右计算元
            c0 = n.children[0] if len(n.children) > 0 else None
            c1 = n.children[1] if len(n.children) > 1 else None
            c2 = n.children[2] if len(n.children) > 2 else None
            x2 = 8 + W + 8 + 36 + 8   # 右数元：符号接口之后
            return [
                (('children', 0), 'num', c0, 8),
                (('children', 1), 'sym', c1, 8 + W + 8),
                (('children', 2), 'num', c2, x2),
            ]
        if n.type == BlockType.OUTPUT:
            # 输出积木：1 个计算元接口（内嵌右侧，容器型）
            return [(('output',), 'slot', None, self._layout_width() - 34)]
        return []

    @property
    def interfaces(self) -> list['InterfaceItem']:
        return list(self._interfaces)

    # ------------------------------------------------------------------
    # 图形（尺寸随结构自适应）
    # ------------------------------------------------------------------

    def boundingRect(self) -> QRectF:
        # 宽度 = 内容右边界 + 右留白（内容驱动，保证明显边缘留白）
        w = max(self._layout_width(),
                self._content_right + self._PAD)
        return QRectF(0, -self._height / 2, w, self._height)

    def _layout_width(self) -> int:
        """积木宽度：按类型/子接口布局计算。"""
        n = self._node
        W = self._NUM_W
        if n.type == BlockType.CALC:
            if n.calc_subtype == CalcSubtype.NUM:
                return W
            if n.calc_subtype == CalcSubtype.EXP:
                return 8 + W + 12 + 20 + 8 + W + 8
            if n.calc_subtype == CalcSubtype.LOG:
                return 8 + 34 + 8 + W + 8 + W + 8
            if n.calc_subtype == CalcSubtype.TRIG:
                return 8 + 46 + 8 + W + 8
            return 80   # 胚计算元
        if n.type == BlockType.SYMBOL:
            return 44
        if n.type == BlockType.PAREN:
            return 120   # 括号做大（容器型，内嵌子积木）
        if n.type in (BlockType.COUNT, BlockType.CHECK):
            return 8 + W + 8 + 36 + 8 + W + 8
        if n.type == BlockType.OUTPUT:
            return 80    # 输出做大（容器型）
        return 60

    def paint(self, painter, option, widget=None):
        color = BLOCK_COLORS.get(self._node.type, QColor('#cccccc'))
        painter.setBrush(QBrush(color))
        # 待定义接口 / 临时连接用红色虚线
        if self._node.is_interface or self._node.is_temp_connect:
            pen = QPen(PENDING_COLOR if self._node.is_interface else TEMP_CONNECT)
            pen.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(pen)
        else:
            painter.setPen(QPen(OUTLINE_COLOR, 1))
        # 括号用长条（圆角矩形），其他用圆角矩形
        rect = self.boundingRect()
        if self._node.type == BlockType.PAREN:
            painter.drawRoundedRect(rect, 8, 8)
        else:
            painter.drawRoundedRect(rect, 5, 5)
        # 主体文本
        painter.setPen(QColor('#222222'))
        painter.setFont(FONT)
        label = self._label()
        # 对数/三角/指数：标签画在流式排布的位置（_label_x）
        st = self._node.calc_subtype if self._node.type == BlockType.CALC else None
        lx = getattr(self, '_label_x', None) or {}
        if st == CalcSubtype.LOG:
            cx = lx.get(None)
            if cx is None:
                cx = 6 + 17
            painter.drawText(QRectF(cx - 20, rect.top(), 40, rect.height()),
                             Qt.AlignmentFlag.AlignCenter, 'log')
        elif st == CalcSubtype.TRIG:
            cx = lx.get(None)
            if cx is None:
                cx = 6 + 23
            painter.drawText(QRectF(cx - 23, rect.top(), 46, rect.height()),
                             Qt.AlignmentFlag.AlignCenter,
                             self._node.trig_func or 'sin')
        elif st == CalcSubtype.EXP:
            cx = lx.get(None)
            if cx is None:
                cx = 8 + self._NUM_W + 8 + 10
            painter.drawText(QRectF(cx - 10, rect.top(), 20, rect.height()),
                             Qt.AlignmentFlag.AlignCenter, '^')
        elif self._node.type == BlockType.OUTPUT:
            # 输出积木：左端显示输出位置（像 log 首部），不再显示"输出"
            out_label = self._output_label()
            painter.drawText(QRectF(6, rect.top(), 40, rect.height()),
                             Qt.AlignmentFlag.AlignCenter, out_label)
        else:
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, label)

    def _label(self) -> str:
        n = self._node
        if n.type == BlockType.CALC:
            if n.calc_subtype == CalcSubtype.NUM:
                return self._data_label(n)
            if n.calc_subtype == CalcSubtype.EXP:
                return '^'   # 在接口之间（居中文本由布局保证）
            if n.calc_subtype == CalcSubtype.LOG:
                return 'log'
            if n.calc_subtype == CalcSubtype.TRIG:
                return n.trig_func or 'sin'   # 正常有函数名
            return '计算元?'   # 胚积木：待选子类
        if n.type == BlockType.SYMBOL:
            return n.sym_value or '符号?'   # 胚积木：待选符号
        if n.type == BlockType.PAREN:
            # 设计记录（01-积木类型.md）：空括号带圆角长条，不画括号符号；
            # 层级用长条大小和长度区分。空括号显示「括号」，有内容显示「括号组」。
            real = [c for c in n.children if not c.is_interface]
            return '括号' if not real else '括号组'
        if n.type == BlockType.COUNT:
            return '计数'
        if n.type == BlockType.CHECK:
            return '检定'
        if n.type == BlockType.OUTPUT:
            return '输出'
        return '?'

    def _data_label(self, n) -> str:
        from custom_calc.model import InputKind
        d = n.data
        if d is None or not d.is_defined:
            return '数元?'
        if d.kind == InputKind.ROW:
            return f'行{d.index + 1}'
        if d.kind == InputKind.COL:
            from models.spreadsheet_model import SpreadsheetModel
            return f'列{SpreadsheetModel.col_letter(d.index)}'
        if d.kind == InputKind.CONST:
            return f'{d.value:g}'
        if d.kind == InputKind.CLIPBOARD:
            return '剪贴板'
        if d.kind == InputKind.WHOLE_TABLE:
            return '整个表格'
        if d.kind == InputKind.RANGE:
            return _range_short_label(d)
        if d.kind == InputKind.BLOCK:
            return '积木'
        return '数元?'

    def _output_label(self) -> str:
        """输出积木当前位置显示文字（未选 → '输出?'）。"""
        from custom_calc.model import OutputTarget
        from models.spreadsheet_model import SpreadsheetModel
        n = self._node
        t = n.output_target
        if t is None:
            return '输出?'
        if t == OutputTarget.CLIPBOARD:
            return '剪贴板'
        if t == OutputTarget.COL:
            return f'列{SpreadsheetModel.col_letter(n.output_index)}' \
                if n.output_index is not None else '列?'
        if t == OutputTarget.ROW:
            return f'行{n.output_index + 1}' \
                if n.output_index is not None else '行?'
        return '?'

    # ------------------------------------------------------------------
    # 事件（区分点击 vs 拖拽）
    # ------------------------------------------------------------------

    _DRAG_THRESHOLD = 5  # 移动超过 5px 视为拖拽

    def mousePressEvent(self, event: QGraphicsSceneMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_pos = event.scenePos()
            self._dragging = False
        elif event.button() == Qt.MouseButton.RightButton:
            self.clicked.emit(self, 'right')
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QGraphicsSceneMouseEvent):
        if event.buttons() & Qt.MouseButton.LeftButton:
            if not self._dragging:
                p0 = getattr(self, '_press_pos', event.scenePos())
                if (event.scenePos() - p0).manhattanLength() > self._DRAG_THRESHOLD:
                    self._dragging = True
            if getattr(self, '_dragging', False):
                # 拖拽中：通知场景高亮可接入的接口
                self.drag_moved.emit(self, event.scenePos())
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QGraphicsSceneMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            if getattr(self, '_dragging', False):
                self._dragging = False
                self.drag_finished.emit(self, event.scenePos())
            else:
                self.clicked.emit(self, 'left')
        super().mouseReleaseEvent(event)

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            self.moved.emit(self, value)
        return super().itemChange(change, value)

    @property
    def node(self) -> BlockNode:
        return self._node


# ----------------------------------------------------------------------
# 接口图形项（+号框）
# ----------------------------------------------------------------------

class InterfaceItem(QGraphicsObject):
    """接口：数元接口（内嵌小积木）/ 符号接口（符号框）/ 积木接口（+号框）。

    kind:
        'num'  = 数元接口：本身就是"待定义数元积木"（内嵌小积木形态），
                 点击 → 操作栏数元定义（输入行/列、常数、剪贴板、接入积木）
        'sym'  = 符号接口：显示逻辑/运算符号，点击 → 操作栏符号表
        'slot' = 积木接口：+号框，点击 → 操作栏「添加积木」「嵌入积木」

    slot: 描述该接口对应的树位置，如
        ('data',)             → 数元接口（计算元 NUM 的 data）
        ('children', 0)       → children[0]
        ('children', 'append')→ 链式末尾追加
        ('output',)           → 输出积木的计算元接口
    node_ref: 接口对应的子节点（children[i]）或 None（data 在父节点上）
    """

    clicked = pyqtSignal(object)      # (InterfaceItem) 左键点击
    dropped = pyqtSignal(object, object)   # (InterfaceItem, BlockItem) 拖入

    _S = 18          # +号框边长
    _NUM_W = 88      # 数元接口小积木宽
    _NUM_H = 30      # 数元接口小积木高
    _SYM_W = 36      # 符号接口框宽
    _SYM_H = 30      # 符号接口框高

    def __init__(self, parent_item: BlockItem = None, slot=None,
                 kind: str = 'slot', node_ref=None):
        super().__init__(parent_item)
        self.slot = slot
        self.kind = kind
        self.node_ref = node_ref
        self._highlight = False
        self.setAcceptHoverEvents(True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)

    def boundingRect(self) -> QRectF:
        if self.kind == 'num':
            return QRectF(0, -self._NUM_H / 2, self._NUM_W, self._NUM_H)
        if self.kind == 'sym':
            return QRectF(0, -self._SYM_H / 2, self._SYM_W, self._SYM_H)
        return QRectF(-self._S / 2, -self._S / 2, self._S, self._S)

    def paint(self, painter, option, widget=None):
        if self.kind == 'num':
            self._paint_num(painter)
        elif self.kind == 'sym':
            self._paint_sym(painter)
        else:
            self._paint_slot(painter)

    def _paint_num(self, painter):
        """数元接口：内嵌小积木（待定义数元积木形态）。"""
        painter.setBrush(QBrush(BLOCK_COLORS[BlockType.CALC]))
        painter.setPen(QPen(OUTLINE_COLOR, 1))
        painter.drawRoundedRect(self.boundingRect(), 4, 4)
        painter.setPen(QColor('#222222'))
        painter.setFont(FONT)
        painter.drawText(self.boundingRect(), Qt.AlignmentFlag.AlignCenter,
                         self._num_label())

    def _num_label(self) -> str:
        """数元接口显示：未定义 → '数元?'；已定义 → 数据内容或嵌入积木标签。"""
        n = self.node_ref
        if n is None:
            return '数元?'
        d = getattr(n, 'data', None)
        if d is None or not d.is_defined:
            return '数元?'
        from custom_calc.model import InputKind
        if d.kind == InputKind.ROW:
            return f'行{d.index + 1}'
        if d.kind == InputKind.COL:
            from models.spreadsheet_model import SpreadsheetModel
            return f'列{SpreadsheetModel.col_letter(d.index)}'
        if d.kind == InputKind.CONST:
            return f'{d.value:g}'
        if d.kind == InputKind.CLIPBOARD:
            return '剪贴板'
        if d.kind == InputKind.WHOLE_TABLE:
            return '整个表格'
        if d.kind == InputKind.RANGE:
            return _range_short_label(d)
        if d.kind == InputKind.BLOCK:
            # 接入积木：显示嵌入积木自身的标签（递归）
            if d.block is not None:
                return _node_short_label(d.block)
            return '积木?'
        return '数元?'

    def _paint_sym(self, painter):
        """符号接口：显示当前符号（未定义 → '?'）。"""
        painter.setBrush(QBrush(BLOCK_COLORS[BlockType.SYMBOL]))
        painter.setPen(QPen(OUTLINE_COLOR, 1))
        painter.drawRoundedRect(self.boundingRect(), 4, 4)
        painter.setPen(QColor('#222222'))
        painter.setFont(FONT)
        painter.drawText(self.boundingRect(), Qt.AlignmentFlag.AlignCenter,
                         self._sym_label())

    def _sym_label(self) -> str:
        """符号接口显示：node_ref.sym_value 或 '?'。"""
        n = self.node_ref
        if n is None:
            return '?'
        return n.sym_value or '?'

    def _paint_slot(self, painter):
        """积木接口：+号框。"""
        painter.setPen(QPen(QColor('#888888'), 1))
        if self._highlight:
            painter.setBrush(QBrush(QColor('#ffd700')))  # 高亮金色
        else:
            painter.setBrush(QBrush(QColor('#f0f0f0')))
        painter.drawRect(self.boundingRect())
        # 加号
        painter.setPen(QPen(QColor('#333333'), 2))
        c = self._S / 2
        painter.drawLine(QPointF(-self._S / 4, 0), QPointF(self._S / 4, 0))
        painter.drawLine(QPointF(0, -self._S / 4), QPointF(0, self._S / 4))

    def set_highlight(self, on: bool):
        self._highlight = on
        self.update()

    def hoverEnterEvent(self, event):
        self.set_highlight(True)
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        self.set_highlight(False)
        super().hoverLeaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self)
            event.accept()
            return
        super().mousePressEvent(event)


# ----------------------------------------------------------------------
# 积木场景
# ----------------------------------------------------------------------

class BlockScene(QGraphicsScene):
    """积木场景：管理积木项、空选/选中状态。"""

    item_clicked = pyqtSignal(object, str)   # (BlockItem, 'left'|'right')
    interface_clicked = pyqtSignal(object)   # (InterfaceItem) 点击接口
    blank_clicked = pyqtSignal()             # 点击空白处（空选）
    blank_right_clicked = pyqtSignal(object)  # (场景坐标) 右键空白处
    item_position_changed = pyqtSignal(object)
    drop_on_interface = pyqtSignal(object, object)  # (BlockItem, InterfaceItem)
    detach_requested = pyqtSignal(object, object)   # (BlockItem, 父BlockItem)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items: list[BlockItem] = []
        self._interfaces: list[InterfaceItem] = []

    def add_block(self, node: BlockNode, pos: QPointF = None) -> BlockItem:
        """添加一个积木到场景（含其子接口注册）。"""
        item = BlockItem(node)
        if pos is not None:
            item.setPos(pos)
        else:
            item.setPos(20 + 20 * len(self._items), 20 + 20 * len(self._items))
        self.addItem(item)
        self._items.append(item)
        for iface in item.interfaces:
            self.register_interface(iface)
            iface.clicked.connect(self._on_interface_clicked)
        item.clicked.connect(self._on_item_clicked)
        item.moved.connect(self._on_item_moved)
        item.drag_finished.connect(self._on_drag_finished)
        item.drag_moved.connect(self._on_drag_moved)
        return item

    def _on_drag_moved(self, item: BlockItem, scene_pos: QPointF):
        """拖拽移动中：高亮当前可接入的接口。"""
        self._highlight_drag_target(scene_pos, item)

    def _on_interface_clicked(self, iface: InterfaceItem):
        self.interface_clicked.emit(iface)

    def register_interface(self, iface: InterfaceItem) -> None:
        """登记一个接口（用于拖拽检测）。"""
        self._interfaces.append(iface)

    def rebuild_interfaces(self, item: BlockItem) -> None:
        """重建积木的子接口（类型切换后 children 结构变化时调用）。

        同时释放旧 children 的图形父子（类型切换后旧子积木脱离，
        其 BlockItem 回到画布顶层，不残留贴图）。
        """
        # 释放旧子积木的图形父子（回画布顶层，数据已脱离）
        for c in list(item.childItems()):
            if isinstance(c, BlockItem) and c is not item:
                c.setParentItem(None)
        for iface in list(item.interfaces):
            self.unregister_interface(iface)
            iface.setParentItem(None)
            self.removeItem(iface)
        item._interfaces = []
        item._build_interfaces()
        for iface in item.interfaces:
            self.register_interface(iface)
            iface.clicked.connect(self._on_interface_clicked)

    def unregister_interface(self, iface: InterfaceItem) -> None:
        if iface in self._interfaces:
            self._interfaces.remove(iface)

    def remove_block(self, item: BlockItem) -> None:
        if item in self._items:
            self._items.remove(item)
        for iface in list(item.interfaces):
            self.unregister_interface(iface)
        # 若是子积木（被嵌入），先解除图形父子
        if item.parentItem() is not None:
            item.setParentItem(None)
        # 递归解除其子积木的父子关系（随母一起移除）
        for child in list(item.childItems()):
            if isinstance(child, BlockItem):
                child.setParentItem(None)
        self.removeItem(item)

    def clear_blocks(self) -> None:
        # 先解除所有父子关系（子积木回顶层），再统一移除，避免 removeItem 报错
        for item in list(self._items):
            if item.parentItem() is not None:
                item.setParentItem(None)
            for c in list(item.childItems()):
                if isinstance(c, BlockItem):
                    c.setParentItem(None)
        for item in list(self._items):
            for iface in list(item.interfaces):
                self.unregister_interface(iface)
            self.removeItem(item)
        self._items.clear()
        self._interfaces.clear()

    def items(self) -> list[BlockItem]:
        return list(self._items)

    def interface_at(self, scene_pos: QPointF,
                     item: BlockItem = None) -> InterfaceItem | None:
        """检测场景坐标处是否有接口（综合判定）。

        - scene_pos：鼠标松开点（必须落在接口判定半径内）
        - item：拖动的积木（可选）；提供时额外要求积木本体与接口区域相交，
          避免大积木路过接口边缘误触（手感：只有积木盖到接口才算拖到）
        判定半径 = 接口宽/2 + 4。
        """
        for iface in self._interfaces:
            # 接口可能挂在积木子项下，用 mapToScene 计算全局位置
            global_pos = iface.mapToScene(iface.boundingRect().center())
            r = iface.boundingRect().width() / 2 + 4
            if (scene_pos - global_pos).manhattanLength() > r:
                continue
            if item is not None:
                # 综合判定：积木本体（场景坐标）与接口区域相交
                iface_rect = iface.mapToScene(iface.boundingRect()).boundingRect()
                item_rect = item.mapToScene(item.boundingRect()).boundingRect()
                if not item_rect.intersects(iface_rect):
                    continue
            return iface
        return None

    def _highlight_drag_target(self, scene_pos: QPointF,
                               item: BlockItem) -> InterfaceItem | None:
        """拖拽过程中：检测当前鼠标位置可接入的接口并高亮。

        返回命中的接口（供松开时嵌入）；未命中清除所有高亮。
        """
        iface = self.interface_at(scene_pos, item)
        for other in self._interfaces:
            other.set_highlight(other is iface)
        return iface

    def _on_drag_finished(self, item: BlockItem, scene_pos: QPointF):
        """拖拽松开：拖到接口→接入；否则已接入的积木→拖出（解绑）。

        判定：鼠标松开点落在接口半径内 且 积木本体与接口相交（综合判定）。
        兜底：即使数据层找不到父（数据/图形可能不同步），
        只要图形上有父积木（parentItem 是 BlockItem），拖到空白处也应拖出
        （解除图形父子），避免积木"看似拖出实则仍挂在父下跟着移动"。
        """
        # 清除拖拽高亮
        for other in self._interfaces:
            other.set_highlight(False)
        iface = self.interface_at(scene_pos, item)
        # 判定"是否自己的接口"：接口挂在 item 自身之下即为自己的接口
        # （不能只与第一个自己的接口比较——多接口积木（计数/检定有 3 个）
        #  拖到自己第 2/3 个接口会被误判为"拖到别的接口"→ 触发循环嵌套误报）
        if iface is not None and not self._is_own_interface(item, iface):
            self.drop_on_interface.emit(item, iface)
        else:
            # 未拖到接口：若该积木已接入某父积木，则拖出（解绑）
            parent = self._find_parent_block(item.node)
            if parent is None and isinstance(item.parentItem(), BlockItem):
                # 数据找不到父但图形有父：按图形父拖出（兜底，防不同步残留）
                parent = item.parentItem()
            if parent is not None:
                self.detach_requested.emit(item, parent)

    @staticmethod
    def _is_own_interface(item: BlockItem, iface: InterfaceItem) -> bool:
        """iface 是否挂在 item 自身之下（拖到自己接口不算接入）。"""
        return iface.parentItem() is item

    def _find_parent_block(self, node) -> BlockItem | None:
        """查找 node 所属的父积木（在场景里找）。

        覆盖三种接入位置：
        - n.children（链式/固定槽子积木）
        - n.data.block（数元积木自身接入）
        - n.children[i].data.block（数元接口接入）
        """
        for other in self._items:
            n = other.node
            if n is node:
                continue
            if node in n.children:
                return other
            if n.data is not None and getattr(n.data, 'block', None) is node:
                return other
            # 数元接口（固定槽 children[i] 的数元节点）接入的积木
            for ch in n.children:
                if ch is not None and ch.type == BlockType.CALC \
                        and ch.calc_subtype == CalcSubtype.NUM \
                        and ch.data is not None \
                        and getattr(ch.data, 'block', None) is node:
                    return other
        return None

    def _find_own_interface(self, item: BlockItem) -> InterfaceItem | None:
        """查找属于该积木自身的接口（拖到自己的接口不算接入）。"""
        for iface in self._interfaces:
            parent = iface.parentItem()
            if parent is item:
                return iface
        return None

    # ------------------------------------------------------------------
    # 事件
    # ------------------------------------------------------------------

    def mousePressEvent(self, event):
        # 点击空白处：左键 → 空选；右键 → 创建菜单
        item = self.itemAt(event.scenePos(), self.views()[0].transform()) \
            if self.views() else None
        if item is None and event.button() == Qt.MouseButton.LeftButton:
            self.blank_clicked.emit()
        elif item is None and event.button() == Qt.MouseButton.RightButton:
            self.blank_right_clicked.emit(event.scenePos())
            event.accept()
            return
        super().mousePressEvent(event)

    def _on_item_clicked(self, item, btn):
        self.item_clicked.emit(item, btn)

    def _on_item_moved(self, item, pos):
        # 同步 node 位置字段（撤销/重做快照依赖它记录积木位置）
        item.node.x = pos.x()
        item.node.y = pos.y()
        self.item_position_changed.emit(item)


# ----------------------------------------------------------------------
# 编辑器弹窗
# ----------------------------------------------------------------------

class CustomCalcEditor(QDialog):
    """自定义运算编辑器弹窗：左侧操作栏 + 右侧积木区。"""

    # 关闭时带出当前积木区数据（临时储存）
    result_blocks = pyqtSignal(list)   # list[BlockNode]

    def __init__(self, parent=None, direction: str = '', model=None):
        super().__init__(parent)
        self.setWindowTitle('自定义运算编辑器')
        # 支持最大化/窗口化切换（最大化按钮在标题栏关闭按钮旁）
        self.setWindowFlags(self.windowFlags()
                            | Qt.WindowType.WindowMaximizeButtonHint)
        self.resize(900, 600)
        self._direction = direction   # 脚本所选方向：含'行'→以行为单位；含'列'→以列为单位
        self._model = model           # 表格模型（可选）：提供时检查报错做数据级对齐预检
        self._blocks: list[BlockNode] = []   # 临时储存区（树根）
        self._selected_mode = 'group'  # 操作栏复制/删除的作用范围：'self'自身 | 'group'整体
        # 撤销/重做：积木树快照栈（独立于表格撤销，2026-08-22 新增）
        self._undo_stack: list = []
        self._redo_stack: list = []
        from PyQt6.QtGui import QShortcut, QKeySequence
        QShortcut(QKeySequence('Ctrl+Z'), self, activated=self._undo)
        QShortcut(QKeySequence('Ctrl+Y'), self, activated=self._redo)
        QShortcut(QKeySequence('Ctrl+Shift+Z'), self, activated=self._redo)

        # --- 布局：左侧操作栏 + 右侧积木区 ---
        outer = QHBoxLayout(self)
        # 右侧积木区（大）
        self._scene = BlockScene(self)
        self._view = QGraphicsView(self._scene)
        self._view.setRenderHint(self._view.renderHints())  # 保留默认
        self._view.setSceneRect(0, 0, 700, 500)
        outer.addWidget(self._view, 4)
        # 左侧操作栏（小，固定宽度——防止长文本 QLabel 撑宽）
        left_widget = QWidget()
        left = QVBoxLayout(left_widget)
        left.setContentsMargins(6, 6, 6, 6)
        left.addWidget(QLabel('操作栏'))
        self._left_panel = QVBoxLayout()
        left.addLayout(self._left_panel)
        left.addStretch(1)
        # 检查报错按钮（底部固定）
        self._check_btn = QPushButton('检查报错')
        self._check_btn.clicked.connect(self._on_check_errors)
        left.addWidget(self._check_btn)
        left_widget.setFixedWidth(230)
        outer.addWidget(left_widget)

        # --- 信号 ---
        self._scene.blank_clicked.connect(self._on_blank_clicked)
        self._scene.blank_right_clicked.connect(self._on_blank_right_clicked)
        self._scene.item_clicked.connect(self._on_item_clicked)
        self._scene.interface_clicked.connect(self._on_interface_clicked)
        self._scene.drop_on_interface.connect(self._on_drop_interface)
        self._scene.detach_requested.connect(self._on_detach)

    def _current_snapshot(self):
        """当前**顶层**积木树深拷贝（撤销/重做快照）。

        只取顶层（parentItem 为 None）：嵌套子积木在 _restore_blocks 时
        由 _build_child_items 递归重建，避免快照重复收录嵌套项。
        """
        import copy
        tops = [item.node for item in self._scene.items()
                if item.parentItem() is None]
        return copy.deepcopy(tops)

    def _push_snapshot(self):
        """操作前保存快照到撤销栈（位置拖动不计入，只记结构/定义变化）。"""
        self._undo_stack.append(self._current_snapshot())
        if len(self._undo_stack) > 50:
            self._undo_stack.pop(0)
        self._redo_stack.clear()

    def _undo(self):
        """Ctrl+Z：恢复上一个快照（撤销最近一次结构/定义操作）。"""
        if not self._undo_stack:
            return
        self._redo_stack.append(self._current_snapshot())
        roots = self._undo_stack.pop()
        self._restore_blocks(roots)
        self._left_panel.addWidget(QLabel('已撤销'))

    def _redo(self):
        """Ctrl+Y / Ctrl+Shift+Z：重做被撤销的操作。"""
        if not self._redo_stack:
            return
        self._undo_stack.append(self._current_snapshot())
        roots = self._redo_stack.pop()
        self._restore_blocks(roots)
        self._left_panel.addWidget(QLabel('已重做'))

    def _restore_blocks(self, roots):
        """清空场景并按快照重建全部积木（撤销/重做恢复）。

        顶层积木按快照记录的 node.x/y 定位（拖动时已同步）。
        """
        from PyQt6.QtCore import QPointF as _QPointF
        self._scene.clear_blocks()
        self._clear_left()
        for node in roots:
            item = self._scene.add_block(node,
                                         _QPointF(node.x, node.y))
            self._build_child_items(node, item)

    def _on_blank_right_clicked(self, scene_pos=None):
        """右键空白：在点击位置弹菜单「创建积木」→ 选类型直接在原地创建。

        与左键途径区分：左键走"点空白定位"流程；右键直接在点击位置创建，
        无需再左键选位置。菜单左上角对齐右键点击点。
        """
        from PyQt6.QtWidgets import QMenu
        from PyQt6.QtGui import QCursor
        menu = QMenu(self)
        # 进入右键创建模式（选类型 → 直接在右键位置创建）
        self._right_click_pos = scene_pos
        menu.addAction('创建积木').triggered.connect(
            self._enter_create_mode)
        menu.exec(QCursor.pos())

    def _right_click_create(self, node: BlockNode):
        """右键创建：选完类型直接在右键位置创建（不进入点空白流程）。"""
        self._push_snapshot()
        pos = getattr(self, '_right_click_pos', None)
        self._right_click_pos = None
        if pos is None:
            return
        self._scene.add_block(node, pos)
        self._clear_left()
        self._left_panel.addWidget(QLabel('已创建积木（右键位置）'))

    def _on_check_errors(self):
        """检查报错：弹窗列出 validate() 的错误。"""
        from PyQt6.QtWidgets import QMessageBox
        errs = self.validate()
        if not errs:
            QMessageBox.information(self, '检查报错', '没有语法错误，允许输出')
        else:
            text = '\n'.join(f'• {e}' for e in errs)
            QMessageBox.warning(self, '检查报错', f'存在以下问题：\n\n{text}')

    def _on_detach(self, item, parent_item):
        """拖出：把 item.node 从父积木解绑（按类型恢复占位接口）。

        设计记录（02-操作类型.md / 04-接口规则.md）：
        拖出值积木 → 原位置变计算元接口；拖出符号积木 → 原位置变符号接口。
        同时解除图形父子（子积木回到画布顶层），母积木收缩尺寸。
        顺序：先解数据 → 再释放图形父子（子积木坐标转场景）→ 最后重排母积木
        （此时子积木已不在母的 childItems，母按"无此子积木"收缩，无中间态）。
        """
        self._push_snapshot()
        self._detach_node(item.node)
        self._release_parent(item)
        parent_item._relayout_propagate()   # 父收缩 + 父的父逐级更新
        item.update()

    def _on_drop_interface(self, item, iface):
        """拖到接口：把积木 node 接入接口对应的树位置。

        接入后把子积木图形项设为母积木的子项（真正内嵌），
        母积木自动扩尺寸包住子积木。
        """
        self._push_snapshot()
        parent_item = iface.parentItem()
        if not isinstance(parent_item, BlockItem):
            return
        # 兜底：拖到自己接口（误判防护）→ 无操作
        if parent_item is item:
            return
        child_node = item.node
        # 设计记录（01-积木类型.md）：输出积木是终点，不能作为子积木嵌入
        if child_node.type == BlockType.OUTPUT:
            return
        parent_node = parent_item.node
        slot = iface.slot or ('children', 'append')

        # 循环嵌套检测：parent_node 若已在 child_node 子树内，嵌入后成环
        if self._would_form_cycle(parent_node, child_node):
            self._reject_cycle()
            return

        # 从旧位置移除：如果 child_node 已在某处 children 里，先解绑
        self._detach_node(child_node)
        # 从旧父积木的图形父子中解除（若有）
        self._release_parent(item)

        # 接入新位置
        if slot[0] == 'data':
            # 数元接口：填入 data.block
            if parent_node.data is None:
                from custom_calc.model import DataDef, InputKind
                parent_node.data = DataDef()
            parent_node.data.kind = InputKind.BLOCK
            parent_node.data.block = child_node
        elif slot[0] == 'children':
            idx = slot[1]
            if parent_node.type == BlockType.PAREN:
                # 括号链式：计算元接口只接值积木（计算元/括号/计数/检定），
                # 拒绝单独的符号元（符号是自动生成的）
                # 例外：缝隙嵌入（('children', ('insert', idx))）填符号位允许符号
                if child_node.type == BlockType.SYMBOL:
                    return
                # 按接口位置接入
                # - 链中空缺（非末尾的占位）→ 补在该位置
                # - 链尾占位（最后一个占位）→ 追加（自动补符号）
                is_tail = idx >= len(parent_node.children) - 1
                if idx < len(parent_node.children) \
                        and parent_node.children[idx].is_interface \
                        and not is_tail:
                    self._fill_chain_gap(parent_node, child_node, idx)
                else:
                    self._append_to_chain(parent_node, child_node)
            elif idx == 'append':
                parent_node.children.append(child_node)
            elif isinstance(idx, tuple) and idx[0] == 'insert':
                # 缝隙嵌入：插入 children 中间位置 + 自动补符号
                self._insert_into_chain(parent_node, child_node, idx[1])
            else:
                # 替换/填入指定索引（固定槽：被顶掉的旧积木数据上脱离父积木，
                # 同时解除其图形父子——否则旧积木仍挂在父下，拖动父时跟着动）
                if idx < len(parent_node.children):
                    old = parent_node.children[idx]
                    parent_node.children[idx] = child_node
                    old_item = self._find_item_for_node(old)
                    if old_item is not None:
                        self._release_parent(old_item)
                else:
                    parent_node.children.append(child_node)
        elif slot[0] == 'output':
            # 输出积木：children[0] = 计算元接口
            if parent_node.children:
                old = parent_node.children[0]
                parent_node.children[0] = child_node
                old_item = self._find_item_for_node(old)
                if old_item is not None:
                    self._release_parent(old_item)
            else:
                parent_node.children.append(child_node)

        # 界面：内嵌为母积木子项，坐标相对母（接口局部坐标）
        item.setParentItem(parent_item)
        item.setPos(iface.pos())
        parent_item._relayout_propagate()   # 母变大 + 母的父逐级更新
        item.update()

    def _append_to_chain(self, paren_node, child_node):
        """括号链尾接入值积木：保持 值↔符号↔值 交替。

        设计记录（08-UI预期结果 3·五）：右侧接口恒为计算元接口；
        接入值积木且链尾已是值 → 自动插入符号占位接口。
        """
        children = paren_node.children
        # 去掉末尾接口占位（pending_interface；未定义数元是真实成员不算）
        while children and children[-1].is_interface:
            children.pop()
        # 链尾是值 → 先补符号占位（未定义符号接口）
        if children and BlockItem._is_value_kind(children[-1]):
            children.append(BlockNode(type=BlockType.SYMBOL))
        # 接入值积木
        children.append(child_node)
        # 补链尾计算元接口占位
        children.append(BlockNode(type=BlockType.CALC,
                                  state='pending_interface'))

    def _fill_chain_gap(self, paren_node, child_node, gap_idx: int):
        """填补链中空缺接口：把 child_node 放入 gap_idx 的占位处。

        设计记录（08-UI预期结果 3·五）：拖出值积木 → 原位置留计算元接口；
        点击该接口加入新积木 → 应补在原位置（不是链尾）。
        - 占位是计算元占位（值位）→ 直接替换
        - 占位是符号占位（符号位）→ 直接替换（child 应为符号积木）
        """
        children = paren_node.children
        if gap_idx < 0 or gap_idx >= len(children):
            self._append_to_chain(paren_node, child_node)
            return
        # 替换占位
        children[gap_idx] = child_node
        # 保持链尾有计算元占位（若替换的是链尾占位，需补一个）
        if not children or not children[-1].is_interface:
            children.append(BlockNode(type=BlockType.CALC,
                                      state='pending_interface'))

    def _release_parent(self, item: BlockItem):
        """把子积木从母积木的图形父子中解除（回到画布顶层）。"""
        if item.parentItem() is not None:
            # 场景坐标保持：先把相对坐标转成场景坐标
            scene_pos = item.mapToScene(0, 0)
            item.setParentItem(None)
            item.setPos(scene_pos)

    def _insert_into_chain(self, parent_node, child_node, insert_idx: int):
        """缝隙嵌入：把 child_node 插入链式 children 的 insert_idx 位置。

        自动补符号保持"计算元↔符号"交替结构：
        - 插入"值"积木（计算元/括号/计数/检定）：若两侧需要，自动补 '+'
        - 插入符号积木：直接插入（不补）
        """
        from custom_calc.model import SymKind
        children = parent_node.children
        if insert_idx < 0:
            insert_idx = 0
        if insert_idx > len(children):
            insert_idx = len(children)

        def _is_value(n):
            return n.type in (BlockType.CALC, BlockType.PAREN,
                              BlockType.COUNT, BlockType.CHECK)

        if child_node.type == BlockType.SYMBOL:
            children.insert(insert_idx, child_node)
            return

        # 插入值积木：保证 值↔符号↔值 交替
        # 前面是值 → child 前补符号
        if insert_idx > 0 and _is_value(children[insert_idx - 1]):
            children.insert(insert_idx, self._new_plus_symbol())
            insert_idx += 1
        children.insert(insert_idx, child_node)
        # 后面是值 → child 后补符号
        if insert_idx + 1 < len(children) and _is_value(children[insert_idx + 1]):
            children.insert(insert_idx + 1, self._new_plus_symbol())

    @staticmethod
    def _new_plus_symbol() -> BlockNode:
        """创建一个 + 符号节点。"""
        from custom_calc.model import SymKind
        return BlockNode(type=BlockType.SYMBOL, sym_kind=SymKind.OP,
                         sym_value='+')

    def _detach_node(self, node):
        """从所有父积木的 children/data 中移除该节点（解绑旧归属）。

        移除后恢复占位接口（按被拖出积木类型，空接口分对应类型）：
        - 固定槽（指数/对数/三角/输出）→ 计算元占位
        - 链式（括号/计数/检定）→ 值积木被拖出 → 计算元占位；
                                    符号积木被拖出 → 符号占位
        """
        from custom_calc.model import CalcSubtype, BlockType
        for other in self._scene.items():
            n = other.node
            if n is node:
                continue
            if node in n.children:
                idx = n.children.index(node)
                n.children.remove(node)
                if self._is_fixed_slot(n, idx):
                    n.children.insert(idx, self._make_pending_calc())
                elif n.type == BlockType.PAREN:
                    # 链式：按被拖出类型恢复占位（值→计算元，符号→符号）
                    n.children.insert(idx, BlockItem._placeholder_for(node))
                    # 合并链尾重复占位（_append_to_chain 已补一个链尾占位）
                    self._collapse_chain_tail(n)
                elif n.type in (BlockType.COUNT, BlockType.CHECK):
                    # 计数/检定固定三槽（数元 符号 数元）：拖出后补回原生槽，
                    # 防止结构破坏（数元槽被拖走只剩 2 槽的异常）
                    n.children.insert(idx, self._native_slot_for(node))
            if n.data is not None and getattr(n.data, 'block', None) is node:
                n.data.block = None
                n.data.kind = None
            # 数元接口（固定槽 children[i] 的数元节点）接入的积木
            for ch in n.children:
                if ch is not None and ch.type == BlockType.CALC \
                        and ch.calc_subtype == CalcSubtype.NUM \
                        and ch.data is not None \
                        and getattr(ch.data, 'block', None) is node:
                    ch.data.block = None
                    ch.data.kind = None

    @staticmethod
    def _native_slot_for(node) -> BlockNode:
        """计数/检定被拖出槽位的原生占位：符号槽→符号占位；数元槽→数元占位。"""
        from custom_calc.model import make_calc_num
        if node.type == BlockType.SYMBOL:
            return BlockNode(type=BlockType.SYMBOL)
        return make_calc_num()

    @staticmethod
    def _is_fixed_slot(node, idx: int) -> bool:
        """该 children 索引是否为固定槽位（指数/对数/三角/输出）。"""
        from custom_calc.model import CalcSubtype, BlockType
        if node.type == BlockType.CALC:
            return node.calc_subtype in (CalcSubtype.EXP, CalcSubtype.LOG,
                                         CalcSubtype.TRIG)
        if node.type == BlockType.OUTPUT:
            return idx == 0
        return False  # 括号/计数/检定：动态链（占位恢复在 _detach_node 处理）

    @staticmethod
    def _make_pending_calc():
        """创建待定义的计算元占位节点。"""
        from custom_calc.model import BlockType
        return BlockNode(type=BlockType.CALC, state='pending_interface')

    @staticmethod
    def _collapse_chain_tail(node):
        """合并链式 children 末尾重复占位（只保留一个链尾计算元占位）。

        只合并 is_interface（pending_interface 计算元占位），
        未定义符号（sym_value=None）是待定义的符号接口，不算链尾占位。
        """
        children = node.children
        while len(children) >= 2 and children[-1].is_interface \
                and children[-2].is_interface:
            children.pop()

    # ------------------------------------------------------------------
    # 左侧栏内容（随阶段变化）
    # ------------------------------------------------------------------

    def _clear_left(self):
        """清空左侧操作栏（含子布局里的控件——复制/删除按钮在 QHBoxLayout 里）。"""
        while self._left_panel.count():
            item = self._left_panel.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                sub = item.layout()
                while sub.count():
                    sub_item = sub.takeAt(0)
                    if sub_item.widget():
                        sub_item.widget().deleteLater()

    def _on_blank_clicked(self):
        """空白点击：有待创建积木则定位创建，否则进入空选状态。"""
        pending = getattr(self, '_pending_create', None)
        if pending is not None:
            # 定位创建：把积木放到点击位置
            self._push_snapshot()
            view = self._view
            pos = view.mapToScene(view.viewport().mapFromGlobal(
                view.cursor().pos()))
            self._pending_create = None
            item = self._scene.add_block(pending, pos)
            # 若是积木接口「添加积木」流程：创建后嵌入接口
            iface = getattr(self, '_pending_slot_iface', None)
            if iface is not None:
                self._pending_slot_iface = None
                self._attach_to_slot(pending, iface, item)
            self._on_blank_clicked()  # 创建后回空选状态
            return
        self._clear_left()
        btn = QPushButton('创建积木')
        btn.clicked.connect(self._enter_create_mode)
        self._left_panel.addWidget(btn)
        # 积木配置：保存/打开（写入 脚本库/自定义运算积木配置/）
        save_cfg = QPushButton('保存当前积木配置')
        save_cfg.clicked.connect(self._save_config)
        self._left_panel.addWidget(save_cfg)
        open_cfg = QPushButton('打开积木配置')
        open_cfg.clicked.connect(self._load_config)
        self._left_panel.addWidget(open_cfg)
        # 清空积木区按钮（有积木时才显示，点击清空全部）
        if self._scene.items():
            clear_btn = QPushButton('清空积木区')
            clear_btn.clicked.connect(self._clear_all_blocks)
            self._left_panel.addWidget(clear_btn)

    def _config_folder(self) -> str:
        """积木配置文件夹：脚本库/自定义运算积木配置（自动创建）。"""
        import os
        from config.settings import AppSettings
        s = AppSettings()
        s.load()
        folder = os.path.join(s.script_folder, '自定义运算积木配置')
        os.makedirs(folder, exist_ok=True)
        return folder

    def _save_config(self):
        """保存当前积木区为积木配置文件（JSON，可自定义文件名）。"""
        import json, os
        from PyQt6.QtWidgets import QInputDialog, QMessageBox
        tops = [item.node for item in self._scene.items()
                if item.parentItem() is None]
        if not tops:
            QMessageBox.information(self, '保存积木配置', '积木区为空，无可保存')
            return
        name, ok = QInputDialog.getText(self, '保存积木配置', '输入配置文件名：')
        if not ok or not name.strip():
            return
        name = name.strip()
        if not name.lower().endswith('.json'):
            name += '.json'
        folder = self._config_folder()
        path = os.path.join(folder, name)
        if os.path.exists(path):
            ret = QMessageBox.question(
                self, '保存积木配置',
                f'文件已存在，是否覆盖？\n{name}',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if ret != QMessageBox.StandardButton.Yes:
                return
        payload = {'version': 1, 'direction': self._direction,
                   'blocks': [_node_to_dict(r) for r in tops]}
        try:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
        except OSError as e:
            QMessageBox.warning(self, '保存失败', f'无法写入：{e}')
            return
        self._left_panel.addWidget(QLabel(f'已保存积木配置：{name}'))

    def _load_config(self):
        """从积木配置文件夹挑选 JSON 文件打开（还原积木区）。"""
        import json, os
        from PyQt6.QtWidgets import QFileDialog, QMessageBox
        from PyQt6.QtCore import QPointF as _QPF
        folder = self._config_folder()
        # DontUseNativeDialog：绕开 Windows 原生文件对话框的 COM 崩溃（0x8001010e）
        path, _ = QFileDialog.getOpenFileName(
            self, '打开积木配置', folder, '积木配置 (*.json)',
            options=QFileDialog.Option.DontUseNativeDialog)
        if not path:
            return
        try:
            with open(path, encoding='utf-8') as f:
                payload = json.load(f)
            roots = [_node_from_dict(d) for d in payload.get('blocks', [])]
        except Exception as e:
            QMessageBox.warning(self, '打开失败', f'配置解析失败：{e}')
            return
        self._push_snapshot()   # 撤销：打开前状态
        self._scene.clear_blocks()
        for node in roots:
            item = self._scene.add_block(node, _QPF(node.x, node.y))
            self._build_child_items(node, item)
        self._clear_left()
        self._left_panel.addWidget(
            QLabel(f'已打开积木配置：{os.path.basename(path)}'))
        self._left_panel.addWidget(QLabel('（可继续编辑）'))

    def _clear_all_blocks(self):
        """清空积木区：移除所有积木及其接口。"""
        self._push_snapshot()
        self._scene.clear_blocks()
        self._clear_left()
        self._left_panel.addWidget(QLabel('积木区已清空'))
        btn = QPushButton('创建积木')
        btn.clicked.connect(self._enter_create_mode)
        self._left_panel.addWidget(btn)

    def _enter_create_mode(self):
        """创建流程：左侧栏显示积木类型列表。

        右键空白进入 → 选类型直接在右键位置创建（_right_click_create）；
        左键/空选按钮进入 → 选类型后点空白定位创建（_create_at_click）。
        """
        self._clear_left()
        self._left_panel.addWidget(QLabel('选择积木类型:'))
        is_right = getattr(self, '_right_click_pos', None) is not None
        for label, node in self._creation_types():
            b = QPushButton(label)
            if is_right:
                b.clicked.connect(lambda _=False, n=node:
                                  self._right_click_create(n))
            else:
                b.clicked.connect(lambda _=False, n=node:
                                  self._create_at_click(n))
            self._left_panel.addWidget(b)

    def _creation_types(self):
        """积木类型列表（6 大类）：返回 [(显示名, 节点)]。

        点击大类创建"胚积木"（未定义态），之后需再次点击选中积木，
        在左侧操作栏编辑定义成具体子类（如计算元→数元/指数/对数/三角）。
        """
        from custom_calc.model import BlockNode, make_paren, make_count, \
            make_check, make_output
        return [
            ('计算元类', BlockNode(type=BlockType.CALC)),   # 胚：待选子类
            ('符号元类', BlockNode(type=BlockType.SYMBOL)),  # 胚：待选符号
            ('括号积木', make_paren()),
            ('计数积木', make_count()),
            ('检定积木', make_check()),
            ('输出积木', make_output()),
        ]

    def _create_at_click(self, node: BlockNode):
        """进入"点空白处定位"状态：下一次点击空白处创建。"""
        self._pending_create = node
        self._clear_left()
        self._left_panel.addWidget(QLabel('请点击积木区空白处创建'))

    def _on_item_clicked(self, item, btn):
        """点击积木：左键=选中本身（数元→定义选项），右键=功能菜单/接入。"""
        self._clear_left()
        node = item.node
        if btn == 'right':
            # 处于"嵌入积木"模式（积木接口）：右键积木 → 嵌入接口 slot
            if getattr(self, '_slot_pick_mode', False):
                self._slot_pick_mode = False
                iface = getattr(self, '_pending_slot_iface', None)
                if iface is not None:
                    self._push_snapshot()   # 右键嵌入：撤销回嵌入前
                    self._attach_to_slot(node, iface, item)
                return
            # 处于"接入积木"模式：右键积木 → 接入到目标数元
            target = getattr(self, '_pick_block_target', None)
            if target is not None:
                refresh = getattr(self, '_pick_block_refresh', None)
                self._pick_block_target = None
                self._pick_block_refresh = None
                self._attach_block_to_num(target, item, refresh)
                return
            # 正常右键：弹出功能菜单
            self._show_block_menu(item)
            return
        # 左键：按积木类型显示对应操作面板
        from custom_calc.model import CalcSubtype
        if node.type == BlockType.CALC and node.calc_subtype == CalcSubtype.NUM:
            self._show_num_define_panel(node, refresh=item)
        elif node.type == BlockType.CALC:
            self._show_calc_type_panel(item)
        elif node.type == BlockType.SYMBOL:
            self._show_symbol_panel(node, refresh=item)
        elif node.type == BlockType.PAREN:
            self._left_panel.addWidget(QLabel('括号（链式构建）'))
        elif node.type == BlockType.COUNT:
            self._show_count_check_panel(item, '计数')
        elif node.type == BlockType.CHECK:
            self._show_count_check_panel(item, '检定')
        elif node.type == BlockType.OUTPUT:
            self._show_output_panel(item)
        else:
            self._left_panel.addWidget(QLabel(f'{node.type.value} 积木'))
        # 操作栏底部：复制/删除（按当前选择范围：自身/整体）
        self._append_copy_del_buttons(item)

    def _show_block_menu(self, item: BlockItem):
        """右键功能菜单：选择本身/整体、删除、清除定义、复制。

        设计记录（02-操作类型.md 18-22 行）：
        右键功能菜单 = 与左键选中后左侧栏提供的选项一致。
        复制/删除默认对**整体**操作；「选择积木本身/整体」决定操作栏
        复制/删除按钮的作用范围。
        """
        from PyQt6.QtWidgets import QMenu
        menu = QMenu(self)
        act_self = menu.addAction('选择积木本身')
        act_self.triggered.connect(
            lambda: self._select_block_mode(item, 'self'))
        act_group = menu.addAction('选择积木及子积木整体')
        act_group.triggered.connect(
            lambda: self._select_block_mode(item, 'group'))
        menu.addSeparator()
        act_del = menu.addAction('删除（整体）')
        act_del.triggered.connect(lambda: self._delete_block(item))
        act_clear = menu.addAction('清除定义')
        act_clear.triggered.connect(lambda: self._clear_block_def(item))
        act_copy = menu.addAction('复制（整体）')
        act_copy.triggered.connect(lambda: self._copy_block(item, whole=True))
        # 在右键点击位置弹出（菜单左上角对齐点击点）
        from PyQt6.QtGui import QCursor
        menu.exec(QCursor.pos())

    def _select_block_mode(self, item: BlockItem, mode: str):
        """选择积木（自身/整体）并刷新操作栏（含按范围的复制/删除按钮）。"""
        self._selected_mode = mode
        self._on_item_clicked(item, 'left')

    def _append_copy_del_buttons(self, item: BlockItem):
        """操作栏底部：复制/删除按钮，作用范围 = 当前选择模式（自身/整体）。"""
        mode = getattr(self, '_selected_mode', 'group')
        label = '整体' if mode == 'group' else '自身'
        self._left_panel.addWidget(QLabel(f'操作范围：{label}'))
        h = QHBoxLayout()
        copy_b = QPushButton(f'复制{label}')
        copy_b.clicked.connect(lambda: self._copy_block(item, whole=(mode == 'group')))
        del_b = QPushButton(f'删除{label}')
        if mode == 'group':
            del_b.clicked.connect(lambda: self._delete_block(item))
        else:
            del_b.clicked.connect(lambda: self._delete_self(item))
        h.addWidget(copy_b)
        h.addWidget(del_b)
        self._left_panel.addLayout(h)

    def _delete_self(self, item: BlockItem):
        """删除积木自身：只删本体，子积木释放为自由积木（不跟随删除）。"""
        self._push_snapshot()
        parent = item.parentItem()
        # 子积木先释放到画布顶层（保留）
        for c in list(item.childItems()):
            if isinstance(c, BlockItem):
                scene_pos = c.mapToScene(0, 0)
                c.setParentItem(None)
                c.setPos(scene_pos)
        self._detach_node(item.node)
        if item.parentItem() is not None:
            self._release_parent(item)
        if isinstance(parent, BlockItem):
            parent._relayout_propagate()
        self._scene.remove_block(item)
        self._clear_left()

    def _select_block_group(self, item: BlockItem):
        """选择积木及子积木整体：标记整体选中状态，左侧提示。"""
        self._group_selected = item
        self._clear_left()
        self._left_panel.addWidget(QLabel('已选中整体积木'))
        self._left_panel.addWidget(QLabel('（可拖拽移动/删除）'))

    def _delete_block(self, item: BlockItem):
        """删除积木（整体）：从父解绑 + **递归移除所有子积木**。

        先记录父积木（释放图形父子后 parentItem 会变 None）。
        """
        self._push_snapshot()
        parent = item.parentItem()
        # 先数据解绑（若在父积木里）
        self._detach_node(item.node)
        # 解除图形父子（若有）
        if item.parentItem() is not None:
            self._release_parent(item)
        # 从父积木 relayout（若父是积木，重排同级 + 恢复空缺接口）
        if isinstance(parent, BlockItem):
            parent._relayout_propagate()
        # 递归收集所有子积木（含嵌套），一并移除（整体删除）
        def _collect(it, acc):
            for c in list(it.childItems()):
                if isinstance(c, BlockItem):
                    acc.append(c)
                    _collect(c, acc)
        all_items = [item]
        _collect(item, all_items)
        for it in all_items:
            self._scene.remove_block(it)
        self._clear_left()

    def _clear_block_def(self, item: BlockItem):
        """清除定义：按类型重置回未定义态。

        设计记录（01-积木类型.md）：清除定义回到未定义态——
        计算元回到"待选择子类"胚（calc_subtype=None，显示"计算元?"），
        符号清空、三角清函数名、输出清位置。
        """
        self._push_snapshot()
        node = item.node
        from custom_calc.model import CalcSubtype, DataDef
        if node.type == BlockType.CALC:
            # 计算元清除定义 → 回到"待选择子类"胚态（calc_subtype=None）
            node.calc_subtype = None
            node.children = []
            node.data = None
            node.trig_func = None
        elif node.type == BlockType.SYMBOL:
            node.sym_value = None
            node.sym_kind = None
        elif node.type == BlockType.OUTPUT:
            node.output_target = None
            node.output_index = None
        item.update()
        item._relayout_propagate()   # 尺寸可能变化，父链更新
        self._clear_left()
        self._left_panel.addWidget(QLabel('已清除定义'))
        self._on_item_clicked(item, 'left')   # 取消选中：回到该积木的操作面板（即点即生效）

    def _copy_block(self, item: BlockItem, whole: bool = True):
        """复制积木（默认整体）。

        whole=True（整体）：深拷贝完整树，并**递归创建嵌套子积木的图形项**
        ——修复"复制嵌套积木只剩接口/加号跑左边缘"的问题。
        whole=False（自身）：只复制积木本体（清除嵌套接入的积木，
        保留定义类属性：数元行/列/常数定义、符号、三角函数、输出位置）。
        """
        self._push_snapshot()
        node = item.node
        if whole:
            clone = node.clone(deep=True)
        else:
            clone = self._clone_self_only(node)
        pos = item.scenePos() + QPointF(30, 30)
        new_item = self._scene.add_block(clone, pos)
        if whole:
            self._build_child_items(clone, new_item)
        self._clear_left()
        self._left_panel.addWidget(QLabel('已复制积木（自由摆放）'))

    def _build_child_items(self, node, parent_item: BlockItem):
        """递归为 node 的嵌套成员创建图形项并嵌入父（复制整体时用）。

        覆盖三种接入位置：
        - children 中真实成员（计算元/括号/计数/检定等）
        - 数元节点 data.block（数元自身接入）
        - children[i].data.block（数元接口接入）
        """
        scene = self._scene
        members = []
        for child in list(node.children):
            if child is None or child.is_interface:
                continue
            if child.type == BlockType.SYMBOL and child.sym_value is None:
                continue   # 符号占位（接口）
            # 接口槽原生数元（EXP/LOG/TRIG/COUNT/CHECKK 的 children 里的 calc num）
            # 不是独立积木：它们由 num 接口显示，数据经 data.block 内嵌，
            # 不应有可拖动的 BlockItem（否则画面多出"外层框"，拖动会破坏结构）。
            # 括号（PAREN）链中的数元是用户构建的真实成员，仍需创建。
            if node.type != BlockType.PAREN \
                    and child.type == BlockType.CALC \
                    and child.calc_subtype == CalcSubtype.NUM:
                continue   # 接口槽原生数元：跳过（由接口/内嵌积木表示）
            members.append(child)
        for child in members:
            child_item = scene.add_block(child)
            child_item.setParentItem(parent_item)
            child_item.setPos(0, 0)
            self._build_child_items(child, child_item)
        # 数元节点 data.block（数元自身接入）
        if node.data is not None and getattr(node.data, 'block', None) is not None:
            b = node.data.block
            if not b.is_interface:
                bi = scene.add_block(b)
                bi.setParentItem(parent_item)
                bi.setPos(0, 0)
                self._build_child_items(b, bi)
        # children[i] 数元接口接入的积木
        for ch in list(node.children):
            if ch is not None and ch.type == BlockType.CALC \
                    and ch.calc_subtype == CalcSubtype.NUM \
                    and ch.data is not None \
                    and getattr(ch.data, 'block', None) is not None \
                    and not ch.data.block.is_interface:
                b = ch.data.block
                bi = scene.add_block(b)
                bi.setParentItem(parent_item)
                bi.setPos(0, 0)
                self._build_child_items(b, bi)
        parent_item._relayout_propagate()

    @staticmethod
    def _clone_self_only(node):
        """仅复制积木本体：清除嵌套接入的积木，保留定义类属性。

        - 括号 → 空括号（1 个链尾占位）
        - 计算元 → 保留子类与定义；数元/固定槽的接入积木（data.block）清空
        - 计数/检定 → 保留结构（数元+符号+数元）与已定义符号/数元定义，
          清空接入的积木
        - 输出 → 保留输出位置，清空接口（1 个占位）
        """
        from custom_calc.model import DataDef, make_paren
        clone = node.clone(deep=True)

        def _clear_block_ref(d):
            if d is not None and getattr(d, 'block', None) is not None:
                d.block = None
                if d.kind == InputKind.BLOCK:
                    d.kind = None
                    d.index = None
                    d.value = None

        if clone.type == BlockType.PAREN:
            clone.children = [BlockNode(type=BlockType.CALC,
                                        state='pending_interface')]
        elif clone.type == BlockType.CALC:
            st = clone.calc_subtype
            if st == CalcSubtype.NUM:
                _clear_block_ref(clone.data)
            elif st in (CalcSubtype.EXP, CalcSubtype.LOG, CalcSubtype.TRIG):
                for ch in clone.children:
                    if ch is not None and ch.type == BlockType.CALC \
                            and ch.calc_subtype == CalcSubtype.NUM \
                            and ch.data is not None:
                        _clear_block_ref(ch.data)
        elif clone.type in (BlockType.COUNT, BlockType.CHECK):
            for ch in clone.children:
                if ch is not None and ch.type == BlockType.CALC \
                        and ch.calc_subtype == CalcSubtype.NUM \
                        and ch.data is not None:
                    _clear_block_ref(ch.data)
        elif clone.type == BlockType.OUTPUT:
            clone.children = [BlockNode(type=BlockType.CALC,
                                        state='pending_interface')]
        clone.state = 'normal'
        return clone

    def _on_interface_clicked(self, iface: InterfaceItem):
        """点击接口：
        - 数元接口（kind='num'）→ 操作栏数元定义（4 种方式）
        - 符号接口（kind='sym'）→ 操作栏符号表（点击即输入）
        - 积木接口（kind='slot'）→ 操作栏「添加积木」「嵌入积木」
        """
        self._clear_left()
        if iface.kind == 'num':
            node = iface.node_ref
            if node is None:
                self._left_panel.addWidget(QLabel('数元接口（待定义）'))
                return
            self._left_panel.addWidget(QLabel('定义数元:'))
            self._show_num_define_panel(node, refresh=iface)
        elif iface.kind == 'sym':
            node = iface.node_ref
            if node is None:
                self._left_panel.addWidget(QLabel('符号接口（待定义）'))
                return
            self._show_symbol_panel(node, refresh=iface)
        else:
            self._show_slot_panel(iface)

    def _show_slot_panel(self, iface: InterfaceItem):
        """积木接口：操作栏显示「添加积木」「嵌入积木」。"""
        self._left_panel.addWidget(QLabel('积木接口:'))
        add_b = QPushButton('添加积木')
        add_b.clicked.connect(lambda: self._slot_add_block(iface))
        self._left_panel.addWidget(add_b)
        embed_b = QPushButton('嵌入积木')
        embed_b.clicked.connect(lambda: self._slot_embed_block(iface))
        self._left_panel.addWidget(embed_b)

    def _slot_add_block(self, iface: InterfaceItem):
        """积木接口「添加积木」：显示类型列表，选择后直接嵌入接口。

        不进入"点空白处定位"流程（与普通创建区分），
        设计记录（02-操作类型.md）：接口点击后操作栏提供选项。
        """
        self._slot_add_iface = iface
        self._clear_left()
        self._left_panel.addWidget(QLabel('选择要嵌入的积木类型:'))
        for label, node in self._creation_types():
            b = QPushButton(label)
            b.clicked.connect(lambda _=False, n=node:
                              self._create_and_embed(n))
            self._left_panel.addWidget(b)

    def _create_and_embed(self, node: BlockNode):
        """创建积木并直接嵌入当前积木接口（无定位步骤）。"""
        self._push_snapshot()
        iface = getattr(self, '_slot_add_iface', None)
        self._slot_add_iface = None
        if iface is None:
            return
        item = self._scene.add_block(node)
        self._attach_to_slot(node, iface, item)
        self._clear_left()
        self._left_panel.addWidget(QLabel('已嵌入积木，可继续编辑'))

    def _slot_embed_block(self, iface: InterfaceItem):
        """积木接口「嵌入积木」：提示右键积木区中的积木以嵌入。"""
        self._pending_slot_iface = iface
        self._left_panel.addWidget(QLabel('请右键积木区中的积木以嵌入'))
        self._slot_pick_mode = True

    def _show_count_check_panel(self, item: BlockItem, name: str):
        """计数/检定积木：显示结构说明。

        10 计划 v2：范围输入改在**数元定义面板**（_show_num_define_panel）
        提供「范围-以行为单位/以列为单位」特化，不在此处加模式按钮。
        """
        self._clear_left()   # 防止刷新时面板叠加
        self._left_panel.addWidget(QLabel(f'{name}积木（等式/不等式）'))
        self._left_panel.addWidget(QLabel('结构：计算元 逻辑符号 计算元'))
        hint = QLabel('（左侧数元可定义「范围」输入：逐行/列计数 → 对齐一维表）')
        hint.setWordWrap(True)
        self._left_panel.addWidget(hint)

    # ------------------------------------------------------------------
    # 符号元定义面板
    # ------------------------------------------------------------------

    def _show_symbol_panel(self, node, refresh=None):
        """符号积木/符号接口：左侧列可选符号（运算+逻辑），点击即输入。

        node: 符号节点（BlockNode）
        refresh: 刷新对象（BlockItem 或 InterfaceItem），可为 None
        """
        from custom_calc.model import SymKind
        cur = node.sym_value or '?'
        self._left_panel.addWidget(QLabel(f'当前符号：{cur}'))
        self._left_panel.addWidget(QLabel('运算符号:'))
        for op in ('+', '-', '×', '÷', '%'):
            b = QPushButton(op)
            b.clicked.connect(lambda _=False, o=op: self._set_symbol(node, o, refresh))
            self._left_panel.addWidget(b)
        self._left_panel.addWidget(QLabel('逻辑符号:'))
        for op in ('=', '>', '<', '>=', '<=', '≠', '≡'):
            b = QPushButton(op)
            b.clicked.connect(lambda _=False, o=op: self._set_symbol(node, o, refresh))
            self._left_panel.addWidget(b)
        clear_b = QPushButton('清除定义')
        clear_b.clicked.connect(lambda: self._set_symbol(node, None, refresh))
        self._left_panel.addWidget(clear_b)

    def _set_symbol(self, node, value, refresh=None):
        """设置符号积木/符号接口的值（None=清除定义）。

        即点即生效：选完符号后取消选中（回空选），接口/积木显示新符号。
        """
        self._push_snapshot()
        from custom_calc.model import SymKind
        node.sym_value = value
        if value is not None:
            # 自动分类：运算符号 / 逻辑符号
            node.sym_kind = SymKind.OP if value in ('+', '-', '×', '÷', '%') \
                else SymKind.LOGIC
        else:
            node.sym_kind = None
        self._refresh_interface(refresh)
        # 取消选中：回到空选状态（符号已即点即生效显示）
        self._clear_left()
        self._left_panel.addWidget(QLabel('符号已设置，可继续编辑'))

    # ------------------------------------------------------------------
    # 数元接口定义面板
    # ------------------------------------------------------------------

    def _show_calc_type_panel(self, item: BlockItem):
        """计算元：显示当前类型 + 类型切换按钮（待选择/数元/指数/对数/三角）。

        三角类型额外显示函数名选择（点击即选，像符号表）：
        设计记录（01-积木类型.md 30-33 行）：点击函数名按钮 → 左侧列函数名表。
        """
        from custom_calc.model import CalcSubtype
        node = item.node
        st = node.calc_subtype
        if st is None:
            self._left_panel.addWidget(QLabel('计算元：待选择类型'))
        else:
            name = {CalcSubtype.EXP: '指数', CalcSubtype.LOG: '对数',
                    CalcSubtype.TRIG: '三角函数',
                    CalcSubtype.NUM: '数元'}.get(st, str(st))
            self._left_panel.addWidget(QLabel(f'计算元：{name}'))
            if st == CalcSubtype.TRIG:
                # 三角：函数名选择（当前函数名 + 列表）
                from custom_calc.model import TRIG_FUNCS
                cur = node.trig_func or 'sin'
                self._left_panel.addWidget(QLabel(f'当前函数：{cur}'))
                self._left_panel.addWidget(QLabel('选择函数:'))
                for fn in TRIG_FUNCS:
                    b = QPushButton(fn)
                    b.clicked.connect(
                        lambda _=False, f=fn: self._set_trig_func(item, f))
                    self._left_panel.addWidget(b)
                clear_b = QPushButton('清除函数')
                clear_b.clicked.connect(
                    lambda: self._set_trig_func(item, None))
                self._left_panel.addWidget(clear_b)
        self._left_panel.addWidget(QLabel('切换类型:'))
        for label, subtype in [
            ('数元', CalcSubtype.NUM),
            ('指数', CalcSubtype.EXP),
            ('对数', CalcSubtype.LOG),
            ('三角函数', CalcSubtype.TRIG),
        ]:
            b = QPushButton(label)
            b.clicked.connect(
                lambda _=False, s=subtype: self._set_calc_type(item, s))
            self._left_panel.addWidget(b)

    def _set_trig_func(self, item: BlockItem, func):
        """设置三角函数名（None=清除定义，未定义态）。"""
        self._push_snapshot()
        node = item.node
        node.trig_func = func
        item.update()
        item._relayout_propagate()
        self._on_item_clicked(item, 'left')  # 刷新左侧面板

    def _set_calc_type(self, item: BlockItem, subtype):
        """切换计算元类型：重建 children 结构。"""
        self._push_snapshot()
        from custom_calc.model import CalcSubtype, DataDef, InputKind
        node = item.node
        if node.calc_subtype == subtype:
            return  # 已是该类型
        node.calc_subtype = subtype
        # 重建结构
        if subtype == CalcSubtype.NUM:
            node.children = []
            if node.data is None:
                node.data = DataDef()
        elif subtype == CalcSubtype.EXP:
            node.children = [self._new_num_interface(), self._new_num_interface()]
            node.data = None
        elif subtype == CalcSubtype.LOG:
            node.children = [self._new_num_interface(), self._new_num_interface()]
            node.data = None
        elif subtype == CalcSubtype.TRIG:
            node.children = [self._new_num_interface()]
            node.trig_func = 'sin'  # 默认 sin（设计文档 01：默认 sin）
            node.data = None
        item._relayout_propagate()   # 重建接口 + 尺寸变化 + 父链逐级更新
        self._on_item_clicked(item, 'left')  # 刷新左侧面板

    @staticmethod
    def _new_num_interface():
        """创建一个数元接口（未定义）。"""
        from custom_calc.model import BlockType, CalcSubtype, DataDef
        node = BlockNode(type=BlockType.CALC)
        node.calc_subtype = CalcSubtype.NUM
        node.data = DataDef()
        return node

    def _show_output_panel(self, item: BlockItem):
        """输出积木：选择输出位置。

        设计记录（03-界面布局.md 46-52 行）：
        - 仅提供前面所选方向：选行单位 → 只提供输出到行；选列单位 → 只提供输出到列
        - 剪贴板始终提供（输出形态随方向）
        - 显示当前已选位置（切走再回来仍在）
        """
        from PyQt6.QtWidgets import QInputDialog
        from custom_calc.model import OutputTarget
        node = item.node
        self._clear_left()   # 防止刷新时按钮叠加
        cur = self._output_label(node)
        self._left_panel.addWidget(QLabel(f'当前输出位置：{cur}'))
        self._left_panel.addWidget(QLabel('输出位置:'))
        # 剪贴板 + 输出到行/输出到列（10 计划：两个按钮都显示，不按脚本方向过滤）
        options = [('剪贴板', OutputTarget.CLIPBOARD),
                   ('输出到行', OutputTarget.ROW),
                   ('输出到列', OutputTarget.COL)]
        for label, tgt in options:
            b = QPushButton(label)
            b.clicked.connect(lambda _=False, t=tgt: self._set_output(item, t))
            self._left_panel.addWidget(b)
        # 清除定义
        clear_b = QPushButton('清除输出位置')
        clear_b.clicked.connect(lambda: self._clear_output(item))
        self._left_panel.addWidget(clear_b)

    @staticmethod
    def _output_label(node) -> str:
        """输出积木当前位置显示文字（未选 → '输出?'）。"""
        from custom_calc.model import OutputTarget
        from models.spreadsheet_model import SpreadsheetModel
        t = node.output_target
        if t is None:
            return '输出?'
        if t == OutputTarget.CLIPBOARD:
            return '剪贴板'
        if t == OutputTarget.COL:
            return f'列{SpreadsheetModel.col_letter(node.output_index)}' \
                if node.output_index is not None else '列?'
        if t == OutputTarget.ROW:
            return f'行{node.output_index + 1}' \
                if node.output_index is not None else '行?'
        return '?'

    def _clear_output(self, item: BlockItem):
        """清除输出位置定义。"""
        self._push_snapshot()
        node = item.node
        node.output_target = None
        node.output_index = None
        item.update()
        self._show_output_panel(item)  # 刷新面板显示

    def _set_output(self, item: BlockItem, target):
        from PyQt6.QtWidgets import QInputDialog
        from custom_calc.model import OutputTarget
        self._push_snapshot()
        node = item.node
        if target == OutputTarget.CLIPBOARD:
            node.output_target = target
            node.output_index = None
        else:
            hint = '输入列B' if target == OutputTarget.COL else '输入行1'
            text, ok = QInputDialog.getText(self, '输出位置', f'{hint}：')
            if not ok or not text.strip():
                return
            text = text.strip().upper()
            if target == OutputTarget.COL and text.startswith('列') and len(text) > 1:
                node.output_target = target
                node.output_index = self._parse_col_letter(text[1:])
            elif target == OutputTarget.ROW and text.startswith('行') and text[1:].isdigit():
                node.output_target = target
                node.output_index = int(text[1:]) - 1
            else:
                from PyQt6.QtWidgets import QMessageBox
                QMessageBox.warning(self, '无效', f'请输入 {hint} 格式')
                return
        item.update()
        self._show_output_panel(item)  # 刷新面板显示当前值

    def _num_parent_type(self, refresh):
        """数元所属积木的类型（用于判断是否计数积木）。

        - refresh 是 InterfaceItem（数元接口）→ 接口的父积木
        - refresh 是 BlockItem（数元积木自身）→ 被嵌入时的父积木（独立时为 None）
        """
        p = refresh.parentItem() if refresh is not None else None
        while p is not None and not isinstance(p, BlockItem):
            p = p.parentItem()
        return p.node.type if isinstance(p, BlockItem) else None

    def _show_num_define_panel(self, node, refresh=None):
        """数元接口定义：4 种方式 + 清除定义。

        node: 被定义的数元节点（BlockNode）
        refresh: 定义后需要重绘的对象（BlockItem 或 InterfaceItem），可为 None
        输入行/列按钮文字跟随脚本所选方向：
        - 以列为单位 → 「输入列」（只接受 列A 格式）
        - 以行为单位 → 「输入行」（只接受 行1 格式）

        「整个表格」仅**计数积木**的数元接口显示（09 计划步骤 5：
        全表输入是计数积木专用，检定/普通运算不接受全表）。

        清除定义按钮仅数元积木自身（refresh 是 BlockItem）显示；
        数元接口（refresh 是 InterfaceItem，如指数/检定等固定槽的原生子级数元）
        不显示清除定义（原生子数元通过接入积木/定义数据操作即可）。
        """
        from PyQt6.QtWidgets import QLineEdit, QInputDialog
        self._clear_left()   # 统一清空（被二级页面"返回"调用时也防叠加）
        rowcol_label = '输入行' if '行' in self._direction else '输入列'
        self._left_panel.addWidget(QLabel('定义数元:'))
        actions = [
            (rowcol_label, 'rowcol'),
            ('手动常数', 'const'),
            ('从剪贴板输入', 'clipboard'),
        ]
        # 范围输入特化（10 计划 v2）：跟随脚本方向——行→范围-以行为单位
        range_label = '范围-以行为单位' if '行' in self._direction \
            else '范围-以列为单位'
        actions.append((range_label, 'range'))
        if self._num_parent_type(refresh) == BlockType.COUNT:
            actions.append(('整个表格', 'whole_table'))
        actions.append(('接入积木', 'block'))
        if not isinstance(refresh, InterfaceItem):
            actions.append(('清除定义', 'clear'))
        for label, action in actions:
            b = QPushButton(label)
            b.clicked.connect(lambda _=False, a=action:
                              self._num_define(node, a, refresh))
            self._left_panel.addWidget(b)

    def _num_define(self, node, action: str, refresh=None):
        """处理数元定义动作。"""
        self._push_snapshot()
        from PyQt6.QtWidgets import QInputDialog
        from custom_calc.model import DataDef, InputKind
        from models.spreadsheet_model import SpreadsheetModel
        if node.data is None:
            node.data = DataDef()
        if action == 'clear':
            # 清除定义：回计算元胚态 + 取消选中（与右键清除一致）
            item = refresh if isinstance(refresh, BlockItem) else None
            if item is not None:
                self._clear_block_def(item)
            else:
                node.data = DataDef()  # 接口清除（refresh 是 InterfaceItem）
                self._refresh_interface(refresh)
            return
        if action == 'rowcol':
            # 方向一致性：以行为单位只接受 行N；以列为单位只接受 列A
            if '行' in self._direction:
                hint, kind = '行1', InputKind.ROW
            else:
                hint, kind = '列A', InputKind.COL
            text, ok = QInputDialog.getText(
                self, '定义数元', f'输入 {hint}（当前以{"行" if kind == InputKind.ROW else "列"}为单位）：')
            if not ok or not text.strip():
                return
            text = text.strip().upper()
            if kind == InputKind.ROW:
                if not (text.startswith('行') and text[1:].isdigit()):
                    from PyQt6.QtWidgets import QMessageBox
                    QMessageBox.warning(self, '无效',
                                        f'当前以行为单位，请输入 {hint} 格式（如 行1）')
                    return
                node.data = DataDef(kind=InputKind.ROW,
                                    index=int(text[1:]) - 1)
            else:
                if not (text.startswith('列') and len(text) > 1
                        and text[1:].isalpha()):
                    from PyQt6.QtWidgets import QMessageBox
                    QMessageBox.warning(self, '无效',
                                        f'当前以列为单位，请输入 {hint} 格式（如 列A）')
                    return
                node.data = DataDef(kind=InputKind.COL,
                                    index=self._parse_col_letter(text[1:]))
        elif action == 'const':
            text, ok = QInputDialog.getText(self, '定义数元', '输入常数：')
            if not ok:
                return
            try:
                val = float(text)
            except ValueError:
                from PyQt6.QtWidgets import QMessageBox
                QMessageBox.warning(self, '无效', '常数无效')
                return
            node.data = DataDef(kind=InputKind.CONST, value=val)
        elif action == 'clipboard':
            from PyQt6.QtWidgets import QApplication
            cb = QApplication.clipboard().text()
            if not cb:
                from PyQt6.QtWidgets import QMessageBox
                QMessageBox.warning(self, '无效', '剪贴板为空')
                return
            # 方向一致性：剪贴板形态需与所选方向对应
            # 对行处理 → Tab 横排（每列一个值）；对列处理 → 换行竖排（每行一个值）
            norm = cb.replace('\r\n', '\n').replace('\r', '\n')
            if '行' in self._direction:
                if '\n' in norm and '\t' not in norm:
                    from PyQt6.QtWidgets import QMessageBox
                    QMessageBox.warning(
                        self, '方向不符',
                        '当前以行为单位，剪贴板应为 Tab 横排（每列一个值）\n'
                        '当前剪贴板是换行竖排，请复制横排数据')
                    return
            else:
                if '\t' in norm and '\n' not in norm:
                    from PyQt6.QtWidgets import QMessageBox
                    QMessageBox.warning(
                        self, '方向不符',
                        '当前以列为单位，剪贴板应为换行竖排（每行一个值）\n'
                        '当前剪贴板是 Tab 横排，请复制竖排数据')
                    return
            node.data = DataDef(kind=InputKind.CLIPBOARD)
        elif action == 'whole_table':
            # 整个表格（仅计数积木接口提供此按钮，09 计划步骤 5）
            node.data = DataDef(kind=InputKind.WHOLE_TABLE)
        elif action == 'range':
            # 范围输入（10 计划 v2）：进入二级页面设起始/结尾
            self._show_range_panel(node, refresh)
            return
        elif action == 'block':
            # 接入积木：记录接口（若 refresh 是接口）或数元节点
            self._pick_block_target = node
            self._pick_block_refresh = refresh
            self._left_panel.addWidget(QLabel('请右键积木区中的积木以接入'))
        self._refresh_interface(refresh)

    # ------------------------------------------------------------------
    # 范围输入（10 计划 v2）：数元定义面板的二级页面
    # ------------------------------------------------------------------

    def _show_range_panel(self, node, refresh=None):
        """范围输入二级页面：起始/结尾按钮（分行）+ 确定/清除/返回。"""
        from custom_calc.model import InputKind, DataDef
        self._clear_left()   # 防止重复点击叠加
        if node.data is None:
            node.data = DataDef()
        axis = '行' if '行' in self._direction else '列'
        d = node.data
        if d.kind == InputKind.RANGE:
            cur = (f'范围-以{axis}为单位：'
                   f'起始{self._range_label(d.range_start, axis)} '
                   f'结尾{self._range_label(d.range_end, axis)}')
        else:
            cur = '范围未设置'
        self._left_panel.addWidget(QLabel(f'当前：{cur}'))
        self._left_panel.addWidget(
            QLabel(f'范围-以{axis}为单位（起始 ≤ 结尾，可相等=单{axis}）'))
        # 起始/结尾分两行（避免操作栏变宽）
        start_b = QPushButton(
            f'起始{axis}: {self._range_label(d.range_start, axis)}')
        start_b.clicked.connect(
            lambda: self._set_range_endpoint(node, 'start', refresh))
        self._left_panel.addWidget(start_b)
        end_b = QPushButton(
            f'结尾{axis}: {self._range_label(d.range_end, axis)}')
        end_b.clicked.connect(
            lambda: self._set_range_endpoint(node, 'end', refresh))
        self._left_panel.addWidget(end_b)
        ok_b = QPushButton('确定范围')
        ok_b.clicked.connect(lambda: self._confirm_range(node, refresh))
        self._left_panel.addWidget(ok_b)
        clear_b = QPushButton('清除范围')
        clear_b.clicked.connect(lambda: self._clear_range(node, refresh))
        self._left_panel.addWidget(clear_b)
        back_b = QPushButton('返回数元定义')
        back_b.clicked.connect(
            lambda: self._show_num_define_panel(node, refresh))
        self._left_panel.addWidget(back_b)

    @staticmethod
    def _range_label(idx, axis: str) -> str:
        """范围端点显示文字（未设 → '未设'；列显示字母 列B）。"""
        if idx is None:
            return '未设'
        if axis == '列':
            from models.spreadsheet_model import SpreadsheetModel
            return f'列{SpreadsheetModel.col_letter(idx)}'
        return f'行{idx + 1}'

    def _set_range_endpoint(self, node, which: str, refresh=None):
        """输入起始/结尾行/列（QInputDialog，格式 行N / 列X）。"""
        from PyQt6.QtWidgets import QInputDialog, QMessageBox
        from custom_calc.model import DataDef
        if node.data is None:
            node.data = DataDef()
        axis = '行' if '行' in self._direction else '列'
        hint = '行1' if axis == '行' else '列A'
        text, ok = QInputDialog.getText(self, '范围设置',
                                        f'输入{axis}号（如 {hint}）：')
        if not ok or not text.strip():
            return
        text = text.strip().upper()
        if axis == '行':
            if not (text.startswith('行') and text[1:].isdigit()):
                QMessageBox.warning(self, '无效', f'请输入 {hint} 格式（如 行1）')
                return
            idx = int(text[1:]) - 1
        else:
            if not (text.startswith('列') and len(text) > 1
                    and text[1:].isalpha()):
                QMessageBox.warning(self, '无效', f'请输入 {hint} 格式（如 列A）')
                return
            idx = self._parse_col_letter(text[1:])
        d = node.data
        d.range_axis = 'row' if axis == '行' else 'col'
        if which == 'start':
            d.range_start = idx
        else:
            d.range_end = idx
        self._push_snapshot()
        self._refresh_interface(refresh)
        self._show_range_panel(node, refresh)

    def _confirm_range(self, node, refresh=None):
        """确定范围：校验完整 + 顺序，设置 kind=RANGE。"""
        from PyQt6.QtWidgets import QMessageBox
        from custom_calc.model import InputKind
        d = node.data
        if d.range_start is None or d.range_end is None:
            QMessageBox.warning(self, '无效', '请先输入起始和结尾')
            return
        if d.range_start > d.range_end:
            QMessageBox.warning(self, '无效', '范围顺序错误：起始应 ≤ 结尾')
            return
        d.kind = InputKind.RANGE
        self._push_snapshot()
        self._refresh_interface(refresh)
        self._show_num_define_panel(node, refresh)

    def _clear_range(self, node, refresh=None):
        """清除范围（回未定义）。"""
        from custom_calc.model import DataDef
        d = node.data
        if d is not None:
            d.kind = None
            d.range_axis = None
            d.range_start = None
            d.range_end = None
        self._push_snapshot()
        self._refresh_interface(refresh)
        self._show_num_define_panel(node, refresh)

    @staticmethod
    def _refresh_interface(refresh):
        """刷新接口/积木显示（数元定义后重绘）。"""
        if refresh is not None:
            refresh.update()

    @staticmethod
    def _parse_col_letter(letter: str) -> int:
        """列字母 → 索引（A=0, B=1, ..., AA=26）。"""
        idx = 0
        for ch in letter:
            idx = idx * 26 + (ord(ch) - ord('A') + 1)
        return idx - 1

    def _would_form_cycle(self, host_node, guest_node) -> bool:
        """判断把 guest_node 嵌入 host_node（数元/槽）是否会形成循环嵌套。

        若 host_node 已位于 guest_node 的子树（data.block + children 递归）
        中，嵌入后 guest → ... → host → guest 成环。
        环会导致：序列化无限递归、Qt 图形父子环（setParentItem 卡死）。
        """
        stack = [guest_node]
        seen = set()
        while stack:
            cur = stack.pop()
            if cur is host_node:
                return True
            if id(cur) in seen:
                continue
            seen.add(id(cur))
            if cur.data is not None \
                    and getattr(cur.data, 'block', None) is not None:
                stack.append(cur.data.block)
            stack.extend(cur.children)
        return False

    @staticmethod
    def _reject_cycle():
        """循环嵌套被拒绝时的用户提示（不打断流程）。"""
        from PyQt6.QtWidgets import QMessageBox
        QMessageBox.warning(
            None, '无法嵌入',
            '该积木已包含目标位置（循环嵌套），已取消本次嵌入。')

    def _attach_block_to_num(self, num_node, block_item: BlockItem, refresh=None):
        """把 block_item.node 接入 num_node（数元节点）的 data.block。

        接入的积木从旧归属解绑（如果有），并移入数元 data.block，
        同时内嵌为母积木子项（母自动扩尺寸）。
        """
        self._push_snapshot()
        from custom_calc.model import DataDef, InputKind
        block_node = block_item.node
        if block_node is num_node:
            return  # 不能接入自身，静默忽略
        # 数元 data 槽只接受"值"积木（计算元/括号/计数/检定），拒绝符号元
        if block_node.type == BlockType.SYMBOL:
            return
        # 循环嵌套检测：num_node 若已在 block_node 子树内，嵌入后成环
        # （会导致数据环 + Qt 图形父子环，曾造成 python 无响应卡死）
        if self._would_form_cycle(num_node, block_node):
            self._reject_cycle()
            return
        # 解绑旧归属（包括旧的 data.block 积木）
        self._detach_node(block_node)
        if num_node.data is not None and getattr(num_node.data, 'block', None) is not None:
            old = num_node.data.block
            num_node.data.block = None
            num_node.data.kind = None
            old_item = self._find_item_for_node(old)
            if old_item is not None:
                self._release_parent(old_item)
        self._release_parent(block_item)
        # 接入数元 data.block
        if num_node.data is None:
            num_node.data = DataDef()
        num_node.data.kind = InputKind.BLOCK
        num_node.data.block = block_node
        # 界面：若 refresh 是接口（数元接口点击进入接入），
        # 保留数元节点，隐藏接口、积木内嵌到接口的母积木
        if isinstance(refresh, InterfaceItem):
            parent_item = refresh.parentItem()
            if isinstance(parent_item, BlockItem):
                block_item.setParentItem(parent_item)
                block_item.setPos(refresh.pos())
                parent_item._relayout_propagate()   # 接口隐藏 + 归位 + 父链更新
            block_item.update()
            self._refresh_interface(refresh)
            return
        # 否则（数元积木自身）：内嵌为母积木子项
        num_item = self._find_item_for_node(num_node)
        if num_item is not None:
            block_item.setParentItem(num_item)
            num_item._relayout_propagate()   # 数元变大 + 父链逐级更新
        block_item.update()
        self._refresh_interface(refresh)

    def _attach_to_slot(self, child_node, iface: InterfaceItem,
                        child_item: BlockItem = None):
        """把积木嵌入积木接口（slot）对应的树位置，并内嵌为母积木子项。

        撤销快照由调用入口 push（_create_and_embed / _on_blank_clicked /
        _on_drop_interface / 右键嵌入），此处不 push——否则"创建+嵌入"会
        产生"已创建未嵌入"的中间快照，撤销只能回到中间态（积木脱离成自由）。
        """
        parent_item = iface.parentItem()
        if not isinstance(parent_item, BlockItem):
            return
        parent_node = parent_item.node
        slot = iface.slot or ('children', 'append')
        # 设计记录：输出积木是终点，不能作为子积木嵌入
        if child_node.type == BlockType.OUTPUT:
            return
        # 值位接口拒绝符号元（数元接口 data 槽 / 输出积木 output 槽 /
        # 固定槽 children / 括号链值位）：符号只能出现在符号接口/缝隙嵌入符号位
        if child_node.type == BlockType.SYMBOL and not (
                slot[0] == 'children' and isinstance(slot[1], tuple)
                and slot[1][0] == 'insert'):
            return
        # 循环嵌套检测：parent_node 若已在 child_node 子树内，嵌入后成环
        if self._would_form_cycle(parent_node, child_node):
            self._reject_cycle()
            return
        # 从旧位置移除
        self._detach_node(child_node)
        if child_item is not None:
            self._release_parent(child_item)
        # 接入新位置
        if slot[0] == 'data':
            # 数元接口：填入 data.block
            if parent_node.data is None:
                from custom_calc.model import DataDef, InputKind
                parent_node.data = DataDef()
            parent_node.data.kind = InputKind.BLOCK
            parent_node.data.block = child_node
        elif slot[0] == 'children':
            idx = slot[1]
            if parent_node.type == BlockType.PAREN:
                # 括号链式：计算元接口只接值积木，拒绝单独的符号元
                # （符号是自动生成的；缝隙嵌入填符号位例外）
                if child_node.type == BlockType.SYMBOL:
                    return
                # 按接口位置接入
                # - 链中空缺（非末尾的占位）→ 补在该位置
                # - 链尾占位（最后一个占位）→ 追加（自动补符号）
                is_tail = idx >= len(parent_node.children) - 1
                if idx < len(parent_node.children) \
                        and parent_node.children[idx].is_interface \
                        and not is_tail:
                    self._fill_chain_gap(parent_node, child_node, idx)
                else:
                    self._append_to_chain(parent_node, child_node)
            elif idx == 'append':
                parent_node.children.append(child_node)
            elif isinstance(idx, tuple) and idx[0] == 'insert':
                self._insert_into_chain(parent_node, child_node, idx[1])
            else:
                # 固定槽替换：旧积木同时解除图形父子
                if idx < len(parent_node.children):
                    old = parent_node.children[idx]
                    parent_node.children[idx] = child_node
                    old_item = self._find_item_for_node(old)
                    if old_item is not None:
                        self._release_parent(old_item)
                else:
                    parent_node.children.append(child_node)
        elif slot[0] == 'output':
            if parent_node.children:
                old = parent_node.children[0]
                parent_node.children[0] = child_node
                old_item = self._find_item_for_node(old)
                if old_item is not None:
                    self._release_parent(old_item)
            else:
                parent_node.children.append(child_node)
        # 界面：内嵌为母积木子项，坐标相对母
        if child_item is not None:
            child_item.setParentItem(parent_item)
            child_item.setPos(iface.pos())
        parent_item._relayout_propagate()   # 母变大 + 父链逐级更新
        if child_item is not None:
            child_item.update()

    def _find_item_for_node(self, node) -> BlockItem | None:
        """按 node 查找场景中的 BlockItem。"""
        for it in self._scene.items():
            if it.node is node:
                return it
        return None

    # ------------------------------------------------------------------
    # 数据导出
    # ------------------------------------------------------------------

    def get_blocks(self) -> list[BlockNode]:
        """返回临时储存区积木列表（树根）。"""
        return [item.node for item in self._scene.items()]

    def validate(self) -> list[str]:
        """检查编辑器中的错误，返回错误列表（空=无错误）。

        传表格模型+方向 → validate_blocks 做数据级对齐预检
        （表+表位置对齐等，把运行时报错提前到检查报错）。
        """
        return validate_blocks([item.node for item in self._scene.items()],
                               getattr(self, '_model', None), self._direction)

    def closeEvent(self, event):
        self.result_blocks.emit(self.get_blocks())
        super().closeEvent(event)


# ----------------------------------------------------------------------
# 校验（模块级：编辑器实例与侧栏「检查报错」共用）
# ----------------------------------------------------------------------

def _node_to_dict(node) -> dict:
    """BlockNode → dict（积木配置序列化，递归含 children/data.block）。"""
    from custom_calc.model import DataDef
    return {
        'type': node.type.value,
        'x': node.x, 'y': node.y,
        'state': node.state,
        'updated_seq': node.updated_seq,
        'calc_subtype': node.calc_subtype.value if node.calc_subtype else None,
        'sym_kind': node.sym_kind.value if node.sym_kind else None,
        'sym_value': node.sym_value,
        'trig_func': node.trig_func,
        'children': [_node_to_dict(c) for c in node.children],
        'data': _data_to_dict(node.data),
        'output_target': node.output_target.value
        if node.output_target and hasattr(node.output_target, 'value')
        else node.output_target,
        'output_index': node.output_index,
    }


def _data_to_dict(data) -> dict | None:
    """DataDef → dict。"""
    if data is None:
        return None
    kind = data.kind
    # 容错：历史脏数据可能把 kind 存成字符串（'block'），枚举与字符串统一输出
    kind_val = kind.value if hasattr(kind, 'value') else kind
    return {
        'kind': kind_val,
        'index': data.index,
        'value': data.value,
        'block': _node_to_dict(data.block) if data.block else None,
        'range_axis': data.range_axis,
        'range_start': data.range_start,
        'range_end': data.range_end,
    }


def _node_from_dict(d) -> 'BlockNode':
    """dict → BlockNode（递归重建 children/data.block）。"""
    from custom_calc.model import (DataDef, CalcSubtype, SymKind, OutputTarget)
    n = BlockNode(type=BlockType(d['type']))
    n.x = d.get('x', 0.0)
    n.y = d.get('y', 0.0)
    n.state = d.get('state', 'normal')
    n.updated_seq = d.get('updated_seq', 0)
    cs = d.get('calc_subtype')
    n.calc_subtype = CalcSubtype(cs) if cs else None
    sk = d.get('sym_kind')
    n.sym_kind = SymKind(sk) if sk else None
    n.sym_value = d.get('sym_value')
    n.trig_func = d.get('trig_func')
    n.children = [_node_from_dict(c) for c in d.get('children', [])]
    n.data = _data_from_dict(d.get('data'))
    ot = d.get('output_target')
    n.output_target = OutputTarget(ot) if ot else None
    n.output_index = d.get('output_index')
    return n


def _data_from_dict(d) -> 'DataDef | None':
    """dict → DataDef。"""
    from custom_calc.model import DataDef, InputKind
    if d is None:
        return None
    data = DataDef()
    k = d.get('kind')
    data.kind = InputKind(k) if k else None
    data.index = d.get('index')
    data.value = d.get('value')
    b = d.get('block')
    data.block = _node_from_dict(b) if b else None
    data.range_axis = d.get('range_axis')
    data.range_start = d.get('range_start')
    data.range_end = d.get('range_end')
    return data


def _range_short_label(d) -> str:
    """范围输入的短标签（如 '范围:行2-6' / '范围:列B-F'）。"""
    from models.spreadsheet_model import SpreadsheetModel
    axis = '行' if d.range_axis == 'row' else '列'
    s = d.range_start + 1 if d.range_start is not None else '?'
    e = d.range_end + 1 if d.range_end is not None else '?'
    if axis == '列':
        s = SpreadsheetModel.col_letter(d.range_start) \
            if d.range_start is not None else '?'
        e = SpreadsheetModel.col_letter(d.range_end) \
            if d.range_end is not None else '?'
    return f'范围:{axis}{s}-{axis}{e}'


def _node_short_label(node) -> str:
    """积木节点短标签（数元接口接入积木时显示其自身标签）。

    设计记录（01-积木类型.md）：接口接入积木后显示积木本身的内容，
    不出现「积木」字样。
    """
    if node is None:
        return '?'
    t = node.type
    if t == BlockType.CALC:
        st = node.calc_subtype
        if st == CalcSubtype.NUM:
            d = node.data
            if d is None or not d.is_defined:
                return '数元?'
            from custom_calc.model import InputKind
            if d.kind == InputKind.ROW:
                return f'行{d.index + 1}'
            if d.kind == InputKind.COL:
                from models.spreadsheet_model import SpreadsheetModel
                return f'列{SpreadsheetModel.col_letter(d.index)}'
            if d.kind == InputKind.CONST:
                return f'{d.value:g}'
            if d.kind == InputKind.CLIPBOARD:
                return '剪贴板'
            if d.kind == InputKind.WHOLE_TABLE:
                return '整个表格'
            if d.kind == InputKind.RANGE:
                return _range_short_label(d)
            if d.kind == InputKind.BLOCK and d.block is not None:
                return _node_short_label(d.block)
            return '数元?'
        if st == CalcSubtype.EXP:
            return '^'
        if st == CalcSubtype.LOG:
            return 'log'
        if st == CalcSubtype.TRIG:
            return node.trig_func or 'sin'
        return '计算元?'
    if t == BlockType.SYMBOL:
        return node.sym_value or '?'
    if t == BlockType.PAREN:
        return '()'
    if t == BlockType.COUNT:
        return '计数'
    if t == BlockType.CHECK:
        return '检定'
    if t == BlockType.OUTPUT:
        return '输出'
    return '?'


def validate_blocks(roots: list[BlockNode], model=None,
                    direction: str = '') -> list[str]:
    """校验积木树，返回错误列表（空=无错误）。

    供编辑器 validate() 与控制器侧栏「检查报错」按钮共用。
    设计记录（05-数据模型.md 四、校验规则）。
    model + direction 可选：提供时做**数据级预检**——表+表位置对齐、
    剪贴板一维格数等运行时才报的错误，提前到检查报错阶段显示。
    """
    from custom_calc.model import SymKind, CalcSubtype, OutputTarget, InputKind
    errors: list[str] = []
    ctx = None
    if model is not None and direction:
        from custom_calc.engine import EvalContext
        ctx = EvalContext(model, direction)

    if not roots:
        errors.append('积木区空白，请先创建积木')
        return errors

    # 收集所有输出积木
    outputs = []
    for n in roots:
        _collect_outputs(n, outputs)

    if not outputs:
        errors.append('没有输出积木')
    for out in outputs:
        # 输出积木未连接计算元 / 直连非法类型 / 内部接口未定义
        if not out.children or out.children[0].is_interface:
            errors.append('输出积木未连接计算元')
        else:
            c0 = out.children[0]
            if c0.type == BlockType.SYMBOL:
                errors.append('输出积木不能直接接符号元')
            elif c0.type == BlockType.CALC and c0.calc_subtype is None:
                errors.append('输出积木的计算元未选择数据类型')
            elif c0.type == BlockType.CALC \
                    and c0.calc_subtype == CalcSubtype.NUM \
                    and (c0.data is None or not c0.data.is_defined):
                errors.append('输出积木的数元接口未定义')
            elif c0.type == BlockType.CALC \
                    and c0.calc_subtype == CalcSubtype.NUM \
                    and c0.data is not None \
                    and c0.data.kind == InputKind.RANGE:
                errors.append('范围输入仅用于计数积木（不能在输出积木中直连）')
        # 输出位置未选
        if out.output_target is None:
            errors.append('输出积木未选择输出位置')
        # 输出方向一致性（10 计划）：静态可判方向（数元列/行/全表/范围计数）→ 预检
        if out.output_target in (OutputTarget.ROW, OutputTarget.COL) \
                and out.children:
            kind = _static_result_kind(out.children[0])
            if kind in ('col', 'row'):
                target_kind = 'row' if out.output_target == OutputTarget.ROW \
                    else 'col'
                if kind != target_kind:
                    errors.append(
                        f'输出到{"行" if out.output_target == OutputTarget.ROW else "列"}'
                        f' 与结果一维表方向不一致（结果为'
                        f'{"垂直" if kind == "col" else "水平"}表）')
            elif kind == 'grid':
                errors.append('二维结果（全表/剪贴板二维）只能输出到剪贴板')

    # 输出位置重叠（静态只能判"确定重叠"；表结果交运行时按实际位置判定）
    # - 多个输出到剪贴板：剪贴板唯一，必然覆盖
    # - 同目标且结果确定是单值（直连检定/计数/常数）：写同一固定格
    clipboard_outs = [o for o in outputs
                      if o.output_target == OutputTarget.CLIPBOARD]
    if len(clipboard_outs) > 1:
        errors.append('多个输出积木输出到剪贴板（后者会覆盖前者）')
    seen_cell = {}
    for out in outputs:
        if out.output_target in (None, OutputTarget.CLIPBOARD):
            continue
        if not _is_scalar_output(out):
            continue   # 表结果：写回位置由数据决定，运行时判定
        cell = ('row', out.output_index) if out.output_target == OutputTarget.ROW \
            else ('col', out.output_index)
        if cell in seen_cell:
            errors.append('多个输出积木输出位置重叠')
            break
        seen_cell[cell] = True

    # 遍历所有节点检查：临时连接 / 待定义接口 / 未定义数元 / 数据级对齐
    for root in roots:
        _validate_node(root, errors, ctx)

    return errors


def _is_scalar_output(out) -> bool:
    """输出积木的结果是否**确定是单值**（静态可判）。

    检定/计数 → 单值；数元常数 → 单值；其余（表/链式/表达式）由数据决定。
    """
    from custom_calc.model import CalcSubtype, InputKind
    c0 = out.children[0] if out.children else None
    if c0 is None or c0.is_interface:
        return False
    if c0.type in (BlockType.COUNT, BlockType.CHECK):
        return True
    if c0.type == BlockType.CALC and c0.calc_subtype == CalcSubtype.NUM:
        d = c0.data
        return d is not None and d.kind == InputKind.CONST
    return False


def _static_result_kind(node) -> str | None:
    """静态判断输出积木子表达式的结果方向（用于输出方向一致性预检）。

    返回 'col'（垂直表）/ 'row'（水平表）/ 'grid' / 'scalar' / None（不确定）。
    """
    from custom_calc.model import CalcSubtype, InputKind
    if node is None:
        return None
    if node.type == BlockType.CALC and node.calc_subtype == CalcSubtype.NUM:
        d = node.data
        if d is None or not d.is_defined:
            return None
        if d.kind == InputKind.COL:
            return 'col'
        if d.kind == InputKind.ROW:
            return 'row'
        if d.kind == InputKind.CONST:
            return 'scalar'
        if d.kind == InputKind.WHOLE_TABLE:
            return 'grid'
        if d.kind == InputKind.RANGE:
            return 'col' if d.range_axis == 'row' else 'row'
        if d.kind == InputKind.BLOCK:
            return _static_result_kind(d.block)
        return None
    if node.type == BlockType.COUNT:
        d = node.children[0].data if node.children else None
        if d is not None and d.kind == InputKind.RANGE:
            return 'col' if d.range_axis == 'row' else 'row'
        return None
    return None


def _collect_outputs(node, outputs: list):
    if node.type == BlockType.OUTPUT:
        outputs.append(node)
    for c in node.children:
        _collect_outputs(c, outputs)
    if node.data is not None and node.data.block is not None:
        _collect_outputs(node.data.block, outputs)


def _is_chain_value(node) -> bool:
    """是否为链式"值"积木（计算元/括号/计数/检定；排除符号/占位接口）。"""
    if node.type in (BlockType.CALC, BlockType.PAREN,
                     BlockType.COUNT, BlockType.CHECK):
        return not node.is_interface
    return False


def _align_check(a_node, b_node, errors: list, ctx, where: str):
    """数据级预检：两侧数元都是表 → 位置对齐检查（把运行时报错提前）。

    复用引擎 `_align_tables_values`（覆盖位置不对齐/剪贴板一维格数不符/
    剪贴板二维与表位置不等）。一方全表另一方非全表：由计数积木全表检查
    报更准确的错（"全表只能配常数"），这里跳过。
    """
    from custom_calc.engine import EvalContext, Evaluator, TableValue, CalcError

    def _table_of(n):
        if n is None or n.type != BlockType.CALC \
                or n.calc_subtype != CalcSubtype.NUM:
            return None
        d = n.data
        if d is None or not d.is_defined:
            return None
        try:
            v = Evaluator(ctx)._eval_data(d)
        except Exception:
            return None
        return v if isinstance(v, TableValue) else None

    a = _table_of(a_node)
    b = _table_of(b_node)
    if a is None or b is None:
        return
    if a.is_grid != b.is_grid:
        return   # 一方全表：由计数积木全表检查报"只能配常数"
    try:
        EvalContext._align_tables_values(a, b)
    except CalcError as e:
        errors.append(f'{where}：{e}')


def _clipboard_is_2d() -> bool:
    """当前剪贴板是否为二维表（Tab+换行混合）。"""
    from PyQt6.QtWidgets import QApplication
    text = QApplication.clipboard().text()
    if not text.strip():
        return False
    norm = text.replace('\r\n', '\n').replace('\r', '\n').strip()
    lines = norm.split('\n')
    return len(lines) > 1 and any('\t' in ln for ln in lines)


def _kind_is_grid_like(kind) -> bool:
    """该数据定义是否为二维（全表 / 剪贴板二维——检测地位等同，用户确认）。"""
    from custom_calc.model import InputKind
    if kind == InputKind.WHOLE_TABLE:
        return True
    if kind == InputKind.CLIPBOARD:
        return _clipboard_is_2d()
    return False


def _is_1d_like(kind) -> bool:
    """该数据定义是否为**确定一维**（行/列/剪贴板一维；全表与剪贴板二维不算）。"""
    from custom_calc.model import InputKind
    if kind in (InputKind.ROW, InputKind.COL):
        return True
    if kind == InputKind.CLIPBOARD:
        return not _clipboard_is_2d()
    return False


def _validate_node(node, errors: list, ctx=None):
    """递归检查节点及其子结构。

    设计记录（05-数据模型.md 四、校验规则）：
    - 临时连接 / 链内空缺 / 未定义符号 / 未定义数元 / 计算元未选类型
    - 括号链结构完整性（值/符号数量匹配、表达式非空）
    - 计数积木：一方全表输入 → 另一方只接受单值常数
    - 检定积木：两边只接受单值（拒绝表格）
    - 数据级预检（ctx 提供时）：表+表位置对齐 / 剪贴板一维格数
    """
    from custom_calc.model import CalcSubtype, InputKind
    # 临时连接 / 待定义接口（顶层自由积木不算，只算链内）
    if node.is_temp_connect:
        errors.append('存在临时连接（红色虚线），需处理后才能输出')
    # 链式结构检查（仅括号）：链尾占位是正常的"可继续添加"接口；
    # 链中空缺 / 未定义符号 / 未定义数元 / 计算元胚 都是错误
    if node.type == BlockType.PAREN and node.children:
        n_children = node.children
        chain_vals = 0   # 值积木数（含未定义数元/计算元胚：结构上算值）
        chain_ops = 0    # 已定义符号数
        for i, c in enumerate(n_children):
            is_last = (i == len(n_children) - 1)
            if c.is_interface:
                if not is_last:
                    errors.append('链中存在空缺接口，需处理后才能输出')
                continue
            if c.type == BlockType.SYMBOL:
                if c.sym_value is None:
                    errors.append('链中存在未定义符号，需选择运算符号')
                else:
                    chain_ops += 1
                continue
            if c.type == BlockType.CALC:
                chain_vals += 1
                if c.calc_subtype == CalcSubtype.NUM:
                    if c.data is None or not c.data.is_defined:
                        errors.append('链中数元接口未定义')
                    elif c.data.kind == InputKind.RANGE:
                        errors.append('范围输入仅用于计数积木（不能在链式中使用）')
                elif c.calc_subtype is None:
                    errors.append('链中存在计算元未选择数据类型')
            elif c.type in (BlockType.PAREN, BlockType.COUNT, BlockType.CHECK):
                chain_vals += 1
        # 链结构完整性：至少 1 个值，符号数 = 值数 - 1
        if chain_vals == 0:
            errors.append('括号链中缺少计算元（表达式为空）')
        elif chain_ops != chain_vals - 1:
            errors.append('括号链表达式结构不完整（符号与计算元数量不匹配）')
        # 链式结构中值值相邻（如 [值, 值]）→ 临时连接
        if len(n_children) > 1:
            prev_is_value = _is_chain_value(n_children[0])
            for c in n_children[1:]:
                cur_is_value = _is_chain_value(c)
                if prev_is_value and cur_is_value:
                    errors.append('存在值值相邻（缺运算符号），需处理后才能输出')
                    break
                prev_is_value = cur_is_value
        # 数据级：相邻值对表+表对齐预检（链式 [表 + 表]）
        if ctx is not None:
            vals = [c for c in n_children if _is_chain_value(c)]
            for i in range(len(vals) - 1):
                _align_check(vals[i], vals[i + 1], errors, ctx, '括号链')
    # 计数/检定：全表 / 数元范围特化 / 表格限制（09 计划五、六；10 计划 v2）
    if node.type in (BlockType.COUNT, BlockType.CHECK) and len(node.children) >= 3:
        l_kind = getattr(node.children[0].data, 'kind', None)
        r_kind = getattr(node.children[2].data, 'kind', None)
        table_kinds = (InputKind.ROW, InputKind.COL, InputKind.CLIPBOARD)
        # 左数元范围特化（10 计划 v2）：范围输入仅用于计数积木；右侧须单值
        if l_kind == InputKind.RANGE:
            if node.type != BlockType.COUNT:
                errors.append('范围输入仅用于计数积木')
            if r_kind in table_kinds or r_kind == InputKind.WHOLE_TABLE:
                errors.append('范围输入右侧只接受单值常数')
        if node.type == BlockType.COUNT:
            # 二维输入（全表/剪贴板二维，地位等同——用户确认）只能与单值常数比较
            if _kind_is_grid_like(l_kind) and _is_1d_like(r_kind):
                errors.append('计数积木：二维输入（全表/剪贴板二维）'
                              '只能与单值常数比较')
            if _kind_is_grid_like(r_kind) and _is_1d_like(l_kind):
                errors.append('计数积木：二维输入（全表/剪贴板二维）'
                              '只能与单值常数比较')
            # 数据级：表+表（含全表/剪贴板二维）位置对齐预检
            if ctx is not None:
                _align_check(node.children[0], node.children[2], errors, ctx,
                             '计数积木')
        else:  # CHECK：10 计划接受一维表（逐元素 0/1 表），仍做对齐/方向预检
            if ctx is not None:
                _align_check(node.children[0], node.children[2], errors, ctx,
                             '检定积木')
    # 计算元固定槽（指数/对数）：表+表对齐预检
    if node.type == BlockType.CALC and ctx is not None \
            and node.calc_subtype in (CalcSubtype.EXP, CalcSubtype.LOG) \
            and len(node.children) >= 2:
        _align_check(node.children[0], node.children[1], errors, ctx,
                     '指数' if node.calc_subtype == CalcSubtype.EXP else '对数')
    # 三角未定义
    if node.type == BlockType.CALC \
            and node.calc_subtype == CalcSubtype.TRIG \
            and node.trig_func is None:
        errors.append('三角函数未定义，请选择函数')
    # 剪贴板为空（编辑器运行时可读剪贴板）
    if node.type == BlockType.CALC and node.calc_subtype == CalcSubtype.NUM:
        d = node.data
        if d is not None and d.kind == InputKind.CLIPBOARD:
            from PyQt6.QtWidgets import QApplication
            if not QApplication.clipboard().text().strip():
                errors.append('数元接口：剪贴板为空')
        # 数元范围特化（10 计划 v2）：完整性 + 顺序（范围仅用于计数积木，见链/检定检查）
        if d is not None and d.kind == InputKind.RANGE:
            if d.range_start is None or d.range_end is None:
                errors.append('数元范围未完整定义（起始/结尾）')
            elif d.range_start > d.range_end:
                errors.append('数元范围顺序错误（起始应 ≤ 结尾）')
    for c in node.children:
        _validate_node(c, errors, ctx)
    if node.data is not None and node.data.block is not None:
        _validate_node(node.data.block, errors, ctx)
