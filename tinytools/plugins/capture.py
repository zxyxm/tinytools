from PySide6.QtCore import QTimer
from screenshot import CAPTURE_KEY, CAPTURE_SHORTCUT, Controller
from tinytools.core import ToolSpec
from tinytools.preferences import HIDE_LAUNCHER_DURING_CAPTURE

SPEC = ToolSpec('capture', '截图与标注', '框选后直接标注，完成后复制 PNG',
                ('截图', '截屏', 'screenshot', 'capture', 'jt', 'jietu'), '▣', CAPTURE_SHORTCUT,
                hotkey_key=ord(CAPTURE_KEY))


class CaptureTool:
    def __init__(self, context):
        self.context = context
        self.controller = Controller(context.app, standalone=False,
                                     on_capture=context.on_capture, on_error=context.capture_error)
        self.pending = QTimer()
        self.pending.setSingleShot(True)
        self.pending.timeout.connect(lambda: self.capture(self.context.resume_launcher))

    def activate(self):
        if self.pending.isActive() or self.controller.selector is not None:
            return
        if self.context.settings.value(HIDE_LAUNCHER_DURING_CAPTURE, False, type=bool):
            hide = self.context.suspend_launcher or self.context.hide_launcher
            hide()
            # Let the panel and its edge button disappear before grabbing the desktop.
            self.pending.start(180)
        else:
            hold = self.context.hold_launcher
            if hold is not None:
                hold(True)
            self.capture(when_finished=(lambda: hold(False)) if hold is not None else None)

    def capture(self, when_finished=None):
        self.controller.capture()
        if when_finished is not None:
            if self.controller.selector is None:
                when_finished()
            else:
                self.controller.selector.finished.connect(when_finished)

    def can_exit(self):
        for editor in list(self.controller.editors):
            if not editor.close():
                return False
        return True

    def edit_capture(self, image, *, queue_paths=(), queue_index=0):
        self.controller.edit(image, confirm_close=False, queue_paths=queue_paths, queue_index=queue_index)

    def shutdown(self):
        self.pending.stop()
        if self.controller.selector:
            self.controller.selector.close()


def create_tool(context):
    return CaptureTool(context)
