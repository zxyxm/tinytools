from pathlib import Path
import logging
from uuid import uuid4

from PySide6.QtCore import Qt, QTimer, QStandardPaths
from PySide6.QtGui import QFont, QKeySequence, QShortcut, QTextCharFormat, QTextDocument, QTextListFormat
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QListWidget,
                               QListWidgetItem, QLineEdit, QTextEdit, QToolBar, QPushButton,
                               QLabel, QColorDialog, QMessageBox, QFileDialog, QComboBox)
from tinytools.brand import app_icon
from tinytools.core import ToolSpec
from tinytools.notes import NoteStore

SPEC = ToolSpec('notes', '随记', '随手记录，支持思刻 Markdown 编辑、本地自动保存和搜索',
                ('note', 'notes', 'idea', '随手笔记', '思刻', 'scripta', '灵感', '便签', 'bj', 'biji'), '✎')


class NotesTool(QWidget):
    def __init__(self, context, store=None, enable_scripta=False):
        super().__init__()
        self.context = context
        self.store = store or NoteStore(Path(QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.AppLocalDataLocation)) / 'notes.sqlite3')
        self.current_id = None
        self.dirty = False
        self.loading = False
        self.closed_store = False
        self.scripta = None
        self.markdown = None
        self.editor_token = None
        self.editor_revision = 0
        self.saving = False
        self.setWindowTitle('随记 · 工作台 Workstation')
        self.setWindowIcon(app_icon())
        self.resize(920, 620)
        self.setMinimumSize(700, 470)
        self.autosave = QTimer(self)
        self.autosave.setSingleShot(True)
        self.autosave.setInterval(600)
        self.autosave.timeout.connect(lambda: self.save(flush=False))
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 16)
        header = QHBoxLayout()
        heading = QLabel('随记')
        heading.setObjectName('heading')
        header.addWidget(heading)
        header.addStretch()
        self.scripta_button = QPushButton('选择思刻目录')
        self.scripta_button.clicked.connect(self.configure_scripta)
        self.scripta_button.setVisible(enable_scripta)
        header.addWidget(self.scripta_button)
        new = QPushButton('＋ 新笔记')
        new.setObjectName('primary')
        new.clicked.connect(lambda: self.new_note())
        header.addWidget(new)
        outer.addLayout(header)
        split = QSplitter()
        sidebar = QWidget()
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(0, 12, 12, 0)
        self.search = QLineEdit()
        self.search.setPlaceholderText('搜索标题和正文')
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.filter_notes)
        self.search.returnPressed.connect(self.edit_selected_note)
        side.addWidget(self.search)
        self.items = QListWidget()
        self.items.currentItemChanged.connect(self.select_note)
        side.addWidget(self.items)
        delete = QPushButton('删除当前笔记')
        delete.setToolTip('笔记列表中可按 Delete 删除')
        delete.clicked.connect(self.delete_note)
        side.addWidget(delete)
        split.addWidget(sidebar)
        content = QWidget()
        self.content_layout = right = QVBoxLayout(content)
        right.setContentsMargins(12, 12, 0, 0)
        self.title = QLineEdit()
        self.title.setPlaceholderText('给这个 idea 起个名字…')
        self.title.setMaxLength(200)
        self.title.textChanged.connect(self.mark_dirty)
        self.title.returnPressed.connect(self.focus_editor)
        right.addWidget(self.title)
        self.toolbar = toolbar = QToolBar()
        toolbar.setStyleSheet('QToolButton { padding: 6px; }')
        self.formats = {}
        for name, shortcut, prop in [('粗体', 'Ctrl+B', 'bold'), ('斜体', 'Ctrl+I', 'italic'),
                                      ('下划线', 'Ctrl+U', 'underline')]:
            action = toolbar.addAction(name)
            action.setCheckable(True)
            action.setShortcut(shortcut)
            action.triggered.connect(lambda checked, kind=prop: self.format_text(kind, checked))
            self.formats[prop] = action
        self.size = QComboBox()
        self.size.addItems(['正文', '小标题', '大标题'])
        self.size.activated.connect(self.change_size)
        toolbar.addWidget(self.size)
        toolbar.addAction('颜色', self.choose_color)
        toolbar.addAction('• 列表', lambda: self.toggle_list(QTextListFormat.Style.ListDisc))
        toolbar.addAction('1. 列表', lambda: self.toggle_list(QTextListFormat.Style.ListDecimal))
        right.addWidget(toolbar)
        self.editor = QTextEdit()
        self.editor.setPlaceholderText('有什么想法？先记下来。\n\n支持粗体、斜体、标题、颜色和列表，停止输入后自动保存。')
        font = QFont('Microsoft YaHei UI')
        font.setPointSize(11)
        self.editor.setFont(font)
        self.editor.setStyleSheet('QTextEdit { background: white; border: 1px solid #dce4f0; border-radius: 8px; padding: 12px; }')
        self.editor.textChanged.connect(self.mark_dirty)
        self.editor.currentCharFormatChanged.connect(self.sync_format)
        right.addWidget(self.editor, 1)
        bottom = QHBoxLayout()
        self.status = QLabel('本地自动保存')
        self.status.setWordWrap(True)
        bottom.addWidget(self.status, 1)
        self.convert = QPushButton('创建思刻副本')
        self.convert.setToolTip('将正文转换为 Markdown，保留原笔记')
        self.convert.clicked.connect(self.copy_to_scripta)
        bottom.addWidget(self.convert)
        export = QPushButton('导出 HTML')
        export.clicked.connect(self.export_note)
        bottom.addWidget(export)
        right.addLayout(bottom)
        split.addWidget(content)
        split.setSizes([240, 640])
        split.setStretchFactor(1, 1)
        outer.addWidget(split, 1)
        self.save_button = QPushButton('保存')
        self.save_button.clicked.connect(lambda: self.save(report=True))
        bottom.insertWidget(1, self.save_button)
        for key, parent, handler in [('Esc', self, self.close),
                                     ('Ctrl+S', self, lambda: self.save(report=True)),
                                     ('Return', self.items, self.edit_selected_note),
                                     ('Enter', self.items, self.edit_selected_note),
                                     ('Delete', self.items, self.delete_selected_note)]:
            shortcut = QShortcut(QKeySequence(key), parent)
            if parent is self.items:
                shortcut.setContext(Qt.ShortcutContext.WidgetShortcut)
            shortcut.setAutoRepeat(False)
            shortcut.activated.connect(handler)
            if key == 'Esc':
                self.close_shortcut = shortcut
        records = self.store.list()
        note_id = records[0][0] if records else self.store.create()
        self.load(note_id)
        self.refresh_list()
        if enable_scripta:
            configured = context.settings.value('notes/scripta_dir', '', type=str)
            location = Path(configured) if configured else Path(__file__).resolve().parents[3] / 'Scripta'
            self.start_scripta(location)

    def configure_scripta(self):
        path = QFileDialog.getExistingDirectory(self, '选择思刻目录（包含 web 或 app）')
        if path and self.save(report=True) and self.start_scripta(Path(path), report=True):
            self.context.settings.setValue('notes/scripta_dir', path)

    def start_scripta(self, path, report=False):
        try:
            from tinytools.scripta import ScriptaEditor, find_assets
            assets = find_assets(path)
            if assets is None:
                raise ValueError('请选择思刻源码目录、桌面版安装目录或编辑器资源目录。')
            editor = ScriptaEditor(assets, self)
        except (ImportError, OSError, ValueError) as error:
            if report:
                QMessageBox.warning(self, '无法接入思刻', str(error))
            return False
        if self.scripta is not None:
            self.scripta.hide()
            self.scripta.deleteLater()
        self.scripta = editor
        editor.hide()
        self.content_layout.insertWidget(3, editor, 1)
        self.show_editor()
        editor.ready.connect(lambda: self.scripta_ready(editor))
        editor.failed.connect(lambda message: self.scripta_failed(editor, message))
        editor.bridge.changed.connect(self.scripta_changed)
        editor.bridge.save_requested.connect(lambda: self.save(report=True))
        return True

    def scripta_ready(self, editor):
        if editor is not self.scripta or self.closed_store:
            return
        self.scripta_button.setText('更换思刻目录')
        if self.markdown is None and self.editor.document().isEmpty() and not self.dirty:
            self.markdown = ''
        self.show_editor()

    def scripta_failed(self, editor, message):
        if editor is self.scripta:
            self.show_editor()
            self.status.setText(message + ' 可继续在随记中编辑。')

    def scripta_changed(self, token, revision, markdown):
        if token != self.editor_token or revision < self.editor_revision:
            return
        self.editor_revision = revision
        if markdown != self.markdown:
            self.markdown = markdown
            self.mark_dirty()

    def show_editor(self):
        use_scripta = self.markdown is not None and self.scripta is not None and self.scripta.prepared
        self.editor_token = uuid4().hex if use_scripta else None
        self.editor_revision = 0
        self.close_shortcut.setEnabled(not use_scripta)
        if self.scripta is not None:
            self.scripta.setVisible(use_scripta)
        self.editor.setVisible(not use_scripta)
        self.editor.setAcceptRichText(self.markdown is None)
        self.toolbar.setVisible(self.markdown is None)
        self.convert.setVisible(self.markdown is None and self.scripta is not None and self.scripta.prepared)
        if use_scripta:
            self.scripta.open_note(self.editor_token, self.title.text(), self.markdown)
        elif self.markdown is not None:
            previous = self.editor.blockSignals(True)
            self.editor.setPlainText(self.markdown)
            self.editor.blockSignals(previous)

    def focus_editor(self):
        (self.scripta if self.editor_token else self.editor).setFocus()

    def copy_to_scripta(self):
        if self.markdown is not None or not self.save(report=True):
            return
        markdown = self.editor.toMarkdown()
        self.new_note((self.title.text() or '未命名笔记') + '（Markdown）', markdown)

    def refresh_list(self):
        self.items.blockSignals(True)
        self.items.clear()
        for note_id, title, plain in self.store.list():
            item = QListWidgetItem(title.strip() or '未命名笔记')
            item.setData(Qt.ItemDataRole.UserRole, note_id)
            item.setData(Qt.ItemDataRole.UserRole + 1, title + '\n' + plain)
            item.setToolTip(plain[:160] or '空白笔记')
            self.items.addItem(item)
            if note_id == self.current_id:
                self.items.setCurrentItem(item)
        self.items.blockSignals(False)
        self.filter_notes()

    def filter_notes(self):
        query = self.search.text().strip().casefold()
        self.items.blockSignals(True)
        for index in range(self.items.count()):
            item = self.items.item(index)
            text = item.data(Qt.ItemDataRole.UserRole + 1)
            item.setHidden(query not in text.casefold())
        self.items.blockSignals(False)

    def load(self, note_id):
        title, html = self.store.get(note_id)
        self.markdown = self.store.get_markdown(note_id)
        if self.markdown is None and not html and self.scripta is not None and self.scripta.prepared:
            self.markdown = ''
        self.loading = True
        self.current_id = note_id
        self.title.setText(title)
        self.editor.setHtml(html)
        self.show_editor()
        self.editor.document().setModified(False)
        self.loading = False
        self.dirty = False
        self.status.setText('已保存到本地')
        self.sync_format(self.editor.currentCharFormat())

    def select_note(self, item, previous=None):
        if item is None or item.data(Qt.ItemDataRole.UserRole) == self.current_id:
            return
        if not self.save(report=True):
            self.items.blockSignals(True)
            self.items.setCurrentItem(previous)
            self.items.blockSignals(False)
            return
        self.load(item.data(Qt.ItemDataRole.UserRole))

    def edit_selected_note(self):
        item = self.items.currentItem()
        if item is None or item.isHidden():
            item = next((self.items.item(row) for row in range(self.items.count())
                         if not self.items.item(row).isHidden()), None)
        if item is not None:
            self.items.setCurrentItem(item)
            if item.data(Qt.ItemDataRole.UserRole) == self.current_id:
                self.focus_editor()

    def delete_selected_note(self):
        item = self.items.currentItem()
        if item is not None and not item.isHidden() and item.data(Qt.ItemDataRole.UserRole) == self.current_id:
            self.delete_note()

    def mark_dirty(self):
        if self.loading:
            return
        self.dirty = True
        self.status.setText('正在编辑…')
        self.autosave.start()
        if self.markdown is not None and not self.editor_token:
            self.markdown = self.editor.toPlainText()
        for index in range(self.items.count()):
            item = self.items.item(index)
            if item.data(Qt.ItemDataRole.UserRole) == self.current_id:
                item.setText(self.title.text().strip() or '未命名笔记')
                body = self.editor.toPlainText() if self.markdown is None else self.markdown
                item.setData(Qt.ItemDataRole.UserRole + 1, self.title.text() + '\n' + body)

    def save(self, report=False, flush=True):
        if self.saving:
            return False
        self.saving = True
        try:
            return self.save_current(report, flush)
        finally:
            self.saving = False

    def save_current(self, report, flush):
        if flush and self.editor_token and self.scripta.loaded:
            token = self.editor_token
            snapshot = self.scripta.snapshot()
            if snapshot is None or snapshot[0] != token:
                self.status.setText('无法读取思刻中的正文，请重试保存。')
                return False
            self.scripta_changed(*snapshot)
        self.autosave.stop()
        if not self.dirty:
            return True
        try:
            html, plain = self.render_body()
            self.store.save(self.current_id, self.title.text(), html, plain, self.markdown)
        except Exception as error:
            logging.exception('Note save failed')
            self.status.setText('保存失败，内容仍在窗口中；请按 Ctrl+S 重试。')
            if report:
                QMessageBox.warning(self, '笔记未保存', f'保存失败：{error}\n请保持窗口打开，重试保存或复制内容。')
            return False
        self.dirty = False
        self.status.setText('已保存到本地 · ' + str(len(plain)) + ' 字符')
        return True

    def render_body(self):
        if self.markdown is None:
            return self.editor.toHtml(), self.editor.toPlainText()
        return self.render_markdown(self.markdown)

    @staticmethod
    def render_markdown(markdown):
        document = QTextDocument()
        document.setMarkdown(markdown)
        return document.toHtml(), document.toPlainText()

    def new_note(self, title='', markdown=None):
        if not self.save(report=True):
            return
        try:
            if markdown is None and self.scripta is not None and self.scripta.prepared:
                markdown = ''
            html, plain = self.render_markdown(markdown) if markdown else ('', '')
            note_id = self.store.create(title, html, plain, markdown)
        except Exception as error:
            QMessageBox.warning(self, '创建失败', str(error))
            return
        self.search.clear()
        self.load(note_id)
        self.refresh_list()
        self.focus_editor()

    def delete_note(self):
        if QMessageBox.question(self, '删除笔记', '确定删除当前笔记？此操作无法撤销。',
                                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        self.autosave.stop()
        try:
            next_id = self.store.delete(self.current_id)
        except Exception as error:
            QMessageBox.warning(self, '删除失败', str(error))
            return
        self.dirty = False
        self.load(next_id)
        self.refresh_list()

    def format_text(self, kind, checked):
        fmt = QTextCharFormat()
        if kind == 'bold':
            fmt.setFontWeight(QFont.Weight.Bold if checked else QFont.Weight.Normal)
        elif kind == 'italic':
            fmt.setFontItalic(checked)
        else:
            fmt.setFontUnderline(checked)
        self.editor.mergeCurrentCharFormat(fmt)
        self.editor.setFocus()

    def change_size(self, index):
        fmt = QTextCharFormat()
        fmt.setFontPointSize([11, 16, 22][index])
        self.editor.mergeCurrentCharFormat(fmt)
        self.editor.setFocus()

    def sync_format(self, fmt):
        for key, checked in [('bold', fmt.fontWeight() >= QFont.Weight.Bold),
                             ('italic', fmt.fontItalic()), ('underline', fmt.fontUnderline())]:
            self.formats[key].setChecked(checked)
        size = fmt.fontPointSize()
        self.size.setCurrentIndex(2 if size >= 22 else 1 if size >= 16 else 0)

    def choose_color(self):
        color = QColorDialog.getColor(self.editor.textColor(), self, '文字颜色')
        if color.isValid():
            self.editor.setTextColor(color)
            self.editor.setFocus()

    def toggle_list(self, style):
        cursor = self.editor.textCursor()
        cursor.beginEditBlock()
        current = cursor.currentList()
        if current and current.format().style() == style:
            # Apply to all selected paragraphs, not just the cursor's last block.
            start, end = cursor.selectionStart(), cursor.selectionEnd()
            block = self.editor.document().findBlock(start)
            while block.isValid() and block.position() <= end:
                if block.textList():
                    block.textList().remove(block)
                block = block.next()
        else:
            fmt = QTextListFormat()
            fmt.setStyle(style)
            fmt.setIndent(1)
            cursor.createList(fmt)
        cursor.endEditBlock()
        self.editor.setFocus()

    def export_note(self):
        if not self.save(report=True):
            return
        path, _ = QFileDialog.getSaveFileName(self, '导出当前笔记', 'idea.html', 'HTML 文档 (*.html)')
        if path:
            try:
                if not path.lower().endswith(('.html', '.htm')):
                    path += '.html'
                Path(path).write_text(self.render_body()[0], encoding='utf-8')
                self.status.setText('已导出 HTML')
            except OSError as error:
                QMessageBox.warning(self, '导出失败', str(error))

    def activate(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()
        self.focus_editor()

    def closeEvent(self, event):
        event.ignore()
        if self.save(report=True):
            self.hide()

    def can_exit(self):
        return self.save(report=True)

    def shutdown(self):
        if self.closed_store:
            return
        if self.save():
            self.store.close()
            self.closed_store = True
            self.hide()


def create_tool(context):
    return NotesTool(context, enable_scripta=True)
