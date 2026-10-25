import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from screenshot import Canvas, Editor, Selector


class ScreenshotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def image(self):
        image = QImage(200, 160, QImage.Format.Format_RGB32)
        image.fill(QColor('white'))
        return image

    def test_draw_undo_redo_and_branch(self):
        canvas = Canvas(self.image())
        canvas.show()
        QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=QPoint(20, 20))
        QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=QPoint(100, 80))
        rendered = canvas.render_image()
        self.assertNotEqual(rendered.pixelColor(20, 40), QColor('white'))
        canvas.undo()
        self.assertEqual(canvas.render_image(), canvas.base)
        canvas.redo()
        self.assertEqual(canvas.render_image(), rendered)
        canvas.undo()
        QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=QPoint(30, 30))
        QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=QPoint(70, 70))
        self.assertEqual(len(canvas.redo_operations), 0)
        canvas.close()

    def test_reverse_selection_crop_and_cancel(self):
        selected = []
        selector = Selector(self.image(), QRect(0, 0, 200, 160))
        selector.selected.connect(selected.append)
        selector.show()
        QTest.mousePress(selector, Qt.MouseButton.LeftButton, pos=QPoint(100, 80))
        QTest.mouseRelease(selector, Qt.MouseButton.LeftButton, pos=QPoint(20, 20))
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0].size(), QRect(QPoint(20, 20), QPoint(100, 80)).size())
        selector = Selector(self.image(), QRect(0, 0, 200, 160))
        selector.selected.connect(selected.append)
        selector.show()
        QTest.keyClick(selector, Qt.Key.Key_Escape)
        self.assertEqual(len(selected), 1)

    def test_all_tools_and_png_roundtrip(self):
        for tool in ['矩形', '圆形', '箭头', '画笔', '文字']:
            with self.subTest(tool=tool):
                canvas = Canvas(self.image())
                canvas.operations.append((tool, [QPoint(20, 20), QPoint(100, 80)], QColor('red'), 3, 'Hello'))
                rendered = canvas.render_image()
                self.assertNotEqual(rendered, canvas.base)
                with tempfile.TemporaryDirectory() as directory:
                    path = os.path.join(directory, 'capture.png')
                    self.assertTrue(rendered.save(path, 'PNG'))
                    self.assertEqual(QImage(path), rendered)

    def test_mosaic_covers_previous_annotation_and_undo(self):
        canvas = Canvas(self.image())
        canvas.operations.append(('画笔', [QPoint(21, 20), QPoint(21, 120)], QColor('red'), 2, ''))
        before = canvas.render_image()
        canvas.operations.append(('马赛克', [QPoint(10, 10), QPoint(130, 130)], QColor('red'), 3, ''))
        after = canvas.render_image()
        self.assertNotEqual(before, after)
        self.assertEqual(after.pixelColor(0, 0), before.pixelColor(0, 0))
        canvas.undo()
        self.assertEqual(canvas.render_image(), before)

    def test_copy_and_save(self):
        editor = Editor(self.image())
        editor.copy()
        self.assertEqual(self.app.clipboard().image(), editor.canvas.render_image())
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, 'export.png')
            with patch('screenshot.QFileDialog.getSaveFileName', return_value=(path, 'PNG')):
                editor.save()
            self.assertEqual(QImage(path), editor.canvas.render_image())
        editor.close()


if __name__ == '__main__':
    unittest.main()
