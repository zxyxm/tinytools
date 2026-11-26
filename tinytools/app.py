import logging
from pathlib import Path
import sys

from PySide6.QtCore import (QDir, QEvent, QLockFile, QRect, QRectF, QSettings, QSize, QStandardPaths,
                            Qt, QTimer, Signal)
from PySide6.QtGui import (QColor, QCursor, QFont, QIcon, QImage, QKeySequence, QLinearGradient,
                           QPainter, QPainterPath, QPen, QShortcut)
from PySide6.QtWidgets import (QApplication, QCheckBox, QDialog, QHBoxLayout, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QMenu, QMessageBox, QPushButton,
                               QStyledItemDelegate, QSystemTrayIcon, QVBoxLayout, QWidget)

from screenshot import Hotkey
from tinytools.brand import APP_TITLE, app_icon
from tinytools.capture_queue import CaptureQueue
from tinytools.common_paths import CommonPaths, path_drop_action
from tinytools.core import Registry, ToolContext
from tinytools.preferences import (HIDE_LAUNCHER_DURING_CAPTURE, SHOW_TRAY_ICON,
                                   ShortcutSettings, shortcut_binding)


CAPTURE_BACKUP = 'Ctrl+Alt+Z'


STYLE = '''
QWidget { font-family: "Microsoft YaHei UI"; font-size: 14px; color: #243247; }
QWidget#launcher { background: #f5f7fb; }
QWidget#launcherResizeHandle { border-left: 2px solid #dce4f0; }
QWidget#launcherResizeHandle:hover { border-left-color: #729cf4; }
QLabel#heading { font-size: 26px; font-weight: bold; color: #172b4d; }
QLabel#muted { color: #64748b; }
QLabel#captureQueueHeading { font-size: 15px; font-weight: bold; }
QLineEdit { background: white; border: 2px solid #dce4f0; border-radius: 12px; padding: 14px; font-size: 18px; }
QLineEdit:focus { border-color: #729cf4; }
QListWidget { background: transparent; border: none; outline: none; }
QListWidget::item { background: white; border: 1px solid #e0e6ef; border-radius: 10px; padding: 14px; margin-bottom: 10px; }
QListWidget::item:selected { background: #eaf1ff; border: 1px solid #729cf4; color: #1742a0; }
QListWidget#tools::item { padding: 8px 12px; margin-bottom: 5px; }
QListWidget#commonPaths::item { padding: 4px 10px; margin-bottom: 4px; }
QLabel#sectionHeading { font-size: 13px; font-weight: bold; color: #52647c; }
QLabel#commonPathsDropHint { color: #52647c; background: #edf2f9; border: 1px dashed #a8b9d1;
    border-radius: 8px; padding: 4px 10px; }
QListWidget#captureQueue::item { padding: 4px; margin: 2px; }
QListWidget#captureQueue::item:hover { background: #eaf1ff; border: 1px solid #729cf4; }
QPushButton { background: #edf1f7; border: none; border-radius: 7px; padding: 10px 16px; }
QPushButton:hover { background: #dce6f7; }
QPushButton#openCaptureFolder { padding: 5px 10px; }
QPushButton#primary { background: #2563eb; color: white; }
QPushButton#quit { background: #fbecee; color: #9f2338; padding: 10px 12px; }
QPushButton#quit:hover { background: #f6dbe0; }
QPushButton#pin:checked { background: #dbeafe; color: #1742a0; }
QPushButton:disabled { color: #94a3b8; background: #eef0f3; }
QSpinBox { padding: 9px; background: white; border: 1px solid #dce4f0; border-radius: 6px; }
QMenu { background: white; padding: 5px; }
QMenu::item { padding: 8px 24px; }
QMenu::item:selected { background: #eaf1ff; }
'''


class EdgeTab(QPushButton):
    def __init__(self, flags):
        super().__init__('', None)
        self.setWindowFlags(flags | Qt.WindowType.WindowDoesNotAcceptFocus | Qt.WindowType.NoDropShadowWindowHint)
        self.setObjectName('edge')
        self.setWindowTitle('工作台侧边入口')
        self.setAccessibleName('展开工作台')
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAcceptDrops(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(44, 76)
        self.logo = app_icon()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        gradient = QLinearGradient(0, 0, 0, self.height())
        gradient.setColorAt(0, QColor('#514379' if self.underMouse() else '#413564'))
        gradient.setColorAt(1, QColor('#221b37'))
        painter.setBrush(gradient)
        painter.setPen(QPen(QColor('#74658d'), 1))
        painter.drawRoundedRect(QRectF(0.5, 0.5, self.width() + 14, self.height() - 1), 14, 14)

        self.logo.paint(painter, QRect(8, 8, 28, 28))
        arrow = QPainterPath()
        arrow.moveTo(25, 50)
        arrow.lineTo(19, 56)
        arrow.lineTo(25, 62)
        painter.setPen(QPen(QColor('#e5f7c5'), 2.4, Qt.PenStyle.SolidLine,
                            Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(arrow)
        painter.end()


class ToolListDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index):
        if index.flags() != Qt.ItemFlag.NoItemFlags:
            super().paint(painter, option, index)
            return

        painter.save()
        font = QFont(option.font)
        font.setPixelSize(13)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor('#52647c'))
        painter.drawText(option.rect.adjusted(12, 0, -12, 0),
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                         index.data(Qt.ItemDataRole.DisplayRole))
        painter.restore()


class CaptureVisibilitySwitch(QCheckBox):
    def __init__(self):
        super().__init__()
        self.setAccessibleName('截图时隐藏工作台')
        self.setToolTip('开启后，框选期间临时隐藏工作台')
        self.setFixedSize(38, 24)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def hitButton(self, position):
        return self.rect().contains(position)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        checked = self.isChecked()
        painter.setPen(QPen(QColor('#172b4d'), 1) if self.hasFocus() else Qt.PenStyle.NoPen)
        painter.setBrush(QColor('#2563eb' if checked else '#64748b'))
        painter.drawRoundedRect(1, 2, 36, 20, 10, 10)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor('#ffffff'))
        painter.drawEllipse(19 if checked else 5, 5, 14, 14)
        painter.end()


class Launcher(QWidget):
    settings_requested = Signal()
    quit_requested = Signal()
    WIDTH_SETTING = 'launcher/width'
    DEFAULT_WIDTH = 660
    MINIMUM_WIDTH = 540

    def __init__(self, registry, launch, settings=None):
        flags = Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
        super().__init__(None, flags)
        self.registry = registry
        self.launch = launch
        self.settings = settings
        self.favorites = settings.value('launcher/favorites', [], type=list) if settings is not None else []
        self.tool_shortcuts = {}
        self.suspended = False
        self.visible_before_suspend = False
        self.capture_holds_panel = False
        self.dock_screen = None
        self.preferred_width = (settings.value(self.WIDTH_SETTING, self.DEFAULT_WIDTH, type=int)
                                if settings is not None else self.DEFAULT_WIDTH)
        self.resize_start = None
        self.resize_handle = QWidget(self)
        self.resize_handle.setObjectName('launcherResizeHandle')
        self.resize_handle.setFixedWidth(8)
        self.resize_handle.setCursor(Qt.CursorShape.SizeHorCursor)
        self.resize_handle.setToolTip('左右拖动调整工作台宽度')
        self.resize_handle.installEventFilter(self)
        self.edge = EdgeTab(flags)
        self.edge.installEventFilter(self)
        self.edge.clicked.connect(self.reveal)
        self.retract_timer = QTimer(self)
        self.retract_timer.setSingleShot(True)
        self.retract_timer.setInterval(300)
        self.retract_timer.timeout.connect(self.retract_if_outside)
        QApplication.instance().primaryScreenChanged.connect(self.set_dock_screen)
        self.setObjectName('launcher')
        self.setWindowTitle(APP_TITLE)
        self.setWindowIcon(app_icon())
        self.resize(self.DEFAULT_WIDTH, 520)
        self.setMinimumWidth(self.MINIMUM_WIDTH)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 26, 28, 22)
        layout.setSpacing(16)
        header = QHBoxLayout()
        logo = QLabel()
        logo.setPixmap(app_icon().pixmap(48, 48))
        header.addWidget(logo)
        title = QLabel('工作台')
        title.setObjectName('heading')
        header.addWidget(title)
        header.addStretch()
        self.pin = QPushButton('📌 固定')
        self.pin.setObjectName('pin')
        self.pin.setCheckable(True)
        self.pin.setToolTip('固定工作台，鼠标移开时保持展开')
        self.pin.toggled.connect(self.update_pin)
        header.addWidget(self.pin)
        settings_button = QPushButton('⚙ 设置')
        settings_button.setToolTip('工作台设置（Ctrl+,）')
        settings_button.clicked.connect(self.settings_requested)
        header.addWidget(settings_button)
        close_button = QPushButton('×')
        close_button.setAccessibleName('收起工作台')
        close_button.setToolTip('收起工作台（Esc）')
        close_button.clicked.connect(self.collapse)
        header.addWidget(close_button)
        self.quit_button = QPushButton('彻底退出')
        self.quit_button.setObjectName('quit')
        self.quit_button.setToolTip('退出工作台及后台工具，释放全局快捷键')
        self.quit_button.clicked.connect(self.quit_requested)
        header.addWidget(self.quit_button)
        layout.addLayout(header)
        self.search = QLineEdit()
        self.search.setPlaceholderText('搜索工具，例如：截图、倒计时、timer…')
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.filter)
        self.search.returnPressed.connect(self.open_selected)
        layout.addWidget(self.search)
        self.results = QListWidget()
        self.results.setObjectName('tools')
        self.results.setAccessibleName('工具列表')
        self.results.setItemDelegate(ToolListDelegate(self.results))
        self.results.itemClicked.connect(self.open_item)
        self.results.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.results.customContextMenuRequested.connect(self.show_tool_menu)
        layout.addWidget(self.results, 1)
        self.empty = QLabel()
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.empty)
        self.common_paths = CommonPaths(settings)
        self.common_paths.interaction_finished.connect(self.schedule_retract)
        layout.addWidget(self.common_paths)
        layout.addStretch()
        self.capture_queue = CaptureQueue()
        layout.addWidget(self.capture_queue)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setObjectName('muted')
        layout.addWidget(self.status)
        footer = QHBoxLayout()
        footer.addWidget(QLabel('↑ ↓ 选择    Enter 打开    Esc 收起'))
        footer.addStretch()
        self.open_button = QPushButton('打开工具')
        self.open_button.setObjectName('primary')
        self.open_button.clicked.connect(self.open_selected)
        footer.addWidget(self.open_button)
        layout.addLayout(footer)
        self.shortcuts = []
        for key, handler in [('Escape', self.collapse), ('Return', self.open_selected),
                             ('Enter', self.open_selected), ('Ctrl+,', self.settings_requested.emit)]:
            parent = self.results if key in ('Return', 'Enter') else self
            shortcut = QShortcut(QKeySequence(key), parent)
            if key in ('Return', 'Enter'):
                shortcut.setContext(Qt.ShortcutContext.WidgetShortcut)
            shortcut.activated.connect(handler)
            self.shortcuts.append(shortcut)
        for widget in (self.search, self.results):
            for key, delta in [('Down', 1), ('Up', -1)]:
                shortcut = QShortcut(QKeySequence(key), widget)
                shortcut.setContext(Qt.ShortcutContext.WidgetShortcut)
                shortcut.activated.connect(lambda delta=delta: self.move_selection(delta))
                self.shortcuts.append(shortcut)
        self.filter('')
        self.set_dock_screen(QApplication.primaryScreen())

    def filter(self, query):
        self.results.clear()
        matches = self.registry.search(query)
        if query.strip():
            if matches:
                self.add_section('搜索结果', matches)
        else:
            favorites = [self.registry.specs[key] for key in self.favorites if key in self.registry.specs]
            if favorites:
                self.add_section('收藏', favorites)
            other_tools = [spec for spec in matches if spec.id not in self.favorites]
            if other_tools:
                self.add_section('其他工具' if favorites else '全部工具', other_tools)
        self.results.setVisible(bool(matches))
        rows_height = sum(self.results.item(row).sizeHint().height() for row in range(self.results.count()))
        self.results.setMaximumHeight(rows_height + 2 * self.results.frameWidth())
        self.empty.setText('没有找到工具，试试其他关键词。' if query.strip() else '当前没有可用工具。')
        self.empty.setVisible(not matches)
        self.open_button.setEnabled(bool(matches))
        if matches:
            self.move_selection(1)

    def add_section(self, title, specs):
        heading = QListWidgetItem(title)
        heading.setFlags(Qt.ItemFlag.NoItemFlags)
        heading.setSizeHint(QSize(0, 25))
        self.results.addItem(heading)
        for spec in specs:
            title = f'{spec.symbol}  {spec.name}'
            shortcut = self.tool_shortcuts.get(spec.id, spec.shortcut)
            if shortcut:
                title += f'    {shortcut}'
            item = QListWidgetItem(title + '\n' + spec.description)
            item.setData(Qt.ItemDataRole.UserRole, spec.id)
            item.setSizeHint(QSize(0, 70))
            self.results.addItem(item)
            if spec.id == 'capture' and self.settings is not None:
                self.add_capture_switch(item)

    def add_capture_switch(self, item):
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 14, 5)
        layout.addStretch()
        label = QLabel('截图时隐藏工作台')
        label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout.addWidget(label)
        switch = CaptureVisibilitySwitch()
        switch.setChecked(self.settings.value(HIDE_LAUNCHER_DURING_CAPTURE, False, type=bool))
        switch.toggled.connect(lambda checked: self.settings.setValue(HIDE_LAUNCHER_DURING_CAPTURE, checked))
        layout.addWidget(switch)
        self.results.setItemWidget(item, widget)

    def show_tool_menu(self, position):
        item = self.results.itemAt(position)
        tool_id = item.data(Qt.ItemDataRole.UserRole) if item else None
        if not tool_id:
            return
        self.results.setCurrentItem(item)
        self.retract_timer.stop()
        menu = QMenu(self)
        menu.setObjectName('toolMenu')
        favorite = menu.addAction('取消收藏' if tool_id in self.favorites else '收藏')
        favorite.triggered.connect(lambda: self.toggle_favorite(tool_id))
        menu.aboutToHide.connect(menu.deleteLater)
        menu.aboutToHide.connect(self.schedule_retract)
        menu.popup(self.results.viewport().mapToGlobal(position))

    def toggle_favorite(self, tool_id):
        if tool_id in self.favorites:
            self.favorites.remove(tool_id)
        else:
            self.favorites.append(tool_id)
        if self.settings is not None:
            self.settings.setValue('launcher/favorites', self.favorites)
        self.filter(self.search.text())
        for index in range(self.results.count()):
            item = self.results.item(index)
            if item.data(Qt.ItemDataRole.UserRole) == tool_id:
                self.results.setCurrentItem(item)
                break

    def move_selection(self, delta):
        count = self.results.count()
        row = self.results.currentRow()
        for _ in range(count):
            row = (row + delta) % count
            if self.results.item(row).data(Qt.ItemDataRole.UserRole):
                self.results.setCurrentRow(row)
                break

    def open_selected(self):
        self.open_item(self.results.currentItem())

    def open_item(self, item):
        tool_id = item.data(Qt.ItemDataRole.UserRole) if item else None
        if tool_id:
            self.launch(tool_id)

    def set_dock_screen(self, screen):
        if self.dock_screen is not None and self.dock_screen in QApplication.screens():
            self.dock_screen.availableGeometryChanged.disconnect(self.position_dock)
        self.finish_resize()
        self.dock_screen = screen
        if screen is not None:
            screen.availableGeometryChanged.connect(self.position_dock)
            self.position_dock()

    def position_dock(self):
        self.finish_resize()
        area = self.dock_screen.availableGeometry()
        self.setMinimumWidth(min(self.MINIMUM_WIDTH, area.width()))
        self.set_dock_width(self.preferred_width)
        self.edge.setGeometry(area.right() - self.edge.width() + 1,
                              area.top() + (area.height() - self.edge.height()) // 2,
                              self.edge.width(), self.edge.height())

    def set_dock_width(self, width):
        area = self.dock_screen.availableGeometry()
        width = max(self.minimumWidth(), min(width, area.width()))
        self.setGeometry(area.right() - width + 1, area.top(), width, area.height())

    def resizeEvent(self, event):
        self.resize_handle.setFixedHeight(event.size().height())
        super().resizeEvent(event)

    def eventFilter(self, watched, event):
        if watched is self.edge:
            if event.type() == QEvent.Type.Enter:
                self.reveal(activate=False)
            elif event.type() == QEvent.Type.DragEnter and path_drop_action(event) != Qt.DropAction.IgnoreAction:
                self.reveal(activate=False)
                self.schedule_retract()
        if watched is self.resize_handle:
            if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                if self.dock_screen is not None:
                    self.resize_start = (event.globalPosition().toPoint().x(), self.width())
                    self.retract_timer.stop()
                return True
            if self.resize_start is not None:
                if event.type() == QEvent.Type.MouseMove:
                    start_x, start_width = self.resize_start
                    self.set_dock_width(start_width + start_x - event.globalPosition().toPoint().x())
                    return True
                if (event.type() == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.LeftButton
                        or event.type() == QEvent.Type.UngrabMouse):
                    self.finish_resize()
                    self.schedule_retract()
                    return True
        return super().eventFilter(watched, event)

    def finish_resize(self):
        if self.resize_start is None:
            return
        _, start_width = self.resize_start
        self.resize_start = None
        if self.width() != start_width:
            self.preferred_width = self.width()
            if self.settings is not None:
                self.settings.setValue(self.WIDTH_SETTING, self.preferred_width)

    def hideEvent(self, event):
        self.finish_resize()
        super().hideEvent(event)

    def enterEvent(self, event):
        self.retract_timer.stop()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.schedule_retract()
        super().leaveEvent(event)

    def changeEvent(self, event):
        if event.type() == QEvent.Type.ActivationChange and not self.isActiveWindow():
            self.schedule_retract()
        super().changeEvent(event)

    def schedule_retract(self):
        if (self.isVisible() and self.resize_start is None
                and not self.pin.isChecked() and not self.capture_holds_panel):
            self.retract_timer.start()

    def retract_if_outside(self):
        if (self.isVisible() and self.resize_start is None
                and not self.pin.isChecked() and not self.capture_holds_panel
                and not QApplication.activeModalWidget()
                and not QApplication.activePopupWidget() and not self.geometry().contains(QCursor.pos())):
            self.collapse()

    def update_pin(self, checked):
        self.pin.setText('📌 取消固定' if checked else '📌 固定')
        self.pin.setToolTip('取消固定，鼠标移开时自动收起' if checked
                            else '固定工作台，鼠标移开时保持展开')
        if checked:
            self.retract_timer.stop()
        else:
            self.retract_timer.start()

    def reveal(self, *, activate=True):
        if self.suspended:
            return
        self.retract_timer.stop()
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, not activate)
        self.show()
        self.raise_()
        self.edge.hide()
        if activate:
            self.activateWindow()
            self.search.setFocus()
            self.search.selectAll()

    def collapse(self):
        self.pin.setChecked(False)
        self.retract_timer.stop()
        self.hide()
        self.search.clear()
        if not self.suspended:
            self.edge.show()

    def suspend(self):
        self.visible_before_suspend = self.isVisible()
        self.suspended = True
        self.retract_timer.stop()
        self.edge.hide()
        self.hide()

    def resume(self):
        self.suspended = False
        if self.visible_before_suspend:
            self.reveal(activate=False)
            self.schedule_retract()
        else:
            self.collapse()

    def hold_for_capture(self, hold):
        self.capture_holds_panel = hold
        if hold:
            self.retract_timer.stop()
        else:
            self.schedule_retract()

    def closeEvent(self, event):
        event.ignore()
        self.collapse()


class Toolbox:
    def __init__(self, app, settings=None):
        self.app = app
        self.settings = settings if settings is not None else QSettings()
        self.registry = Registry()
        self.registry.discover()
        self.window = Launcher(self.registry, self.activate, self.settings)
        self.window.settings_requested.connect(self.show_settings)
        self.window.quit_requested.connect(self.quit)
        self.settings_dialog = None
        self.context = ToolContext(app, self.settings, self.notify, self.window.collapse,
                                   suspend_launcher=self.window.suspend, resume_launcher=self.window.resume,
                                   on_capture=self.window.capture_queue.append,
                                   capture_error=self.window.status.setText,
                                   hold_launcher=self.window.hold_for_capture)
        self.window.capture_queue.items.itemDoubleClicked.connect(self.edit_capture)
        app.setWindowIcon(app_icon())
        self.tray = QSystemTrayIcon(app_icon(), app)
        self.tray.setToolTip(APP_TITLE)
        self.menu = QMenu()
        self.open_action = self.menu.addAction('打开工具箱', self.window.reveal)
        self.menu.addSeparator()
        self.tool_actions = {}
        for spec in self.registry.specs.values():
            self.tool_actions[spec.id] = self.menu.addAction(
                spec.name, lambda checked=False, tool_id=spec.id: self.activate(tool_id))
        self.menu.addSeparator()
        self.menu.addAction('工作台设置', self.show_settings)
        self.menu.addAction('重新注册快捷键', self.register_hotkeys)
        self.menu.addAction('退出工具箱', self.quit)
        self.tray.setContextMenu(self.menu)
        self.tray.activated.connect(self.tray_activated)
        self.tray.setVisible(self.settings.value(SHOW_TRAY_ICON, False, type=bool))
        self.shortcut_labels = {'launcher': '呼出工作台'}
        self.shortcut_defaults = {'launcher': 'Alt+Space'}
        self.hotkeys = {'launcher': Hotkey(self.window.reveal, 0x5344, key=0x20)}
        for index, spec in enumerate(self.registry.specs.values()):
            if spec.hotkey_key:
                callback = lambda tool_id=spec.id: self.activate(tool_id)
                self.hotkeys[spec.id] = Hotkey(callback, 0x6000 + index,
                                               spec.hotkey_modifiers, spec.hotkey_key)
        if 'capture' in self.hotkeys:
            self.shortcut_labels['capture'] = '截图'
            self.shortcut_defaults['capture'] = self.registry.specs['capture'].shortcut
        self.capture_backup = Hotkey(lambda: self.activate('capture'), 0x5345,
                                    *shortcut_binding(QKeySequence(CAPTURE_BACKUP))) if 'capture' in self.hotkeys else None
        self.shortcut_values = dict(self.shortcut_defaults)
        for key in self.shortcut_defaults:
            value = self.settings.value(f'launcher/hotkeys/{key}', self.shortcut_defaults[key], type=str)
            sequence = QKeySequence.fromString(value, QKeySequence.SequenceFormat.PortableText)
            try:
                modifiers, native_key = shortcut_binding(sequence)
            except ValueError:
                continue
            self.shortcut_values[key] = value
            self.hotkeys[key].modifiers, self.hotkeys[key].key = modifiers, native_key
        self.hotkey_conflicts = ''
        self.update_shortcut_labels()
        if sys.platform == 'win32':
            for hotkey in self.hotkeys.values():
                app.installNativeEventFilter(hotkey)
            if self.capture_backup is not None:
                app.installNativeEventFilter(self.capture_backup)
        app.aboutToQuit.connect(self.cleanup)
        self.window.collapse()
        QTimer.singleShot(0, self.register_hotkeys)

    def tray_activated(self, reason):
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self.window.reveal()

    def notify(self, title, message):
        if self.tray.isVisible():
            self.tray.showMessage(title, message, QSystemTrayIcon.MessageIcon.Information, 7000)

    def update_shortcut_labels(self, capture_shortcut=None):
        self.open_action.setText(f"打开工具箱  {self.shortcut_values['launcher']}")
        self.window.tool_shortcuts = {key: value for key, value in self.shortcut_values.items()
                                      if key in self.tool_actions}
        if capture_shortcut is not None:
            self.window.tool_shortcuts['capture'] = capture_shortcut
        for key, value in self.window.tool_shortcuts.items():
            self.tool_actions[key].setText(f'{self.registry.specs[key].name}  {value}')
        self.window.filter(self.window.search.text())

    def register_hotkeys(self):
        if self.settings_dialog is not None:
            return
        self.hotkey_conflicts = ''
        text = ' · '.join(f'{self.shortcut_values[key]} {label}' for key, label in self.shortcut_labels.items())
        capture_shortcut = None
        if sys.platform != 'win32':
            text = '当前系统不支持全局快捷键，请使用侧边入口。'
        else:
            failed = [key for key, hotkey in self.hotkeys.items() if not hotkey.register()]
            if failed:
                names = [self.shortcut_values.get(key) or self.registry.specs[key].name for key in failed]
                self.hotkey_conflicts = '快捷键被占用或系统保留：' + '、'.join(names)
                text = self.hotkey_conflicts + '。可在设置中修改。'
            if self.capture_backup is not None:
                if (self.shortcut_values['capture'] == self.shortcut_defaults['capture']
                        and self.capture_backup.register()):
                    text += f' · {CAPTURE_BACKUP} 备用截图'
                    if 'capture' in failed:
                        capture_shortcut = CAPTURE_BACKUP
                else:
                    self.capture_backup.close()
        if self.registry.errors:
            text += f'\n{len(self.registry.errors)} 个模块加载失败，详情见日志。'
        self.update_shortcut_labels(capture_shortcut)
        self.window.status.setText(text)
        self.tray.setToolTip(f'{APP_TITLE}\n{text}')

    def show_settings(self):
        if self.settings_dialog is not None or self.window.suspended:
            return
        if not self.window.isVisible():
            self.window.reveal()
        self.window.retract_timer.stop()
        # Let the shortcut fields receive even the combinations currently registered by this app.
        for key in self.shortcut_values:
            self.hotkeys[key].close()
        if self.capture_backup is not None:
            self.capture_backup.close()
        values = {key: (label, self.shortcut_values[key]) for key, label in self.shortcut_labels.items()}
        self.settings_dialog = ShortcutSettings(self.window, values, self.shortcut_defaults,
                                                self.hotkey_conflicts, self.apply_shortcuts,
                                                show_tray_icon=self.tray.isVisible())
        self.settings_dialog.finished.connect(self.finish_settings)
        self.settings_dialog.open()

    def finish_settings(self, result):
        if result == QDialog.DialogCode.Accepted:
            show_tray = self.settings_dialog.tray_option.isChecked()
            self.settings.setValue(SHOW_TRAY_ICON, show_tray)
            self.tray.setVisible(show_tray)
        self.settings_dialog.deleteLater()
        self.settings_dialog = None
        self.register_hotkeys()
        self.window.schedule_retract()

    def apply_shortcuts(self, sequences):
        bindings = {}
        for key, sequence in sequences.items():
            try:
                bindings[key] = shortcut_binding(sequence)
            except ValueError as error:
                return f'{self.shortcut_labels[key]}：{error}'
        if len(set(bindings.values())) != len(bindings):
            return '呼出工作台和截图不能使用同一个快捷键。'

        previous = {key: (self.hotkeys[key].modifiers, self.hotkeys[key].key) for key in bindings}
        changed = {key: binding for key, binding in bindings.items() if binding != previous[key]}
        for key, binding in changed.items():
            hotkey = self.hotkeys[key]
            hotkey.modifiers, hotkey.key = binding
            if sys.platform == 'win32' and not hotkey.register():
                for previous_key in changed:
                    old_hotkey = self.hotkeys[previous_key]
                    old_hotkey.close()
                    old_hotkey.modifiers, old_hotkey.key = previous[previous_key]
                return f'{self.shortcut_labels[key]}的快捷键被占用或由 Windows 保留，请换一个组合键。'

        for key, sequence in sequences.items():
            value = sequence.toString(QKeySequence.SequenceFormat.PortableText)
            self.shortcut_values[key] = value
            self.settings.setValue(f'launcher/hotkeys/{key}', value)
        self.update_shortcut_labels()
        return ''

    def activate(self, tool_id):
        try:
            self.registry.activate(tool_id, self.context)
            if tool_id != 'capture' and self.window.isVisible() and not self.window.pin.isChecked():
                self.window.collapse()
        except Exception as error:
            logging.exception('Failed to open tool: %s', tool_id)
            QMessageBox.warning(self.window, '工具打开失败', f'{error}\n其他工具仍然可用，详情见日志。')

    def edit_capture(self, item):
        items = self.window.capture_queue.items
        queue_paths = tuple(items.item(row).data(Qt.ItemDataRole.UserRole) for row in range(items.count()))
        queue_index = items.row(item)
        image = QImage(queue_paths[queue_index])
        if image.isNull():
            self.window.status.setText('无法打开截图，文件可能已被移动或删除。')
            return
        self.registry.instances['capture'].edit_capture(image, queue_paths=queue_paths, queue_index=queue_index)

    def quit(self):
        if self.registry.can_exit():
            self.app.quit()

    def cleanup(self):
        if self.settings_dialog is not None:
            self.settings_dialog.finished.disconnect(self.finish_settings)
            self.settings_dialog.close()
            self.settings_dialog.deleteLater()
            self.settings_dialog = None
        for hotkey in self.hotkeys.values():
            hotkey.close()
            if sys.platform == 'win32':
                self.app.removeNativeEventFilter(hotkey)
        if self.capture_backup is not None:
            self.capture_backup.close()
            if sys.platform == 'win32':
                self.app.removeNativeEventFilter(self.capture_backup)
        self.registry.shutdown()
        self.window.suspend()
        self.tray.hide()


def main():
    app = QApplication(sys.argv)
    app.setOrganizationName('TinyTools')
    app.setApplicationName('TinyTools')
    # Keep storage identifiers stable so existing preferences survive the rename.
    app.setApplicationDisplayName(APP_TITLE)
    app.setQuitOnLastWindowClosed(False)
    log_dir = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation))
    log_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=log_dir / 'tinytools.log', encoding='utf-8', level=logging.INFO,
                        format='%(asctime)s %(levelname)s %(message)s')
    lock = QLockFile(QDir.tempPath() + '/tinytools-toolbox.lock')
    lock.setStaleLockTime(0)
    if not lock.tryLock(0):
        QMessageBox.information(None, APP_TITLE, '工作台已在运行，请使用屏幕右侧的箭头入口。')
        return 0
    app.setStyleSheet(STYLE)
    toolbox = Toolbox(app)
    return app.exec()
