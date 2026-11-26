import json
from pathlib import Path

from PySide6.QtCore import QDir, QSize, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QKeySequence, QShortcut
from PySide6.QtWidgets import (QApplication, QFileDialog, QHBoxLayout, QInputDialog, QLabel,
                               QListWidget, QListWidgetItem, QMenu, QMessageBox, QPushButton,
                               QStyle, QTabBar, QVBoxLayout, QWidget)


def path_drop_action(event):
    if not any(url.isLocalFile() for url in event.mimeData().urls()):
        return Qt.DropAction.IgnoreAction
    for action in (Qt.DropAction.LinkAction, Qt.DropAction.CopyAction):
        if event.possibleActions() & action:
            return action
    return Qt.DropAction.IgnoreAction


class CommonPaths(QWidget):
    interaction_finished = Signal()
    LEGACY_SETTINGS_KEY = 'launcher/commonPaths'
    GROUPS_SETTINGS_KEY = 'launcher/commonPathGroups'
    ROW_HEIGHT = 36
    VISIBLE_ROWS = 4

    def __init__(self, settings):
        super().__init__()
        self.settings = settings
        self.groups = self.load_groups()
        self.setAcceptDrops(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        header = QHBoxLayout()
        heading = QLabel('常用路径')
        heading.setObjectName('sectionHeading')
        header.addWidget(heading)
        header.addStretch()
        self.add_button = QPushButton('＋ 添加文件夹')
        self.add_button.clicked.connect(self.choose_folder)
        header.addWidget(self.add_button)
        self.open_group_button = QPushButton('打开本组')
        self.open_group_button.clicked.connect(self.open_group)
        header.addWidget(self.open_group_button)
        layout.addLayout(header)

        group_row = QHBoxLayout()
        self.tabs = QTabBar()
        self.tabs.setAccessibleName('常用分组')
        self.tabs.setUsesScrollButtons(True)
        self.tabs.setElideMode(Qt.TextElideMode.ElideRight)
        self.tabs.setExpanding(False)
        for group in self.groups:
            self.tabs.addTab(group['name'])
        group_row.addWidget(self.tabs, 1)
        new_group = QPushButton('＋ 分组')
        new_group.clicked.connect(self.add_group)
        group_row.addWidget(new_group)
        rename = QPushButton('重命名')
        rename.clicked.connect(self.rename_group)
        group_row.addWidget(rename)
        layout.addLayout(group_row)

        self.items = QListWidget()
        self.items.setObjectName('commonPaths')
        self.items.setAccessibleName('常用路径列表')
        self.items.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.items.itemClicked.connect(self.open_item)
        self.items.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.items.customContextMenuRequested.connect(self.show_path_menu)
        for key in ('Return', 'Enter'):
            shortcut = QShortcut(QKeySequence(key), self.items)
            shortcut.setContext(Qt.ShortcutContext.WidgetShortcut)
            shortcut.activated.connect(lambda: self.open_item(self.items.currentItem()))
        layout.addWidget(self.items)

        self.drop_hint = QLabel('拖入文件或文件夹，也可以直接拖到分组标签上')
        self.drop_hint.setObjectName('commonPathsDropHint')
        self.drop_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.drop_hint.setWordWrap(True)
        layout.addWidget(self.drop_hint)
        self.tabs.currentChanged.connect(self.show_group)
        self.show_group(self.tabs.currentIndex())

    def load_groups(self):
        if self.settings is not None:
            saved = self.settings.value(self.GROUPS_SETTINGS_KEY, '', type=str)
            try:
                groups = json.loads(saved)
            except json.JSONDecodeError:
                groups = None
            if (isinstance(groups, list) and groups and all(
                    isinstance(group, dict) and isinstance(group.get('name'), str)
                    and isinstance(group.get('paths'), list)
                    and all(isinstance(path, str) for path in group['paths']) for group in groups)):
                return groups
            legacy_paths = self.settings.value(self.LEGACY_SETTINGS_KEY, [], type=list)
        else:
            legacy_paths = []
        return [{'name': '分组1', 'paths': legacy_paths}, {'name': '分组2', 'paths': []}]

    def save(self):
        if self.settings is not None:
            self.settings.setValue(self.GROUPS_SETTINGS_KEY, json.dumps(self.groups, ensure_ascii=False))

    def add_group(self):
        names = {group['name'] for group in self.groups}
        number = 1
        while f'分组{number}' in names:
            number += 1
        name = f'分组{number}'
        self.groups.append({'name': name, 'paths': []})
        self.tabs.setCurrentIndex(self.tabs.addTab(name))
        self.save()

    def rename_group(self):
        index = self.tabs.currentIndex()
        group = self.groups[index]
        name, accepted = QInputDialog.getText(self, '重命名分组', '分组名称', text=group['name'])
        name = name.strip()
        if accepted and name and name != group['name']:
            if any(other['name'].casefold() == name.casefold() for other in self.groups if other is not group):
                QMessageBox.warning(self, '分组名称重复', '已有同名分组。')
            else:
                group['name'] = name
                self.tabs.setTabText(index, name)
                self.save()
        self.interaction_finished.emit()

    def show_group(self, index):
        self.items.clear()
        for path in self.groups[index]['paths']:
            self.append_item(path)
        self.update_list_height()

    def append_item(self, path):
        icon = self.style().standardIcon(QStyle.StandardPixmap.SP_FileLinkIcon)
        item = QListWidgetItem(icon, path)
        item.setToolTip(f'{path}\n单击打开，右键复制路径或移除')
        item.setSizeHint(QSize(0, self.ROW_HEIGHT))
        self.items.addItem(item)

    def update_list_height(self):
        count = self.items.count()
        self.items.setFixedHeight(min(count, self.VISIBLE_ROWS) * self.ROW_HEIGHT + 2 * self.items.frameWidth())
        self.items.setVisible(count > 0)
        self.open_group_button.setEnabled(count > 0)
        self.drop_hint.setMinimumHeight(60 if count == 0 else 28)

    def choose_folder(self):
        selected = QFileDialog.getExistingDirectory(self, '添加常用文件夹')
        if selected:
            self.add_paths(self.tabs.currentIndex(), [selected])
        self.interaction_finished.emit()

    def add_paths(self, index, paths):
        saved_paths = self.groups[index]['paths']
        rows = {Path(path): row for row, path in enumerate(saved_paths)}
        original_count = len(saved_paths)
        first_row = None
        for path in map(Path, paths):
            if path not in rows:
                rows[path] = len(saved_paths)
                saved_paths.append(str(path))
            if first_row is None:
                first_row = rows[path]

        if len(saved_paths) != original_count:
            self.save()
            if index == self.tabs.currentIndex():
                self.show_group(index)
        self.tabs.setCurrentIndex(index)
        if first_row is not None:
            self.items.setCurrentRow(first_row)
            self.items.scrollToItem(self.items.currentItem())

    def dragEnterEvent(self, event):
        action = path_drop_action(event)
        if action != Qt.DropAction.IgnoreAction:
            event.setDropAction(action)
            event.accept()

    def dragMoveEvent(self, event):
        self.dragEnterEvent(event)

    def dragLeaveEvent(self, event):
        self.interaction_finished.emit()

    def dropEvent(self, event):
        action = path_drop_action(event)
        if action == Qt.DropAction.IgnoreAction:
            return
        position = self.tabs.mapFrom(self, event.position().toPoint())
        index = self.tabs.tabAt(position)
        if index < 0:
            index = self.tabs.currentIndex()
        paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile() and url.toLocalFile()]
        if paths:
            self.add_paths(index, paths)
            event.setDropAction(action)
            event.accept()
        self.interaction_finished.emit()

    def open_item(self, item):
        if item is not None:
            self.open_paths([item.text()])

    def open_group(self):
        self.open_paths(self.groups[self.tabs.currentIndex()]['paths'])

    def open_paths(self, paths):
        failed = []
        for path in paths:
            try:
                available = Path(path).exists()
            except OSError:
                available = False
            if not available or not QDesktopServices.openUrl(QUrl.fromLocalFile(QDir.fromNativeSeparators(path))):
                failed.append(path)
        if failed:
            box = QMessageBox(QMessageBox.Icon.Warning, '无法打开路径',
                              f'有 {len(failed)} 个文件或文件夹无法打开。', parent=self)
            box.setDetailedText('\n'.join(failed))
            box.exec()
        self.interaction_finished.emit()

    def show_path_menu(self, position):
        item = self.items.itemAt(position)
        if item is None:
            return
        self.items.setCurrentItem(item)
        menu = QMenu(self)
        menu.addAction('复制路径', lambda: QApplication.clipboard().setText(item.text()))
        menu.addAction('移除', lambda: self.remove_item(item))
        menu.aboutToHide.connect(menu.deleteLater)
        menu.aboutToHide.connect(self.interaction_finished.emit)
        menu.popup(self.items.viewport().mapToGlobal(position))

    def remove_item(self, item):
        row = self.items.row(item)
        if row < 0:
            return
        self.groups[self.tabs.currentIndex()]['paths'].pop(row)
        self.items.takeItem(row)
        self.update_list_height()
        self.save()
