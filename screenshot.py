"""Windows screenshot and annotation tool. Run with Python 3.10+."""
import ctypes
from ctypes import wintypes
import math
import sys
from datetime import datetime

from PySide6.QtCore import Qt, QPoint, QPointF, QRect, QTimer, Signal, QAbstractNativeEventFilter, QLockFile, QDir
from PySide6.QtGui import (QAction, QActionGroup, QColor, QFont, QIcon, QImage,
                           QKeySequence, QPainter, QPen, QPixmap, QPolygonF)
from PySide6.QtWidgets import (QApplication, QColorDialog, QFileDialog, QInputDialog,
                               QLabel, QMainWindow, QMenu, QMessageBox, QScrollArea,
                               QSpinBox, QSystemTrayIcon, QToolBar, QWidget)


def rect_between(a, b):
    return QRect(QPoint(min(a.x(), b.x()), min(a.y(), b.y())),
                 QPoint(max(a.x(), b.x()), max(a.y(), b.y())))


def desktop_image():
    screens = QApplication.screens()
    bounds = QRect()
    for screen in screens:
        bounds = bounds.united(screen.geometry())
    image = QImage(bounds.size(), QImage.Format.Format_RGB32)
    image.fill(Qt.GlobalColor.black)
    painter = QPainter(image)
    for screen in screens:
        # Composite in logical coordinates, including negative monitor origins.
        target = screen.geometry().translated(-bounds.topLeft())
        capture = screen.grabWindow(0)
        if capture.isNull():
            painter.end()
            raise RuntimeError('无法读取屏幕，请确认桌面未锁定且当前会话允许截图。')
        painter.drawPixmap(target, capture)
    painter.end()
    return image, bounds


class Selector(QWidget):
    selected = Signal(QImage)
    finished = Signal()

    def __init__(self, image, bounds):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.image = image
        self.start = None
        self.selection = QRect()
        self.setGeometry(bounds)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setMouseTracking(True)

    def paintEvent(self, event):
        p = QPainter(self)
        p.drawImage(0, 0, self.image)
        p.fillRect(self.rect(), QColor(0, 0, 0, 110))
        if not self.selection.isEmpty():
            p.drawImage(self.selection, self.image, self.selection)
            p.setPen(QPen(QColor('#22c55e'), 2))
            p.drawRect(self.selection.adjusted(0, 0, -1, -1))
        label = '拖动框选 · 松开进入编辑 · Esc / 右键取消'
        if self.start is not None:
            label = f'{self.selection.width()} × {self.selection.height()}   ' + label
        p.fillRect(16, 16, 530, 36, QColor(20, 24, 30, 225))
        p.setPen(Qt.GlobalColor.white)
        p.drawText(QRect(28, 16, 510, 36), Qt.AlignmentFlag.AlignVCenter, label)
        p.end()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton:
            self.close()
        elif event.button() == Qt.MouseButton.LeftButton:
            self.start = event.position().toPoint()
            self.selection = QRect(self.start, self.start)

    def mouseMoveEvent(self, event):
        if self.start is not None:
            self.selection = rect_between(self.start, event.position().toPoint()).intersected(self.rect())
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.start is not None:
            self.mouseMoveEvent(event)
            if self.selection.width() >= 3 and self.selection.height() >= 3:
                crop = self.image.copy(self.selection)
                self.close()
                self.selected.emit(crop)
            else:
                self.start = None

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.close()

    def closeEvent(self, event):
        self.finished.emit()
        super().closeEvent(event)


class Canvas(QWidget):
    changed = Signal()

    def __init__(self, image):
        super().__init__()
        self.base = image.copy()
        self.operations = []
        self.redo_operations = []
        self.pending = None
        self.tool = '矩形'
        self.color = QColor('#ff453a')
        self.stroke_width = 3
        self.setFixedSize(image.size())
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
        p.drawImage(0, 0, self.render_image(preview=True))
        p.end()

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        point = event.position().toPoint()
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
            point = event.position().toPoint()
            point.setX(max(0, min(self.width_pixels - 1, point.x())))
            point.setY(max(0, min(self.base.height() - 1, point.y())))
            points = self.pending[1]
            if self.tool == '画笔' or len(points) == 1:
                points.append(point)
            else:
                points[-1] = point
            self.update()

    @property
    def width_pixels(self):
        return self.base.width()

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
    def __init__(self, image):
        super().__init__()
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle('轻截图 · 编辑')
        self.canvas = Canvas(image)
        self.saved_count = []
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
                                           ('复制', self.copy, 'Ctrl+C'), ('保存', self.save, 'Ctrl+S'),
                                           ('完成', self.finish, 'Return')]:
            action = toolbar.addAction(title, callback)
            action.setShortcut(QKeySequence(shortcut))
        self.statusBar().showMessage('拖动添加标注 · Enter 复制并关闭 · Ctrl+S 保存 · 马赛克拖动覆盖区域')
        available = QApplication.primaryScreen().availableGeometry()
        self.resize(min(max(image.width() + 40, 900), available.width()), min(max(image.height() + 120, 400), available.height()))
        self.exported = False

    def pick_color(self):
        color = QColorDialog.getColor(self.canvas.color, self, '标注颜色')
        if color.isValid():
            self.canvas.color = color

    def copy(self):
        QApplication.clipboard().setImage(self.canvas.render_image())
        self.exported = True
        self.saved_count = list(self.canvas.operations)
        self.statusBar().showMessage('已复制，可以粘贴到微信或其他应用', 5000)

    def save(self):
        path, _ = QFileDialog.getSaveFileName(self, '保存截图', f'截图_{datetime.now():%Y%m%d_%H%M%S}.png', 'PNG 图片 (*.png)')
        if path:
            if not path.lower().endswith('.png'):
                path += '.png'
            if self.canvas.render_image().save(path, 'PNG'):
                self.exported = True
                self.saved_count = list(self.canvas.operations)
                self.statusBar().showMessage(f'已保存：{path}', 5000)
            else:
                QMessageBox.warning(self, '保存失败', '请检查目标文件夹是否可写。')

    def finish(self):
        self.copy()
        self.close()

    def closeEvent(self, event):
        if not self.exported or self.saved_count != self.canvas.operations:
            answer = QMessageBox.question(self, '关闭截图', '截图尚未复制或保存，是否放弃？',
                                          QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                                          QMessageBox.StandardButton.Cancel)
            if answer != QMessageBox.StandardButton.Discard:
                event.ignore()
                return
        super().closeEvent(event)


class Hotkey(QAbstractNativeEventFilter):
    ID = 0x5343

    def __init__(self, callback):
        super().__init__()
        self.callback = callback
        self.registered = False

    def register(self):
        if self.registered:
            return True
        self.registered = bool(ctypes.windll.user32.RegisterHotKey(None, self.ID, 0x0001 | 0x4000, ord('A')))
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
    def __init__(self, app):
        self.app = app
        self.selector = None
        self.editors = []
        icon = QPixmap(32, 32)
        icon.fill(QColor('#16a34a'))
        p = QPainter(icon)
        p.setPen(QPen(Qt.GlobalColor.white, 2))
        p.drawRect(7, 8, 18, 15)
        p.drawEllipse(12, 12, 8, 8)
        p.end()
        app.setWindowIcon(QIcon(icon))
        self.tray = QSystemTrayIcon(QIcon(icon), app)
        self.tray.setToolTip('轻截图 · Alt+A')
        menu = QMenu()
        menu.addAction('截图  Alt+A', self.capture)
        menu.addAction('重新注册 Alt+A', self.register)
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
            self.tray.setToolTip('轻截图 · Alt+A 已启用')
            self.tray.showMessage('轻截图已就绪', '按 Alt+A 框选截图；右键托盘图标可退出。')
        else:
            self.tray.setToolTip('轻截图 · Alt+A 被占用，可右键截图')
            QMessageBox.warning(None, 'Alt+A 被其他程序占用',
                                '本工具无法注册 Alt+A。\n\n如果微信正在使用该快捷键，请在微信设置的快捷键选项中修改或关闭截图快捷键。\n然后右键本工具托盘图标，选择“重新注册 Alt+A”。\n\n现在也可以通过托盘菜单“截图”使用。')

    def capture(self):
        if self.selector is not None or QApplication.activeModalWidget():
            return
        try:
            image, bounds = desktop_image()
            self.selector = Selector(image, bounds)
            self.selector.selected.connect(self.edit)
            self.selector.finished.connect(self.selection_finished)
            self.selector.show()
            self.selector.activateWindow()
            self.selector.raise_()
        except Exception as error:
            self.selector = None
            QMessageBox.warning(None, '截图失败', str(error))

    def selection_finished(self):
        old = self.selector
        self.selector = None
        if old:
            old.deleteLater()

    def edit(self, image):
        editor = Editor(image)
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
    app.setApplicationName('轻截图')
    if sys.platform != 'win32':
        QMessageBox.critical(None, '平台不支持', '当前版本的全局快捷键仅支持 Windows。')
        return 1
    lock = QLockFile(QDir.tempPath() + '/tinytools-screenshot.lock')
    lock.setStaleLockTime(0)
    if not lock.tryLock(0):
        QMessageBox.information(None, '轻截图', '工具已经在运行，请按 Alt+A 或使用系统托盘中的绿色相机图标。')
        return 0
    app.setQuitOnLastWindowClosed(False)
    controller = Controller(app)
    return app.exec()


if __name__ == '__main__':
    sys.exit(main())
