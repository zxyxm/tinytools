import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QTextCursor, QFont, QTextListFormat
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox
from tinytools.core import ToolContext
from tinytools.notes import NoteStore
from tinytools.plugins.notes import NotesTool


class NotesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / 'notes.sqlite3'
        settings = QSettings(str(Path(self.directory.name) / 'settings.ini'), QSettings.Format.IniFormat)
        self.context = ToolContext(self.app, settings, Mock(), Mock())
        self.window = NotesTool(self.context, NoteStore(self.path))

    def tearDown(self):
        self.window.shutdown()
        self.directory.cleanup()

    def test_keyboard_edits_text_and_deletes_only_from_the_list(self):
        window = self.window
        window.activate()
        self.app.processEvents()
        window.editor.setPlainText('abc')
        window.editor.moveCursor(QTextCursor.MoveOperation.Start)
        QTest.keyClick(window.editor, Qt.Key.Key_Delete)
        QTest.keyClick(window.editor, Qt.Key.Key_Return)
        self.assertEqual(window.editor.toPlainText(), '\nbc')
        note_id = window.current_id
        window.items.setFocus()
        QTest.keyClick(window.items, Qt.Key.Key_Return)
        self.assertTrue(window.editor.hasFocus())
        window.items.setFocus()
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.No) as confirm:
            QTest.keyClick(window.items, Qt.Key.Key_Delete)
        confirm.assert_called_once()
        self.assertEqual(window.current_id, note_id)
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Yes):
            QTest.keyClick(window.items, Qt.Key.Key_Delete)
        self.assertNotEqual(window.current_id, note_id)
        window.editor.setFocus()
        window.editor.setPlainText('save on close')
        QTest.keyClick(window.editor, Qt.Key.Key_Escape)
        self.assertFalse(window.isVisible())
        self.assertFalse(window.dirty)
        self.assertIn('save on close', window.store.get(window.current_id)[1])

    def test_autosave_and_rich_text_survive_restart(self):
        self.window.title.setText('一个新 idea')
        self.window.editor.setPlainText('需要保留的想法')
        self.window.editor.selectAll()
        self.window.format_text('bold', True)
        self.window.toggle_list(QTextListFormat.Style.ListDisc)
        QTest.qWait(800)
        self.assertFalse(self.window.dirty)
        self.window.shutdown()
        self.window = NotesTool(self.context, NoteStore(self.path))
        self.assertEqual(self.window.title.text(), '一个新 idea')
        self.assertEqual(self.window.editor.toPlainText(), '需要保留的想法')
        cursor = self.window.editor.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.Start)
        cursor.movePosition(QTextCursor.MoveOperation.NextCharacter, QTextCursor.MoveMode.KeepAnchor)
        self.assertGreaterEqual(cursor.charFormat().fontWeight(), QFont.Weight.Bold)
        self.assertIsNotNone(cursor.currentList())

    def test_new_switch_close_and_search(self):
        first_id = self.window.current_id
        self.window.editor.setPlainText('隐藏在正文中的灵感')
        self.window.new_note()
        second_id = self.window.current_id
        self.assertNotEqual(first_id, second_id)
        self.window.title.setText('第二条')
        self.window.editor.setPlainText('another idea')
        for i in range(self.window.items.count()):
            item = self.window.items.item(i)
            if item.data(256) == first_id:
                self.window.items.setCurrentItem(item)
                break
        self.assertEqual(self.window.editor.toPlainText(), '隐藏在正文中的灵感')
        self.assertIn('another idea', self.window.store.get(second_id)[1])
        self.window.search.setText('灵感')
        visible = [self.window.items.item(i) for i in range(self.window.items.count()) if not self.window.items.item(i).isHidden()]
        self.assertEqual(len(visible), 1)
        self.window.editor.insertPlainText('追加')
        self.window.close()
        self.assertFalse(self.window.dirty)
        self.assertIn('追加', self.window.store.get(first_id)[1])

    def test_failed_write_keeps_unsaved_text_and_blocks_exit(self):
        self.window.editor.setPlainText('不能丢失')
        with patch.object(self.window.store, 'save', side_effect=OSError('disk full')), \
                patch.object(QMessageBox, 'warning'), self.assertLogs(level='ERROR'):
            self.assertFalse(self.window.can_exit())
        self.assertTrue(self.window.dirty)
        self.assertEqual(self.window.editor.toPlainText(), '不能丢失')
        self.assertTrue(self.window.save())

    def test_delete_confirmation_and_last_note(self):
        note_id = self.window.current_id
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.No):
            self.window.delete_note()
        self.assertEqual(self.window.current_id, note_id)
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Yes):
            self.window.delete_note()
        self.assertNotEqual(self.window.current_id, note_id)
        self.assertEqual(len(self.window.store.list()), 1)
        self.assertEqual(self.window.editor.toPlainText(), '')

    def test_export(self):
        path = str(Path(self.directory.name) / 'idea.html')
        self.window.editor.setHtml('<p><b>灵感</b> &amp; idea</p>')
        with patch('tinytools.plugins.notes.QFileDialog.getSaveFileName', return_value=(path, 'HTML')):
            self.window.export_note()
        html = Path(path).read_text(encoding='utf-8')
        self.assertIn('灵感', html)
        self.assertIn('font-weight', html)


if __name__ == '__main__':
    unittest.main()
