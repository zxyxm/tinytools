from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QSpinBox,
                               QPushButton, QCheckBox, QMessageBox, QSlider)
from tinytools.core import ToolSpec
from tinytools.timer import Countdown

SPEC = ToolSpec('countdown', '倒计时', '支持暂停、窗口置顶、透明度调节和简约模式',
                ('计时器', 'timer', 'countdown', 'djs', 'daojishi', '番茄钟'), '◷')


class CountdownTool(QWidget):
    def __init__(self, context):
        super().__init__()
        self.context = context
        self.model = Countdown()
        self.setWindowTitle('倒计时 · 工作台 Workstation')
        self.full_size = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        title = QLabel('倒计时')
        title.setObjectName('heading')
        layout.addWidget(title)
        self.status = QLabel('设定一段时间，专注做好一件事。')
        layout.addWidget(self.status)
        self.display = QLabel()
        self.display.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.display)
        duration_panel = QWidget()
        duration_layout = QVBoxLayout(duration_panel)
        duration_layout.setContentsMargins(0, 0, 0, 0)
        inputs = QHBoxLayout()
        self.fields = []
        for label, maximum in [('时', 99), ('分', 59), ('秒', 59)]:
            spin = QSpinBox()
            spin.setRange(0, maximum)
            spin.setSuffix(' ' + label)
            spin.valueChanged.connect(self.configure)
            self.fields.append(spin)
            inputs.addWidget(spin)
        duration_layout.addLayout(inputs)
        presets = QHBoxLayout()
        self.presets = []
        for minutes in [1, 5, 10, 25]:
            button = QPushButton(f'{minutes} 分钟')
            button.clicked.connect(lambda checked=False, seconds=minutes * 60: self.set_duration(seconds))
            presets.addWidget(button)
            self.presets.append(button)
        duration_layout.addLayout(presets)
        layout.addWidget(duration_panel)
        actions = QHBoxLayout()
        self.start_button = QPushButton('开始')
        self.start_button.setObjectName('primary')
        self.start_button.clicked.connect(self.toggle)
        reset = QPushButton('重置')
        reset.clicked.connect(self.reset)
        actions.addWidget(self.start_button)
        actions.addWidget(reset)
        self.mode_button = QPushButton('简约模式')
        self.mode_button.setCheckable(True)
        actions.addWidget(self.mode_button)
        layout.addLayout(actions)
        options = QWidget()
        options_layout = QVBoxLayout(options)
        options_layout.setContentsMargins(0, 0, 0, 0)
        pin = QCheckBox('窗口置顶')
        pin.toggled.connect(self.set_pinned)
        appearance = QHBoxLayout()
        appearance.addWidget(pin)
        appearance.addSpacing(12)
        appearance.addWidget(QLabel('不透明度'))
        self.opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self.opacity_slider.setRange(45, 100)
        self.opacity_slider.setAccessibleName('不透明度')
        appearance.addWidget(self.opacity_slider, 1)
        self.opacity_value = QLabel()
        self.opacity_value.setMinimumWidth(self.opacity_value.fontMetrics().horizontalAdvance('100%'))
        self.opacity_value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        appearance.addWidget(self.opacity_value)
        options_layout.addLayout(appearance)
        options_layout.addWidget(QLabel('Enter 开始／暂停／继续 · Delete 重置 · Esc 收起'))
        options_layout.addWidget(QLabel('关闭窗口后继续计时，到时通过声音和通知提醒。'))
        layout.addWidget(options)
        self.full_widgets = [title, self.status, duration_panel, reset, options]
        for key, handler in [('Esc', self.close), ('Return', self.start_from_keyboard),
                             ('Enter', self.start_from_keyboard)]:
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.setAutoRepeat(False)
            shortcut.activated.connect(handler)
        saved = context.settings.value('countdown/seconds', 300, type=int)
        self.set_duration(max(1, min(359999, saved)))
        opacity = context.settings.value('countdown/opacity', 100, type=int)
        self.opacity_slider.setValue(opacity)
        self.apply_opacity(self.opacity_slider.value())
        self.opacity_slider.valueChanged.connect(self.set_opacity)
        compact = context.settings.value('countdown/compact', False, type=bool)
        self.apply_compact(compact)
        self.mode_button.setChecked(compact)
        self.mode_button.toggled.connect(self.set_compact)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(100)

    def set_duration(self, seconds):
        if self.model.state in ('running', 'paused'):
            return
        for spin, value in zip(self.fields, [seconds // 3600, seconds // 60 % 60, seconds % 60]):
            spin.blockSignals(True)
            spin.setValue(value)
            spin.blockSignals(False)
        self.configure()

    def configure(self):
        seconds = sum(spin.value() * multiplier for spin, multiplier in zip(self.fields, [3600, 60, 1]))
        if seconds > 0:
            self.model.configure(seconds)
            self.context.settings.setValue('countdown/seconds', seconds)
        self.start_button.setEnabled(seconds > 0)
        self.display.setText(self.model.display if seconds else '00:00:00')
        self.status.setText('准备就绪' if seconds else '请设置大于零的时长')

    def toggle(self):
        if self.model.tick():
            self.completed()
        elif self.model.state == 'running':
            self.model.pause()
        else:
            self.model.start()
        self.refresh()

    def start_from_keyboard(self):
        for field in self.fields:
            if field.isEnabled():
                field.interpretText()
        self.start_button.click()

    def reset(self):
        self.model.reset()
        self.configure()
        self.refresh()

    def completed(self):
        self.context.app.beep()
        self.context.notify('倒计时结束', '设定的时间已到。')
        self.show()
        self.raise_()
        self.context.app.alert(self, 10000)

    def refresh(self):
        if self.model.tick():
            self.completed()
        active = self.model.state in ('running', 'paused')
        for widget in self.fields + self.presets:
            widget.setEnabled(not active)
        self.start_button.setText({'running': '暂停', 'paused': '继续', 'finished': '再来一次', 'idle': '开始'}[self.model.state])
        if self.model.state != 'idle':
            self.status.setText({'running': '正在计时', 'paused': '已暂停', 'finished': '时间到！'}[self.model.state])
        if self.start_button.isEnabled():
            self.display.setText(self.model.display)

    def set_pinned(self, enabled):
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, enabled)
        self.show()

    def apply_opacity(self, percent):
        self.setWindowOpacity(percent / 100)
        self.opacity_value.setText(f'{percent}%')

    def set_opacity(self, percent):
        self.apply_opacity(percent)
        self.context.settings.setValue('countdown/opacity', percent)

    def apply_compact(self, compact):
        if compact and self.isVisible():
            self.full_size = self.normalGeometry().size()
            if self.isMaximized():
                self.showNormal()
        for widget in self.full_widgets:
            widget.setVisible(not compact)
        self.mode_button.setText('展开' if compact else '简约模式')
        margin = 12 if compact else 28
        vertical_margin = 8 if compact else 24
        self.layout().setContentsMargins(margin, vertical_margin, margin, vertical_margin)
        font_size, padding = (38, 2) if compact else (52, 20)
        self.display.setStyleSheet(f'font: {font_size}px "Consolas"; color: #2563eb; padding: {padding}px 0;')
        minimum_size = (0, 0) if compact else (480, 390)
        self.setMinimumSize(*minimum_size)
        self.layout().activate()
        self.resize(self.sizeHint() if compact or self.full_size is None else self.full_size)

    def set_compact(self, compact):
        self.apply_compact(compact)
        self.context.settings.setValue('countdown/compact', compact)

    def activate(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()
        self.start_button.setFocus()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Delete and event.modifiers() == Qt.KeyboardModifier.NoModifier:
            if not event.isAutoRepeat():
                self.reset()
            event.accept()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event):
        event.ignore()
        self.hide()

    def can_exit(self):
        if self.model.state in ('running', 'paused'):
            return QMessageBox.question(self, '退出工具箱', '倒计时尚未结束，退出将停止计时。是否退出？',
                                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                        QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes
        return True

    def shutdown(self):
        self.timer.stop()
        self.hide()


def create_tool(context):
    return CountdownTool(context)
