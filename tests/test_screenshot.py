import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, Qt
from PySide6.QtGui import QColor, QImage, QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton, QWidget
from screenshot import Canvas, DesktopCapture, Editor, Selector


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

    def test_editor_browses_queue_and_keeps_separate_annotations(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = tuple(os.path.join(directory, f'{index}.png') for index in range(3))
            images = [self.image() for _ in paths]
            images[1].fill(QColor('blue'))
            images[2].fill(QColor('green'))
            for image, path in zip(images, paths):
                self.assertTrue(image.save(path))

            editor = Editor(images[1], confirm_close=False, queue_paths=paths, queue_index=1)
            self.addCleanup(editor.close)
            editor.show()
            QTest.qWait(20)
            self.assertEqual(editor.queue_position.text(), '2 / 3')
            canvas = editor.canvas
            QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=QPoint(20, 20))
            QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=QPoint(100, 80))
            marked = canvas.render_image()
            self.assertNotEqual(marked, images[1])

            QTest.keyClick(editor, Qt.Key.Key_Right)
            self.assertEqual(editor.queue_position.text(), '3 / 3')
            self.assertFalse(editor.next_action.isEnabled())
            self.assertEqual(canvas.render_image(), images[2])
            editor.previous_action.trigger()
            self.assertEqual(canvas.render_image(), marked)
            QTest.keyClick(editor, Qt.Key.Key_Left)
            self.assertEqual(editor.queue_position.text(), '1 / 3')
            self.assertFalse(editor.previous_action.isEnabled())
            self.assertEqual(canvas.render_image(), images[0])

    def test_reverse_selection_crop_and_cancel(self):
        selected = []
        desktop = DesktopCapture([(QRect(0, 0, 200, 160), self.image())])
        selector = Selector(desktop)
        selector.selected.connect(selected.append)
        selector.show()
        QTest.mousePress(selector, Qt.MouseButton.LeftButton, pos=QPoint(100, 80))
        QTest.mouseRelease(selector, Qt.MouseButton.LeftButton, pos=QPoint(20, 20))
        self.assertEqual(selected, [])
        self.assertTrue(selector.isVisible())
        QTest.keyClick(selector, Qt.Key.Key_Return)
        self.assertEqual(len(selected), 1)
        self.assertFalse(selector.isVisible())
        self.assertEqual(selected[0].size(), QRect(QPoint(20, 20), QPoint(100, 80)).size())
        selector = Selector(desktop)
        selector.selected.connect(selected.append)
        selector.show()
        QTest.mousePress(selector, Qt.MouseButton.LeftButton, pos=QPoint(10, 10))
        QTest.mouseRelease(selector, Qt.MouseButton.LeftButton, pos=QPoint(100, 80))
        self.app.processEvents()
        QTest.keyClick(selector, Qt.Key.Key_Escape)
        self.assertEqual(len(selected), 1)
        self.assertFalse(selector.isVisible())

    def test_inline_toolbar_edits_original_pixels_and_stays_on_screen(self):
        image = QImage(1000, 640, QImage.Format.Format_RGB32)
        image.fill(QColor('white'))
        image.setDevicePixelRatio(2)
        selector = Selector(DesktopCapture([(QRect(0, 0, 500, 320), image)]))
        selected = []
        selector.selected.connect(selected.append)
        selector.show()
        QTest.mousePress(selector, Qt.MouseButton.LeftButton, pos=QPoint(100, 180))
        QTest.mouseRelease(selector, Qt.MouseButton.LeftButton, pos=QPoint(430, 315))
        toolbar = selector.findChild(QWidget, 'captureToolbar')
        self.assertTrue(selector.rect().contains(toolbar.geometry()))
        self.assertLess(toolbar.geometry().bottom(), selector.selection.top())
        canvas = selector.canvas
        self.assertEqual(canvas.geometry(), selector.selection)
        QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=QPoint(10, 10))
        QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=QPoint(50, 50))
        QTest.mouseClick(toolbar.findChild(QPushButton, 'captureFinish'), Qt.MouseButton.LeftButton)
        self.assertEqual(len(selected), 1)
        self.assertEqual((selected[0].width(), selected[0].height()), (662, 272))
        self.assertEqual(selected[0].pixelColor(20, 50), QColor('#ff453a'))

    def test_window_snap_prefers_front_dialog_and_allows_drag(self):
        image = QImage(750, 480, QImage.Format.Format_RGB32)
        image.fill(QColor('white'))
        image.setDevicePixelRatio(1.5)
        desktop = DesktopCapture([(QRect(-500, 0, 500, 320), image)],
                                 [QRect(-350, 60, 300, 210), QRect(-500, 0, 600, 420)])
        selector = Selector(desktop)
        self.addCleanup(selector.close)
        selector.show()
        point = QPoint(150, 80)
        move = QMouseEvent(QEvent.Type.MouseMove, QPointF(point), QPointF(selector.mapToGlobal(point)),
                           Qt.MouseButton.NoButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)
        QApplication.sendEvent(selector, move)
        self.assertEqual(selector.selection, QRect(100, 40, 200, 140))
        QTest.mouseClick(selector, Qt.MouseButton.LeftButton, pos=point)
        self.assertEqual(selector.canvas.base.size(), image.copy(150, 60, 300, 210).size())
        selector.close()

        drag = Selector(desktop)
        self.addCleanup(drag.close)
        drag.show()
        QTest.mousePress(drag, Qt.MouseButton.LeftButton, pos=point)
        QTest.mouseRelease(drag, Qt.MouseButton.LeftButton, pos=QPoint(190, 120))
        self.assertEqual(drag.selection, QRect(150, 80, 41, 41))

    def test_high_dpi_crop_preserves_single_pixel_details(self):
        image = QImage(250, 200, QImage.Format.Format_RGB32)
        image.fill(QColor('white'))
        image.setPixelColor(26, 25, QColor('black'))
        image.setDevicePixelRatio(1.25)
        desktop = DesktopCapture([(QRect(-200, 0, 200, 160), image)])
        crop = desktop.crop(QRect(20, 20, 80, 60))
        self.assertEqual(crop.size(), image.copy(25, 25, 100, 75).size())
        self.assertEqual(crop.devicePixelRatio(), 1)
        self.assertEqual(crop.pixelColor(1, 0), QColor('black'))
        self.assertEqual(crop.pixelColor(2, 0), QColor('white'))

    def test_mixed_dpi_crop_keeps_high_dpi_pixels(self):
        left = QImage(20, 20, QImage.Format.Format_RGB32)
        left.fill(QColor('red'))
        right = QImage(40, 40, QImage.Format.Format_RGB32)
        right.fill(QColor('white'))
        right.setPixelColor(1, 0, QColor('black'))
        right.setDevicePixelRatio(2)
        desktop = DesktopCapture([(QRect(-20, 0, 20, 20), left), (QRect(0, 0, 20, 20), right)])
        crop = desktop.crop(QRect(16, 0, 8, 4))
        self.assertEqual((crop.width(), crop.height()), (16, 8))
        self.assertEqual(crop.pixelColor(7, 0), QColor('red'))
        self.assertEqual(crop.pixelColor(8, 0), QColor('white'))
        self.assertEqual(crop.pixelColor(9, 0), QColor('black'))
        self.assertEqual(crop.pixelColor(10, 0), QColor('white'))

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

    def test_annotation_keyboard_controls(self):
        editor = Editor(self.image())
        editor.show()
        editor.activateWindow()
        self.app.processEvents()
        QTest.mousePress(editor.canvas, Qt.MouseButton.LeftButton, pos=QPoint(5, 5))
        QTest.mouseRelease(editor.canvas, Qt.MouseButton.LeftButton, pos=QPoint(25, 25))
        with patch('screenshot.QMessageBox.question', return_value=QMessageBox.StandardButton.Cancel) as confirm:
            QTest.keyClick(editor, Qt.Key.Key_Escape)
        confirm.assert_called_once()
        self.assertTrue(editor.isVisible())
        editor.centralWidget().setFocus()
        QTest.keyClick(editor.centralWidget(), Qt.Key.Key_Delete)
        self.assertFalse(editor.canvas.operations)
        self.assertEqual(len(editor.canvas.redo_operations), 1)
        QTest.keyClick(editor, Qt.Key.Key_Enter, Qt.KeyboardModifier.KeypadModifier)
        self.assertFalse(editor.isVisible())
        self.assertEqual(self.app.clipboard().image(), self.image())


if __name__ == '__main__':
    unittest.main()
