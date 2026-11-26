"""Windows screenshot and annotation tool. Run with Python 3.10+."""
import ctypes
from ctypes import wintypes
import logging
import math
from pathlib import Path
import sys
from datetime import datetime
from uuid import uuid4
from tinytools.brand import app_icon

from PySide6.QtCore import (Qt, QPoint, QPointF, QRect, QSize, QTimer, Signal, QAbstractNativeEventFilter,
                            QLockFile, QDir, QMimeData, QStandardPaths, QUrl)
from PySide6.QtGui import (QAction, QActionGroup, QColor, QCursor, QFont, QIcon, QImage,
                           QKeySequence, QPainter, QPen, QPixmap, QPolygonF)
from PySide6.QtWidgets import (QApplication, QButtonGroup, QColorDialog, QFileDialog, QGridLayout, QInputDialog,
                               QLabel, QMainWindow, QMenu, QMessageBox, QScrollArea,
                               QHBoxLayout, QPushButton, QSpinBox, QSystemTrayIcon, QToolBar, QToolButton, QWidget)
from tinytools.window_snap import visible_window_rects


CAPTURE_KEY = 'A'
CAPTURE_SHORTCUT = f'Alt+{CAPTURE_KEY}'


def rect_between(a, b):
    return QRect(QPoint(min(a.x(), b.x()), min(a.y(), b.y())),
                 QPoint(max(a.x(), b.x()), max(a.y(), b.y())))


def scale_rect(region, source, target_size):
    local = region.translated(-source.topLeft())
    x_scale = target_size.width() / source.width()
    y_scale = target_size.height() / source.height()
    left = round(local.x() * x_scale)
    top = round(local.y() * y_scale)
    right = round((local.x() + local.width()) * x_scale)
    bottom = round((local.y() + local.height()) * y_scale)
    return QRect(left, top, right - left, bottom - top)


class DesktopCapture:
    def __init__(self, screens, window_rects=()):
        self.screens = screens
        self.bounds = QRect()
        for geometry, _ in screens:
            self.bounds = self.bounds.united(geometry)
        self.windows = []
        for frame in window_rects:
            logical = QRect()
            for geometry, image in screens:
                # On Windows, Qt scales the size of each screen and preserves its native origin.
                physical = QRect(geometry.topLeft(), image.size())
                region = frame.intersected(physical)
                if not region.isEmpty():
                    logical = logical.united(scale_rect(region, physical, geometry.size()).translated(geometry.topLeft()))
            if not logical.isEmpty():
                self.windows.append(logical.translated(-self.bounds.topLeft()))

    def window_at(self, point):
        return next((window for window in self.windows if window.contains(point)), QRect())

    def paint_preview(self, painter):
        for geometry, image in self.screens:
            painter.drawImage(geometry.translated(-self.bounds.topLeft()), image, image.rect())

    def crop(self, selection):
        # The selector works in logical coordinates. Crop each intersected screen in its own pixels.
        selection = selection.translated(self.bounds.topLeft())
        parts = []
        for geometry, image in self.screens:
            region = selection.intersected(geometry)
            if not region.isEmpty():
                parts.append((region, image, scale_rect(region, geometry, image.size())))

        if len(parts) == 1 and parts[0][0] == selection:
            _, image, source = parts[0]
            crop = image.copy(source)
            crop.setDevicePixelRatio(1)
            return crop

        # A cross-screen PNG needs one scale. Use the largest to avoid shrinking high-DPI content.
        scale = max((image.devicePixelRatio() for _, image, _ in parts), default=1.0)
        size = QSize(round(selection.width() * scale), round(selection.height() * scale))
        result = QImage(size, QImage.Format.Format_RGB32)
        result.fill(Qt.GlobalColor.black)
        painter = QPainter(result)
        for region, image, source in parts:
            painter.drawImage(scale_rect(region, selection, size), image, source)
        painter.end()
        return result


def desktop_image():
    captures = []
    for screen in QApplication.screens():
        capture = screen.grabWindow(0)
        if capture.isNull():
            raise RuntimeError('无法读取屏幕，请确认桌面未锁定且当前会话允许截图。')
        captures.append((screen.geometry(), capture.toImage()))
    return DesktopCapture(captures, visible_window_rects())


def copy_capture(path, image):
    data = QMimeData()
    data.setUrls([QUrl.fromLocalFile(str(path))])
    data.setImageData(image)
    if sys.platform == 'win32':
        # DROPEFFECT_COPY keeps the source PNG available in the queue after pasting.
        data.setData('application/x-qt-windows-mime;value="Preferred DropEffect"', (1).to_bytes(4, 'little'))
    QApplication.clipboard().setMimeData(data)


def ensure_capture_directory():
    directory = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation)) / 'captures'
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def save_capture(image):
    directory = ensure_capture_directory()
    path = directory / f'截图_{datetime.now():%Y%m%d_%H%M%S}_{uuid4().hex[:10]}.png'
    if not image.save(str(path), 'PNG'):
        raise OSError('无法保存截图，请检查应用数据目录是否可写。')
    copy_capture(path, image)
    return path


class Selector(QWidget):
    selected = Signal(QImage)
    finished = Signal()

    def __init__(self, desktop):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.desktop = desktop
        self.start = None
        self.dragging = False
        self.selection = QRect()
        self.canvas = None
        self.setGeometry(desktop.bounds)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.selection = self.desktop.window_at(self.mapFromGlobal(QCursor.pos()))
        for key, callback in [('Ctrl+C', self.finish_capture), ('Esc', self.close),
                              ('Ctrl+Z', self.undo_annotation)]:
            action = QAction(self)
            action.setShortcut(QKeySequence(key))
            action.setAutoRepeat(False)
            action.triggered.connect(callback)
            self.addAction(action)

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), Qt.GlobalColor.black)
        self.desktop.paint_preview(p)
        p.fillRect(self.rect(), QColor(0, 0, 0, 110))
        if not self.selection.isEmpty():
            p.save()
            p.setClipRect(self.selection)
            self.desktop.paint_preview(p)
            p.restore()
            p.setPen(QPen(QColor('#22c55e'), 2))
            p.drawRect(self.selection.adjusted(-1, -1, 0, 0))
        if self.canvas is None:
            label = '单击选窗口 · 拖动框选 · Esc / 右键取消'
            if self.start is not None:
                label = f'{self.selection.width()} × {self.selection.height()}   ' + label
            p.fillRect(16, 16, 380, 36, QColor(20, 24, 30, 225))
            p.setPen(Qt.GlobalColor.white)
            p.drawText(QRect(28, 16, 356, 36), Qt.AlignmentFlag.AlignVCenter, label)
        p.end()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton:
            self.close()
        elif event.button() == Qt.MouseButton.LeftButton and self.canvas is None:
            self.start = event.position().toPoint()
            self.dragging = False
            self.selection = self.desktop.window_at(self.start)

    def mouseMoveEvent(self, event):
        if self.canvas is not None:
            return
        point = event.position().toPoint()
        if self.start is None:
            selection = self.desktop.window_at(point)
        else:
            self.dragging = self.dragging or (point - self.start).manhattanLength() >= 4
            selection = rect_between(self.start, point).intersected(self.rect()) if self.dragging else self.selection
        if selection != self.selection:
            self.selection = selection
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.start is not None:
            self.mouseMoveEvent(event)
            self.start = None
            if self.selection.width() >= 3 and self.selection.height() >= 3:
                self.open_draft()
            else:
                self.selection = QRect()
                self.update()

    def open_draft(self):
        self.canvas = Canvas(self.desktop.crop(self.selection), preview_size=self.selection.size(), parent=self)
        self.canvas.move(self.selection.topLeft())
        self.canvas.show()

        anchor = self.selection.bottomRight() + self.desktop.bounds.topLeft()
        geometry = next((screen for screen, _ in self.desktop.screens if screen.contains(anchor)), self.desktop.bounds)
        area = geometry.translated(-self.desktop.bounds.topLeft())
        toolbar = QWidget(self)
        toolbar.setObjectName('captureToolbar')
        toolbar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        toolbar.setStyleSheet('''
            QWidget#captureToolbar { background: #211b35; border: 1px solid #4d416a; border-radius: 7px; }
            QPushButton { background: transparent; color: #fff; border: none; border-radius: 4px; padding: 5px 6px; }
            QPushButton:hover, QPushButton:checked { background: #534471; }
            QPushButton#captureFinish { background: #c5f463; color: #211b35; font-weight: bold; }
            QPushButton#captureFinish:hover { background: #dbff94; }
        ''')
        layout = QGridLayout(toolbar)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(3)
        columns = max(1, min(7, (area.width() - 18) // 54))
        group = QButtonGroup(toolbar)
        buttons = []
        for name in ('矩形', '箭头', '画笔', '马赛克'):
            button = QPushButton(name)
            button.setCheckable(True)
            button.setChecked(name == self.canvas.tool)
            button.clicked.connect(lambda checked=False, tool=name: setattr(self.canvas, 'tool', tool))
            group.addButton(button)
            buttons.append(button)
        for name, callback in [('撤销', self.undo_annotation), ('取消', self.close), ('完成', self.finish_capture)]:
            button = QPushButton(name)
            button.clicked.connect(callback)
            buttons.append(button)
        buttons[-1].setObjectName('captureFinish')
        for index, button in enumerate(buttons):
            button.setFocusPolicy(Qt.FocusPolicy.TabFocus)
            layout.addWidget(button, index // columns, index % columns)
        toolbar.adjustSize()
        gap = 6
        x = max(area.left(), min(self.selection.right() + 1 - toolbar.width(), area.right() + 1 - toolbar.width()))
        y = self.selection.bottom() + gap
        if y + toolbar.height() > area.bottom() + 1:
            y = self.selection.top() - gap - toolbar.height()
        if y < area.top():
            y = area.bottom() + 1 - toolbar.height() - gap
        toolbar.move(x, max(area.top(), y))
        toolbar.show()
        self.setFocus(Qt.FocusReason.OtherFocusReason)
        self.update()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            event.accept()
            if not event.isAutoRepeat():
                self.finish_capture()
            return
        super().keyPressEvent(event)

    def undo_annotation(self):
        if self.canvas is not None:
            self.canvas.undo()

    def finish_capture(self):
        if self.canvas is not None:
            crop = self.canvas.render_image()
            self.close()
            self.selected.emit(crop)

    def closeEvent(self, event):
        self.finished.emit()
        super().closeEvent(event)


class Canvas(QWidget):
    changed = Signal()

    def __init__(self, image, *, preview_size=None, parent=None):
        super().__init__(parent)
        self.base = image.copy()
        self.operations = []
        self.redo_operations = []
        self.pending = None
        self.tool = '矩形'
        self.color = QColor('#ff453a')
        self.stroke_width = 3
        self.setFixedSize(image.size() if preview_size is None else preview_size)
        self.setCursor(Qt.CursorShape.CrossCursor)

    def render_image(self, preview=False):
        result = self.base.copy()
        ops = self.operations + ([self.pending] if preview and self.pending else [])
        for op in ops:
            tool, points, color, width, text = op
            rect = rect_between(points[0], points[-1]).intersected(result.rect())
            # Read the already rendered pixels, so later mosaic also covers annotations.
            if tool == '马赛克' and not rect.isEmpty():
                tile = result.copy(rect).scaled(max(1, rect.width() // 12), max(1, rect.height() // 12),
                                                Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.FastTransformation)
                p = QPainter(result)
                p.drawImage(rect, tile.scaled(rect.size(), Qt.AspectRatioMode.IgnoreAspectRatio,
                                            Qt.TransformationMode.FastTransformation))
                p.end()
                continue
            p = QPainter(result)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setPen(QPen(color, width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            if tool == '矩形':
                p.drawRect(rect)
            elif tool == '圆形':
                p.drawEllipse(rect)
            elif tool == '画笔':
                if len(points) == 1:
                    p.drawPoint(points[0])
                else:
                    p.drawPolyline(QPolygonF([QPointF(pt) for pt in points]))
            elif tool == '箭头':
                a, b = QPointF(points[0]), QPointF(points[-1])
                p.drawLine(a, b)
                angle = math.atan2(b.y() - a.y(), b.x() - a.x())
                length = 12 + width * 2
                p.setBrush(color)
                p.drawPolygon(QPolygonF([b, b - QPointF(length * math.cos(angle - .5), length * math.sin(angle - .5)),
                                            b - QPointF(length * math.cos(angle + .5), length * math.sin(angle + .5))]))
            elif tool == '文字':
                font = QFont('Microsoft YaHei')
                font.setPixelSize(16 + width * 2)
                p.setFont(font)
                p.drawText(QRect(points[0], result.rect().bottomRight()), Qt.TextFlag.TextWordWrap, text)
            p.end()
        return result

    def paintEvent(self, event):
        p = QPainter(self)
        p.drawImage(self.rect(), self.render_image(preview=True))
        p.end()

    def image_point(self, position):
        x = int(position.x() * self.base.width() / self.width())
        y = int(position.y() * self.base.height() / self.height())
        return QPoint(max(0, min(self.base.width() - 1, x)), max(0, min(self.base.height() - 1, y)))

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        point = self.image_point(event.position())
        if self.tool == '文字':
            text, ok = QInputDialog.getMultiLineText(self, '添加文字', '输入标注文字：')
            if ok and text.strip():
                self.operations.append((self.tool, [point], QColor(self.color), self.stroke_width, text))
                self.redo_operations.clear()
                self.changed.emit()
                self.update()
        else:
            self.pending = (self.tool, [point], QColor(self.color), self.stroke_width, '')

    def mouseMoveEvent(self, event):
        if self.pending:
            point = self.image_point(event.position())
            points = self.pending[1]
            if self.tool == '画笔' or len(points) == 1:
                points.append(point)
            else:
                points[-1] = point
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.pending:
            self.mouseMoveEvent(event)
            self.operations.append(self.pending)
            self.pending = None
            self.redo_operations.clear()
            self.changed.emit()
            self.update()

    def undo(self):
        if self.operations:
            self.redo_operations.append(self.operations.pop())
            self.changed.emit()
            self.update()

    def redo(self):
        if self.redo_operations:
            self.operations.append(self.redo_operations.pop())
            self.changed.emit()
            self.update()


class Editor(QMainWindow):
    def __init__(self, image, *, confirm_close=True, queue_paths=(), queue_index=0):
        super().__init__()
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle('截图编辑 · 工作台 Workstation')
        self.canvas = Canvas(image)
        self.confirm_close = confirm_close
        self.saved_count = []
        self.queue_paths = queue_paths
        self.queue_index = queue_index
        self.queue_edits = {}
        scroll = QScrollArea()
        scroll.setWidget(self.canvas)
        scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setCentralWidget(scroll)
        toolbar = QToolBar('标注')
        toolbar.setMovable(False)
        self.addToolBar(toolbar)
        group = QActionGroup(self)
        for name in ['矩形', '圆形', '箭头', '画笔', '文字', '马赛克']:
            action = toolbar.addAction(name)
            action.setCheckable(True)
            action.setChecked(name == '矩形')
            group.addAction(action)
            action.triggered.connect(lambda checked=False, tool=name: setattr(self.canvas, 'tool', tool))
        toolbar.addSeparator()
        toolbar.addAction('颜色', self.pick_color)
        toolbar.addWidget(QLabel(' 粗细 '))
        width = QSpinBox()
        width.setRange(1, 16)
        width.setValue(3)
        width.valueChanged.connect(lambda value: setattr(self.canvas, 'stroke_width', value))
        toolbar.addWidget(width)
        toolbar.addSeparator()
        for title, callback, shortcut in [('撤销', self.canvas.undo, 'Ctrl+Z'), ('重做', self.canvas.redo, 'Ctrl+Y'),
                                           ('复制', self.copy, 'Ctrl+C'), ('保存', self.save, 'Ctrl+S')]:
            action = toolbar.addAction(title, callback)
            action.setShortcut(QKeySequence(shortcut))
        finish = toolbar.addAction('完成', self.finish)
        finish.setShortcuts([QKeySequence('Return'), QKeySequence('Enter')])
        finish.setAutoRepeat(False)
        close = QAction('关闭截图', self)
        close.setShortcut(QKeySequence('Esc'))
        close.setAutoRepeat(False)
        close.triggered.connect(self.close)
        self.addAction(close)
        self.statusBar().showMessage('Enter 复制并关闭 · Delete 撤销最近标注 · Esc 关闭 · Ctrl+S 保存')
        if self.queue_paths:
            self.add_queue_navigation()
        available = QApplication.primaryScreen().availableGeometry()
        self.resize(min(max(image.width() + 40, 900), available.width()), min(max(image.height() + 120, 400), available.height()))

    def add_queue_navigation(self):
        controls = QWidget()
        layout = QHBoxLayout(controls)
        layout.setContentsMargins(0, 2, 6, 2)
        self.previous_action = self.add_queue_action(layout, '‹ 上一张', 'Left', -1)
        self.queue_position = QLabel()
        self.queue_position.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.queue_position)
        self.next_action = self.add_queue_action(layout, '下一张 ›', 'Right', 1)
        self.statusBar().addPermanentWidget(controls)
        self.update_queue_position()

    def add_queue_action(self, layout, title, key, delta):
        action = QAction(title, self)
        action.setShortcut(QKeySequence(key))
        action.triggered.connect(lambda: self.step_queue(delta))
        self.addAction(action)
        button = QToolButton()
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        button.setDefaultAction(action)
        layout.addWidget(button)
        return action

    def update_queue_position(self):
        self.queue_position.setText(f'{self.queue_index + 1} / {len(self.queue_paths)}')
        self.previous_action.setEnabled(self.queue_index > 0)
        self.next_action.setEnabled(self.queue_index + 1 < len(self.queue_paths))

    def step_queue(self, delta):
        index = self.queue_index + delta
        while 0 <= index < len(self.queue_paths):
            image = QImage(self.queue_paths[index])
            if not image.isNull():
                break
            index += delta
        else:
            self.statusBar().showMessage('这个方向没有可读取的截图。', 5000)
            return

        self.queue_edits[self.queue_index] = (self.canvas.operations, self.canvas.redo_operations, self.saved_count)
        self.queue_index = index
        self.canvas.operations, self.canvas.redo_operations, self.saved_count = self.queue_edits.get(index, ([], [], []))
        self.canvas.pending = None
        self.canvas.base = image
        self.canvas.setFixedSize(image.size())
        self.canvas.update()
        self.centralWidget().horizontalScrollBar().setValue(0)
        self.centralWidget().verticalScrollBar().setValue(0)
        self.statusBar().clearMessage()
        self.update_queue_position()

    def pick_color(self):
        color = QColorDialog.getColor(self.canvas.color, self, '标注颜色')
        if color.isValid():
            self.canvas.color = color

    def copy(self):
        QApplication.clipboard().setImage(self.canvas.render_image())
        self.saved_count = list(self.canvas.operations)
        self.statusBar().showMessage('已复制，可以粘贴到微信或其他应用', 5000)

    def save(self):
        path, _ = QFileDialog.getSaveFileName(self, '保存截图', f'截图_{datetime.now():%Y%m%d_%H%M%S}.png', 'PNG 图片 (*.png)')
        if path:
            if not path.lower().endswith('.png'):
                path += '.png'
            if self.canvas.render_image().save(path, 'PNG'):
                self.saved_count = list(self.canvas.operations)
                self.statusBar().showMessage(f'已保存：{path}', 5000)
            else:
                QMessageBox.warning(self, '保存失败', '请检查目标文件夹是否可写。')

    def finish(self):
        self.copy()
        self.close()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Delete and event.modifiers() == Qt.KeyboardModifier.NoModifier:
            if not event.isAutoRepeat():
                self.canvas.undo()
            event.accept()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event):
        if self.confirm_close and self.saved_count != self.canvas.operations:
            answer = QMessageBox.question(self, '关闭截图', '截图尚未复制或保存，是否放弃？',
                                          QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                                          QMessageBox.StandardButton.Cancel)
            if answer != QMessageBox.StandardButton.Discard:
                event.ignore()
                return
        super().closeEvent(event)


class Hotkey(QAbstractNativeEventFilter):
    ID = 0x5343

    def __init__(self, callback, hotkey_id=0x5343, modifiers=0x0001, key=ord(CAPTURE_KEY)):
        super().__init__()
        self.callback = callback
        self.ID = hotkey_id
        self.modifiers = modifiers
        self.key = key
        self.registered = False

    def register(self):
        if self.registered:
            return True
        self.registered = bool(ctypes.windll.user32.RegisterHotKey(None, self.ID, self.modifiers | 0x4000, self.key))
        return self.registered

    def close(self):
        if self.registered:
            ctypes.windll.user32.UnregisterHotKey(None, self.ID)
            self.registered = False

    def nativeEventFilter(self, event_type, message):
        msg = wintypes.MSG.from_address(int(message))
        if msg.message == 0x0312 and msg.wParam == self.ID:
            QTimer.singleShot(0, self.callback)
            return True, 0
        return False, 0


class Controller:
    def __init__(self, app, standalone=True, on_capture=None, on_error=None):
        self.app = app
        self.selector = None
        self.editors = []
        self.on_capture = on_capture
        self.on_error = on_error
        if not standalone:
            return
        app.setWindowIcon(app_icon())
        self.tray = QSystemTrayIcon(app_icon(), app)
        self.tray.setToolTip(f'工作台截图 · {CAPTURE_SHORTCUT}')
        menu = QMenu()
        menu.addAction(f'截图  {CAPTURE_SHORTCUT}', self.capture)
        self.latest_path = None
        self.edit_latest_action = menu.addAction('标注最近截图', self.edit_latest)
        self.edit_latest_action.setEnabled(False)
        menu.addAction(f'重新注册 {CAPTURE_SHORTCUT}', self.register)
        menu.addSeparator()
        menu.addAction('退出', self.quit)
        self.menu = menu
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(lambda reason: self.capture() if reason == QSystemTrayIcon.ActivationReason.DoubleClick else None)
        self.tray.show()
        self.hotkey = Hotkey(self.capture)
        app.installNativeEventFilter(self.hotkey)
        app.aboutToQuit.connect(self.hotkey.close)
        QTimer.singleShot(0, self.register)

    def register(self):
        if self.hotkey.register():
            self.tray.setToolTip(f'工作台截图 · {CAPTURE_SHORTCUT} 已启用')
        else:
            self.tray.setToolTip(f'工作台截图 · {CAPTURE_SHORTCUT} 被占用，可右键截图')

    def capture(self):
        if self.selector is not None or QApplication.activeModalWidget():
            return
        try:
            self.selector = Selector(desktop_image())
            self.selector.selected.connect(self.save_selection)
            self.selector.finished.connect(self.selection_finished)
            self.selector.show()
            self.selector.activateWindow()
            self.selector.raise_()
        except Exception as error:
            self.selector = None
            self.report_error(error)

    def save_selection(self, image):
        try:
            path = save_capture(image)
        except OSError as error:
            self.report_error(error)
            return
        if self.on_capture is not None:
            self.on_capture(path, image)
        if hasattr(self, 'edit_latest_action'):
            self.latest_path = path
            self.edit_latest_action.setEnabled(True)

    def edit_latest(self):
        image = QImage(str(self.latest_path))
        if image.isNull():
            self.report_error('无法打开截图，文件可能已被移动或删除。')
            return
        self.edit(image)

    def report_error(self, error):
        logging.error('Capture failed: %s', error)
        message = f'截图失败：{error}'
        if self.on_error is not None:
            self.on_error(message)
        elif hasattr(self, 'tray'):
            self.tray.setToolTip(message)

    def selection_finished(self):
        old = self.selector
        self.selector = None
        if old:
            old.deleteLater()

    def edit(self, image, *, confirm_close=True, queue_paths=(), queue_index=0):
        editor = Editor(image, confirm_close=confirm_close, queue_paths=queue_paths, queue_index=queue_index)
        self.editors.append(editor)
        editor.destroyed.connect(lambda: self.editors.remove(editor) if editor in self.editors else None)
        editor.show()
        editor.activateWindow()

    def quit(self):
        for editor in list(self.editors):
            if not editor.close():
                return
        self.app.quit()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName('工作台截图')
    if sys.platform != 'win32':
        QMessageBox.critical(None, '平台不支持', '当前版本的全局快捷键仅支持 Windows。')
        return 1
    lock = QLockFile(QDir.tempPath() + '/tinytools-screenshot.lock')
    lock.setStaleLockTime(0)
    if not lock.tryLock(0):
        QMessageBox.information(None, '工作台截图', f'工具已经在运行，请按 {CAPTURE_SHORTCUT} 或使用系统托盘中的 W 图标。')
        return 0
    app.setQuitOnLastWindowClosed(False)
    controller = Controller(app)
    return app.exec()


if __name__ == '__main__':
    sys.exit(main())
