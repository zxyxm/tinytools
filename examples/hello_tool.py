"""Copy this file to tinytools/plugins/hello.py and restart Workstation."""
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QPushButton
from tinytools.core import ToolSpec

SPEC = ToolSpec('hello', '示例工具', '一个可以复制修改的工具模板', ('hello', 'example', '示例'), '◇')


class HelloTool(QWidget):
    def __init__(self, context):
        super().__init__()
        self.context = context
        self.setWindowTitle('示例工具 · 工作台 Workstation')
        self.resize(400, 220)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel('在这里实现你的工具界面。'))
        button = QPushButton('发送一条通知')
        button.clicked.connect(lambda: context.notify('示例工具', '工具已成功集成。'))
        layout.addWidget(button)

    def activate(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event):
        event.ignore()
        self.hide()

    def can_exit(self):
        return True

    def shutdown(self):
        self.hide()


def create_tool(context):
    return HelloTool(context)
