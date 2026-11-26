from PySide6.QtCore import QEvent, QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QIcon, QImage, QPixmap
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QListView, QListWidget, QListWidgetItem,
                               QMessageBox, QPushButton, QSizePolicy, QVBoxLayout, QWidget)

from screenshot import copy_capture, ensure_capture_directory


class CaptureQueue(QWidget):
    EDGE_SCROLL_ZONE = 36
    EDGE_SCROLL_STEP = 12

    def __init__(self):
        super().__init__()
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        header = QHBoxLayout()
        self.heading = QLabel('截图队列（0）')
        self.heading.setObjectName('captureQueueHeading')
        header.addWidget(self.heading)
        header.addStretch()
        self.open_folder_button = QPushButton('打开文件夹')
        self.open_folder_button.setObjectName('openCaptureFolder')
        self.open_folder_button.setAccessibleName('打开截图队列文件夹')
        self.open_folder_button.clicked.connect(self.open_folder)
        header.addWidget(self.open_folder_button)
        layout.addLayout(header)
        self.items = QListWidget()
        self.items.setObjectName('captureQueue')
        self.items.setAccessibleName('截图队列')
        self.items.setViewMode(QListView.ViewMode.IconMode)
        self.items.setMovement(QListView.Movement.Static)
        self.items.setFlow(QListView.Flow.LeftToRight)
        self.items.setWrapping(False)
        self.items.setSelectionMode(QListView.SelectionMode.NoSelection)
        self.items.setMouseTracking(True)
        self.items.setIconSize(QSize(144, 90))
        self.items.setGridSize(QSize(158, 110))
        self.items.setFixedHeight(130)
        self.items.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.items.setHorizontalScrollMode(QListView.ScrollMode.ScrollPerPixel)
        self.items.itemClicked.connect(self.copy_item)
        layout.addWidget(self.items)
        self.scroll_pending = False
        self.scroll_timer = QTimer(self)
        self.scroll_timer.setSingleShot(True)
        self.scroll_timer.timeout.connect(self.scroll_to_latest)
        self.edge_direction = 0
        self.edge_timer = QTimer(self)
        self.edge_timer.setInterval(35)
        self.edge_timer.timeout.connect(self.scroll_at_edge)
        self.items.viewport().installEventFilter(self)
        self.items.hide()

    def open_folder(self):
        try:
            directory = ensure_capture_directory()
        except OSError:
            QMessageBox.warning(self, '无法打开截图文件夹', '无法访问截图目录，请检查应用数据目录的权限。')
            return
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(directory.as_posix())):
            QMessageBox.warning(self, '无法打开截图文件夹', f'系统无法打开该文件夹。\n{directory}')

    def append(self, path, image):
        size = self.items.iconSize()
        if image.width() > size.width() or image.height() > size.height():
            image = image.scaled(size, Qt.AspectRatioMode.KeepAspectRatio,
                                 Qt.TransformationMode.SmoothTransformation)
        item = QListWidgetItem(QIcon(QPixmap.fromImage(image)), '')
        item.setData(Qt.ItemDataRole.UserRole, str(path))
        item.setData(Qt.ItemDataRole.AccessibleTextRole, path.name)
        item.setToolTip(f'{path.name}\n单击复制 · 双击标注')
        self.items.insertItem(0, item)
        self.heading.setText(f'截图队列（{self.items.count()}）')
        self.edge_timer.stop()
        self.scroll_pending = True
        self.items.show()
        if self.isVisible():
            self.scroll_timer.start(0)

    def showEvent(self, event):
        super().showEvent(event)
        if self.scroll_pending:
            self.scroll_timer.start(0)

    def hideEvent(self, event):
        self.edge_timer.stop()
        super().hideEvent(event)

    def eventFilter(self, watched, event):
        viewport = self.items.viewport()
        if watched is viewport:
            if event.type() == QEvent.Type.MouseMove:
                self.update_edge_scroll(event.position().x(), viewport.width())
            elif event.type() == QEvent.Type.Leave:
                self.edge_timer.stop()
        return super().eventFilter(watched, event)

    def update_edge_scroll(self, x, width):
        bar = self.items.horizontalScrollBar()
        self.edge_direction = 0
        if x >= width - self.EDGE_SCROLL_ZONE and bar.value() < bar.maximum():
            self.edge_direction = 1
        elif x < self.EDGE_SCROLL_ZONE and bar.value() > bar.minimum():
            self.edge_direction = -1
        if not self.edge_direction:
            self.edge_timer.stop()
        elif not self.edge_timer.isActive():
            self.edge_timer.start()

    def scroll_at_edge(self):
        bar = self.items.horizontalScrollBar()
        previous = bar.value()
        bar.setValue(previous + self.edge_direction * self.EDGE_SCROLL_STEP)
        if bar.value() == previous:
            self.edge_timer.stop()

    def scroll_to_latest(self):
        if self.isVisible():
            bar = self.items.horizontalScrollBar()
            bar.setValue(bar.minimum())
            self.scroll_pending = False

    def copy_item(self, item):
        path = item.data(Qt.ItemDataRole.UserRole)
        image = QImage(path)
        if not image.isNull():
            copy_capture(path, image)
