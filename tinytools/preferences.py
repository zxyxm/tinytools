"""Shortcut entry and translation from Qt key sequences to Windows hotkeys."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QFormLayout, QKeySequenceEdit,
                               QLabel, QVBoxLayout)


HIDE_LAUNCHER_DURING_CAPTURE = 'capture/hide_launcher'
SHOW_TRAY_ICON = 'launcher/show_tray_icon'


def shortcut_binding(sequence):
    if sequence.count() != 1:
        raise ValueError('请输入一个组合键。')
    combination = sequence[0]
    modifiers = combination.keyboardModifiers()
    flags = Qt.KeyboardModifier
    modifier_bits = {flags.AltModifier: 1, flags.ControlModifier: 2,
                     flags.ShiftModifier: 4, flags.MetaModifier: 8}
    native_modifiers = sum(bit for flag, bit in modifier_bits.items() if modifiers & flag)
    if not native_modifiers & (1 | 2 | 8):
        raise ValueError('组合键需包含 Ctrl、Alt 或 Win。')

    key = combination.key()
    keys = Qt.Key
    if keys.Key_A <= key <= keys.Key_Z or keys.Key_0 <= key <= keys.Key_9 or key == keys.Key_Space:
        return native_modifiers, int(key)
    if keys.Key_F1 <= key <= keys.Key_F24:
        return native_modifiers, 0x70 + key - keys.Key_F1
    raise ValueError('主键请选择字母、数字、空格或 F1–F24。')


class ShortcutSettings(QDialog):
    def __init__(self, parent, shortcuts, defaults, failures, apply_shortcuts, *, show_tray_icon=False):
        super().__init__(parent)
        self.setWindowTitle('工作台设置')
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.setMinimumWidth(450)
        self.defaults = defaults
        self.apply_shortcuts = apply_shortcuts

        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.fields = {}
        for shortcut_id, (label, value) in shortcuts.items():
            field = QKeySequenceEdit(QKeySequence.fromString(value, QKeySequence.SequenceFormat.PortableText))
            field.setMaximumSequenceLength(1)
            field.setAccessibleName(label)
            form.addRow(label, field)
            self.fields[shortcut_id] = field
        layout.addLayout(form)

        hint = QLabel('点击输入框后按下组合键。支持 Ctrl、Alt、Win，可搭配 Shift；主键支持字母、数字、空格及 F1–F24。')
        hint.setObjectName('muted')
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.tray_option = QCheckBox('在系统托盘显示工作台图标')
        self.tray_option.setChecked(show_tray_icon)
        layout.addWidget(self.tray_option)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setStyleSheet('color: #a12430;')
        self.set_status(failures)
        layout.addWidget(self.status)

        buttons = QDialogButtonBox()
        self.save_button = buttons.addButton('保存', QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton('取消', QDialogButtonBox.ButtonRole.RejectRole)
        reset = buttons.addButton('恢复默认值', QDialogButtonBox.ButtonRole.ResetRole)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        reset.clicked.connect(self.reset)
        layout.addWidget(buttons)
        self.setFocus()

    def set_status(self, message):
        self.status.setText(message)
        self.status.setVisible(bool(message))

    def reset(self):
        for shortcut_id, field in self.fields.items():
            field.setKeySequence(QKeySequence.fromString(self.defaults[shortcut_id],
                                                         QKeySequence.SequenceFormat.PortableText))
        self.tray_option.setChecked(False)
        self.set_status('')

    def save(self):
        error = self.apply_shortcuts({key: field.keySequence() for key, field in self.fields.items()})
        self.set_status(error)
        if not error:
            self.accept()
