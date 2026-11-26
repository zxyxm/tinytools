import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from PySide6.QtCore import QEvent, QMimeData, QPoint, QPointF, QRect, QSettings, Qt, QUrl
from PySide6.QtGui import (QColor, QDragEnterEvent, QDragMoveEvent, QDropEvent, QEnterEvent, QImage,
                           QKeySequence, QMouseEvent)
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMenu
from screenshot import DesktopCapture
from tinytools.core import Registry, ToolSpec, ToolContext
from tinytools.timer import Countdown
from tinytools.plugins.countdown import CountdownTool
from tinytools.plugins.capture import CaptureTool
from tinytools.app import CaptureVisibilitySwitch, Launcher, Toolbox
from tinytools.preferences import HIDE_LAUNCHER_DURING_CAPTURE, SHOW_TRAY_ICON, shortcut_binding


class TimerTests(unittest.TestCase):
    def setUp(self):
        self.now = 100.0
        self.timer = Countdown(lambda: self.now)

    def test_pause_resume_and_delayed_tick(self):
        self.timer.configure(60)
        self.timer.start()
        self.now += 20.25
        self.assertEqual(self.timer.display, '00:00:40')
        self.timer.pause()
        self.now += 300
        self.assertEqual(self.timer.remaining, 39.75)
        self.timer.start()
        self.now += 50
        self.assertTrue(self.timer.tick())
        self.assertFalse(self.timer.tick())
        self.assertEqual(self.timer.display, '00:00:00')
        self.timer.start()
        self.assertEqual(self.timer.remaining, 60)

    def test_reset_and_invalid_duration(self):
        with self.assertRaises(ValueError):
            self.timer.configure(0)
        self.timer.configure(3661)
        self.assertEqual(self.timer.display, '01:01:01')
        self.timer.start()
        with self.assertRaises(ValueError):
            self.timer.configure(30)
        self.now += 20
        self.timer.reset()
        self.assertEqual(self.timer.remaining, 3661)
        self.assertEqual(self.timer.state, 'idle')


class RegistryTests(unittest.TestCase):
    def test_discovery_search_and_reuse(self):
        registry = Registry()
        registry.discover()
        self.assertFalse(registry.errors)
        self.assertEqual({spec.id for spec in registry.search('')}, {'countdown', 'capture', 'notes'})
        self.assertEqual(registry.search('timer')[0].id, 'countdown')
        self.assertEqual(registry.search('JT')[0].id, 'capture')
        self.assertEqual(registry.search('does-not-exist'), [])
        tool = Mock()
        factory = Mock(return_value=tool)
        registry.register(ToolSpec('test', 'test', 'description'), factory)
        registry.activate('test', None)
        registry.activate('test', None)
        factory.assert_called_once()
        self.assertEqual(tool.activate.call_count, 2)
        with self.assertRaises(ValueError):
            registry.register(ToolSpec('test', 'duplicate', ''), factory)

    def test_bad_module_does_not_disable_other_tools(self):
        registry = Registry()
        import tinytools.core as core
        original = core.import_module
        def broken(name):
            if name.endswith('.capture'):
                raise RuntimeError('test load failure')
            return original(name)
        with patch.object(core, 'import_module', side_effect=broken), self.assertLogs(level='ERROR'):
            registry.discover()
        self.assertIn('countdown', registry.specs)
        self.assertEqual(len(registry.errors), 1)


class WindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_countdown_hidden_completion_and_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = QSettings(directory + '/settings.ini', QSettings.Format.IniFormat)
            notify = Mock()
            context = ToolContext(self.app, settings, notify, Mock())
            window = CountdownTool(context)
            now = [0.0]
            window.model.clock = lambda: now[0]
            window.set_duration(2)
            window.activate()
            window.toggle()
            window.close()
            self.assertFalse(window.isVisible())
            self.assertEqual(window.model.state, 'running')
            now[0] = 3
            window.refresh()
            window.refresh()
            notify.assert_called_once()
            self.assertTrue(window.isVisible())
            self.assertEqual(window.display.text(), '00:00:00')
            self.assertEqual(settings.value('countdown/seconds', type=int), 2)
            window.reset()
            window.set_duration(0)
            self.assertFalse(window.start_button.isEnabled())
            window.shutdown()

    def test_countdown_appearance_restores_without_interrupting_timer(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = QSettings(str(Path(directory) / 'settings.ini'), QSettings.Format.IniFormat)
            context = ToolContext(self.app, settings, Mock(), Mock())
            window = CountdownTool(context)
            self.addCleanup(window.shutdown)
            window.activate()
            window.resize(540, 460)
            full_size = window.size()
            window.opacity_slider.setValue(70)
            window.start_button.click()
            deadline = window.model.deadline

            window.mode_button.click()
            self.assertLess(window.width(), full_size.width())
            self.assertLess(window.height(), full_size.height())
            self.assertFalse(window.fields[0].isVisible())
            self.assertFalse(window.opacity_slider.isVisible())
            self.assertTrue(window.start_button.isVisible())
            self.assertTrue(window.mode_button.isVisible())
            self.assertEqual(window.model.state, 'running')
            self.assertEqual(window.model.deadline, deadline)
            self.assertAlmostEqual(window.windowOpacity(), 0.70, delta=0.01)

            reopened = CountdownTool(context)
            self.addCleanup(reopened.shutdown)
            reopened.activate()
            self.assertTrue(reopened.mode_button.isChecked())
            self.assertFalse(reopened.fields[0].isVisible())
            self.assertAlmostEqual(reopened.windowOpacity(), 0.70, delta=0.01)

            window.mode_button.click()
            self.assertEqual(window.size(), full_size)
            self.assertTrue(window.opacity_slider.isVisible())
            self.assertEqual(window.model.deadline, deadline)
            self.assertFalse(settings.value('countdown/compact', type=bool))

    def test_countdown_keyboard_controls(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = QSettings(str(Path(directory) / 'settings.ini'), QSettings.Format.IniFormat)
            window = CountdownTool(ToolContext(self.app, settings, Mock(), Mock()))
            self.addCleanup(window.shutdown)
            window.activate()
            self.app.processEvents()
            window.fields[1].setFocus()
            QTest.keyClick(window.fields[1], Qt.Key.Key_Return)
            self.assertEqual(window.model.state, 'running')
            QTest.keyClick(window.start_button, Qt.Key.Key_Enter, Qt.KeyboardModifier.KeypadModifier)
            self.assertEqual(window.model.state, 'paused')
            QTest.keyClick(window.start_button, Qt.Key.Key_Return)
            self.assertEqual(window.model.state, 'running')
            QTest.keyClick(window.start_button, Qt.Key.Key_Escape)
            self.assertFalse(window.isVisible())
            self.assertEqual(window.model.state, 'running')
            window.activate()
            QTest.keyClick(window.start_button, Qt.Key.Key_Delete)
            self.assertEqual(window.model.state, 'idle')

    def test_launcher_search_and_activation(self):
        registry = Registry()
        registry.discover()
        launch = Mock()
        window = Launcher(registry, launch)
        self.addCleanup(window.suspend)
        window.reveal()
        window.search.setText('timer')
        self.assertEqual(window.results.count(), 2)
        self.assertEqual(window.results.currentRow(), 1)
        QTest.keyClick(window.search, Qt.Key.Key_Return)
        launch.assert_called_once_with('countdown')
        window.search.setText('no-matching-tool')
        window.open_selected()
        launch.assert_called_once()
        self.assertFalse(window.open_button.isEnabled())
        window.close()

    def test_favorite_from_search_survives_reopen_and_does_not_pin_window(self):
        registry = Registry()
        registry.discover()
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / 'settings.ini')
            settings = QSettings(path, QSettings.Format.IniFormat)
            window = Launcher(registry, Mock(), settings)
            self.addCleanup(window.suspend)
            window.reveal()
            window.search.setText('bj')
            self.app.processEvents()
            rect = window.results.visualItemRect(window.results.currentItem())
            window.show_tool_menu(rect.center())
            menu = window.findChild(QMenu, 'toolMenu')
            self.assertEqual(menu.actions()[0].text(), '收藏')
            QTest.mouseClick(menu, Qt.MouseButton.LeftButton, pos=menu.actionGeometry(menu.actions()[0]).center())
            self.assertEqual(window.search.text(), 'bj')
            self.assertEqual(window.favorites, ['notes'])
            self.assertFalse(window.pin.isChecked())
            window.suspend()
            settings.sync()

            reopened = Launcher(registry, Mock(), QSettings(path, QSettings.Format.IniFormat))
            self.addCleanup(reopened.suspend)
            self.assertEqual(reopened.results.item(0).text(), '收藏')
            self.assertEqual(reopened.results.currentItem().data(Qt.ItemDataRole.UserRole), 'notes')
            reopened.move_selection(1)
            self.assertEqual(reopened.results.currentItem().data(Qt.ItemDataRole.UserRole), 'capture')
            reopened.move_selection(-1)
            self.assertEqual(reopened.results.currentItem().data(Qt.ItemDataRole.UserRole), 'notes')
            reopened.toggle_favorite('notes')
            self.assertEqual(reopened.results.item(0).text(), '全部工具')
            self.assertEqual(settings.value('launcher/favorites', type=list), [])

    def test_shortcut_settings_save_and_reject_conflicts(self):
        self.assertEqual(shortcut_binding(QKeySequence('Ctrl+Alt+F11')), (3, 0x7A))
        with tempfile.TemporaryDirectory() as directory:
            settings = QSettings(str(Path(directory) / 'settings.ini'), QSettings.Format.IniFormat)
            with patch('tinytools.app.Hotkey') as hotkey_class:
                def create_hotkey(callback, hotkey_id, modifiers=1, key=0x20):
                    return SimpleNamespace(modifiers=modifiers, key=key,
                                           close=Mock(), register=Mock(return_value=True))

                hotkey_class.side_effect = create_hotkey
                with patch.object(self.app, 'installNativeEventFilter'), \
                        patch.object(self.app, 'removeNativeEventFilter'):
                    toolbox = Toolbox(self.app, settings)
                    try:
                        self.assertFalse(toolbox.window.isVisible())
                        self.assertTrue(toolbox.window.edge.isVisible())
                        self.assertEqual(toolbox.window.tool_shortcuts['capture'], 'Alt+A')
                        self.assertEqual(toolbox.hotkeys['capture'].key, ord('A'))
                        toolbox.hotkeys['capture'].register.return_value = False
                        with patch('tinytools.app.sys.platform', 'win32'):
                            toolbox.register_hotkeys()
                        self.assertEqual(toolbox.window.tool_shortcuts['capture'], 'Ctrl+Alt+Z')
                        self.assertIn('备用截图', toolbox.window.status.text())
                        self.assertFalse(settings.contains('launcher/hotkeys/capture'))
                        toolbox.window.settings_requested.emit()
                        dialog = toolbox.settings_dialog
                        dialog.fields['launcher'].setKeySequence(QKeySequence('Alt+A'))
                        dialog.save_button.click()
                        self.assertIn('同一个', dialog.status.text())
                        self.assertFalse(settings.contains('launcher/hotkeys/launcher'))
                        dialog.fields['launcher'].setKeySequence(QKeySequence('Ctrl+Alt+F11'))
                        dialog.fields['capture'].setKeySequence(QKeySequence('Ctrl+Alt+F10'))
                        toolbox.hotkeys['capture'].register.return_value = False
                        with patch('tinytools.app.sys.platform', 'win32'):
                            dialog.save_button.click()
                        self.assertIn('截图', dialog.status.text())
                        self.assertEqual(toolbox.hotkeys['launcher'].key, 0x20)
                        self.assertFalse(settings.contains('launcher/hotkeys/launcher'))

                        toolbox.hotkeys['capture'].register.return_value = True
                        dialog.save_button.click()
                        self.assertIsNone(toolbox.settings_dialog)
                        self.assertEqual(settings.value('launcher/hotkeys/launcher'), 'Ctrl+Alt+F11')
                        self.assertEqual(toolbox.window.tool_shortcuts['capture'], 'Ctrl+Alt+F10')
                        self.assertIn('Ctrl+Alt+F11', toolbox.open_action.text())
                        self.assertIn('Ctrl+Alt+F10', toolbox.tool_actions['capture'].text())

                        toolbox.show_settings()
                        dialog = toolbox.settings_dialog
                        dialog.reset()
                        self.assertEqual(dialog.fields['launcher'].keySequence(), QKeySequence('Alt+Space'))
                        dialog.reject()
                        self.assertEqual(settings.value('launcher/hotkeys/launcher'), 'Ctrl+Alt+F11')
                    finally:
                        self.app.aboutToQuit.disconnect(toolbox.cleanup)
                        toolbox.cleanup()

    def test_exit_button_and_optional_tray_icon(self):
        with (tempfile.TemporaryDirectory() as directory,
              patch.object(Toolbox, 'register_hotkeys'), patch.object(self.app, 'quit') as quit_app):
            settings = QSettings(str(Path(directory) / 'settings.ini'), QSettings.Format.IniFormat)
            toolbox = Toolbox(self.app, settings)
            try:
                self.assertFalse(toolbox.tray.isVisible())
                self.assertEqual(toolbox.window.quit_button.text(), '彻底退出')
                toolbox.show_settings()
                toolbox.settings_dialog.tray_option.setChecked(True)
                toolbox.settings_dialog.reject()
                self.assertFalse(toolbox.tray.isVisible())

                toolbox.show_settings()
                toolbox.settings_dialog.tray_option.setChecked(True)
                toolbox.settings_dialog.save_button.click()
                self.assertTrue(toolbox.tray.isVisible())
                self.assertTrue(settings.value(SHOW_TRAY_ICON, type=bool))

                with patch.object(toolbox.registry, 'can_exit', side_effect=[False, True]):
                    toolbox.window.quit_button.click()
                    quit_app.assert_not_called()
                    toolbox.window.quit_button.click()
                    quit_app.assert_called_once()
            finally:
                self.app.aboutToQuit.disconnect(toolbox.cleanup)
                toolbox.cleanup()

    def test_launcher_edge_hover_and_pin(self):
        window = Launcher(Registry(), Mock())
        self.addCleanup(window.suspend)
        area = QApplication.primaryScreen().availableGeometry()
        window.collapse()
        self.assertFalse(window.isVisible())
        self.assertTrue(window.edge.isVisible())
        self.assertEqual(window.edge.geometry().right(), area.right())
        self.assertEqual(window.edge.geometry().center().y(), area.center().y())

        edge_enter = QEnterEvent(window.edge.rect().center(), window.edge.rect().center(),
                                 window.edge.geometry().center())
        QApplication.sendEvent(window.edge, edge_enter)
        self.assertTrue(window.isVisible())
        self.assertFalse(window.edge.isVisible())
        self.assertEqual(window.geometry().right(), area.right())
        self.assertEqual(window.geometry().top(), area.top())
        self.assertEqual(window.geometry().bottom(), area.bottom())

        with patch('tinytools.app.QCursor') as cursor:
            cursor.pos.return_value = QPoint(area.left() - 1, area.top())
            QApplication.sendEvent(window, QEvent(QEvent.Type.Leave))
            self.assertTrue(window.retract_timer.isActive())
            window.pin.click()
            QApplication.sendEvent(window, QEvent(QEvent.Type.Leave))
            self.assertFalse(window.retract_timer.isActive())
            self.assertTrue(window.isVisible())
            window.pin.click()
            QTest.qWait(400)
            self.assertFalse(window.isVisible())
            self.assertTrue(window.edge.isVisible())

    def test_dragging_launcher_left_edge_keeps_dock_and_saves_width(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / 'settings.ini')
            settings = QSettings(path, QSettings.Format.IniFormat)
            window = Launcher(Registry(), Mock(), settings)
            self.addCleanup(window.suspend)
            window.reveal()
            self.app.processEvents()
            area = QApplication.primaryScreen().availableGeometry()
            handle = window.resize_handle
            self.assertEqual(handle.height(), window.height())
            start = handle.mapToGlobal(handle.rect().center())
            left = Qt.MouseButton.LeftButton
            none = Qt.MouseButton.NoButton

            def mouse_event(kind, x, button, buttons):
                position = QPoint(x, start.y())
                event = QMouseEvent(kind, QPointF(handle.mapFromGlobal(position)), QPointF(position),
                                    button, buttons, Qt.KeyboardModifier.NoModifier)
                QApplication.sendEvent(handle, event)

            mouse_event(QEvent.Type.MouseButtonPress, start.x(), left, left)
            mouse_event(QEvent.Type.MouseMove, area.left() - 100, none, left)
            self.assertEqual(window.width(), area.width())
            self.assertEqual(window.geometry().right(), area.right())
            mouse_event(QEvent.Type.MouseMove, area.right() + 100, none, left)
            self.assertEqual(window.width(), window.minimumWidth())
            self.assertEqual(window.geometry().right(), area.right())
            with patch('tinytools.app.QCursor') as cursor:
                cursor.pos.return_value = QPoint(area.left() - 1, area.top())
                window.retract_if_outside()
                self.assertTrue(window.isVisible())

            target_width = (area.width() + window.minimumWidth()) // 2
            release_x = area.right() - target_width + 1 + handle.rect().center().x()
            mouse_event(QEvent.Type.MouseMove, release_x, none, left)
            self.assertEqual(window.width(), target_width)
            mouse_event(QEvent.Type.MouseButtonRelease, release_x, left, none)
            self.assertTrue(window.retract_timer.isActive())
            self.assertEqual(settings.value(Launcher.WIDTH_SETTING, type=int), window.width())
            settings.sync()
            reopened = Launcher(Registry(), Mock(), QSettings(path, QSettings.Format.IniFormat))
            self.addCleanup(reopened.suspend)
            self.assertEqual(reopened.width(), window.width())
            self.assertEqual(reopened.geometry().right(), area.right())

    def test_common_paths_drop_groups_rename_and_restore(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            ini = str(folder / 'settings.ini')
            document = folder / 'meeting notes.txt'
            document.touch()
            settings = QSettings(ini, QSettings.Format.IniFormat)
            settings.setValue('launcher/commonPaths', [str(folder)])
            window = Launcher(Registry(), Mock(), settings)
            self.addCleanup(window.suspend)
            paths = window.common_paths
            self.assertEqual(paths.items.item(0).text(), str(folder))
            mime = QMimeData()
            mime.setUrls([QUrl.fromLocalFile(p.as_posix()) for p in (document, folder, document)])
            args = (Qt.DropAction.MoveAction | Qt.DropAction.LinkAction, mime, Qt.MouseButton.LeftButton,
                    Qt.KeyboardModifier.NoModifier)
            window.collapse()
            self.app.sendEvent(window.edge, QDragEnterEvent(window.edge.rect().center(), *args))
            self.assertTrue(window.isVisible())
            self.app.processEvents()

            point = paths.tabs.mapTo(window, paths.tabs.tabRect(1).center())
            for event in (QDragEnterEvent(point, *args), QDragMoveEvent(point, *args), QDropEvent(QPointF(point), *args)):
                self.app.sendEvent(window.windowHandle(), event)
                self.assertTrue(event.isAccepted())
                self.assertEqual(event.dropAction(), Qt.DropAction.LinkAction)
            self.assertEqual(paths.tabs.currentIndex(), 1)
            self.assertEqual(paths.items.count(), 2)
            self.assertEqual(paths.items.item(0).text(), str(document))

            with patch('tinytools.common_paths.QInputDialog.getText', return_value=('项目资料', True)):
                paths.rename_group()
            paths.add_group()
            self.assertEqual(paths.tabs.currentIndex(), 2)
            self.assertEqual(paths.items.count(), 0)
            self.assertFalse(paths.open_group_button.isEnabled())
            settings.sync()
            reopened = Launcher(Registry(), Mock(), QSettings(ini, QSettings.Format.IniFormat))
            self.addCleanup(reopened.suspend)
            restored = reopened.common_paths
            self.assertEqual(restored.items.item(0).text(), str(folder))
            self.assertEqual(restored.tabs.tabText(1), '项目资料')
            self.assertEqual(restored.tabs.count(), 3)
            restored.tabs.setCurrentIndex(1)
            self.assertEqual(restored.items.count(), 2)
            self.assertEqual(restored.items.item(0).text(), str(document))

    def test_open_common_path_group_continues_after_missing_document(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            document = folder / 'existing.txt'
            document.touch()
            missing = folder / 'missing.txt'
            window = Launcher(Registry(), Mock())
            self.addCleanup(window.suspend)
            paths = window.common_paths
            paths.add_paths(0, [missing, document, folder])
            paths.add_paths(1, [folder])
            paths.tabs.setCurrentIndex(0)
            with (patch('tinytools.common_paths.QDesktopServices.openUrl', return_value=True) as open_url,
                  patch('tinytools.common_paths.QMessageBox.exec') as warning):
                paths.open_group_button.click()
            self.assertEqual([call.args[0].toLocalFile() for call in open_url.call_args_list],
                             [document.as_posix(), folder.as_posix()])
            warning.assert_called_once()

    def test_capture_temporarily_hides_panel_and_edge(self):
        window = Launcher(Registry(), Mock())
        self.addCleanup(window.suspend)
        settings = Mock()
        settings.value.return_value = True
        context = ToolContext(self.app, settings, Mock(), window.collapse,
                              suspend_launcher=window.suspend, resume_launcher=window.resume)
        tool = CaptureTool(context)
        self.addCleanup(tool.shutdown)
        window.reveal()
        window.pin.setChecked(True)
        tool.activate()
        self.assertFalse(window.isVisible())
        self.assertFalse(window.edge.isVisible())
        tool.pending.stop()

        image = QImage(200, 160, QImage.Format.Format_RGB32)
        image.fill(QColor('white'))
        desktop = DesktopCapture([(QRect(0, 0, 200, 160), image)])
        with patch('screenshot.desktop_image', return_value=desktop):
            tool.capture(context.resume_launcher)
        self.assertFalse(window.edge.isVisible())
        self.assertFalse(window.isVisible())
        tool.controller.selector.close()
        self.assertTrue(window.isVisible())
        self.assertTrue(window.pin.isChecked())

    def test_capture_card_switch_and_visible_panel(self):
        image = QImage(200, 160, QImage.Format.Format_RGB32)
        image.fill(QColor('white'))
        desktop = DesktopCapture([(QRect(0, 0, 200, 160), image)])
        with (tempfile.TemporaryDirectory() as directory,
              patch.object(Toolbox, 'register_hotkeys'),
              patch('screenshot.desktop_image', return_value=desktop)):
            settings = QSettings(str(Path(directory) / 'settings.ini'), QSettings.Format.IniFormat)
            toolbox = Toolbox(self.app, settings)
            try:
                window = toolbox.window
                window.reveal()
                window.search.setText('截图')
                card = window.results.itemWidget(window.results.currentItem())
                switch = card.findChild(CaptureVisibilitySwitch)
                self.assertFalse(switch.isChecked())

                # Clicking the card still starts capture with the unpinned panel visible.
                QTest.mouseClick(card, Qt.MouseButton.LeftButton, pos=QPoint(20, 20))
                tool = toolbox.registry.instances['capture']
                self.assertIsNotNone(tool.controller.selector)
                self.assertTrue(window.isVisible())
                with patch('tinytools.app.QCursor') as cursor:
                    cursor.pos.return_value = window.geometry().topLeft() - QPoint(10, 10)
                    window.retract_if_outside()
                    self.assertTrue(window.isVisible())
                tool.controller.selector.close()
                self.assertFalse(window.capture_holds_panel)

                QTest.mouseClick(switch, Qt.MouseButton.LeftButton)
                self.assertTrue(settings.value(HIDE_LAUNCHER_DURING_CAPTURE, type=bool))
                self.assertIsNone(tool.controller.selector)
                window.filter('截图')
                card = window.results.itemWidget(window.results.currentItem())
                self.assertTrue(card.findChild(CaptureVisibilitySwitch).isChecked())
            finally:
                self.app.aboutToQuit.disconnect(toolbox.cleanup)
                toolbox.cleanup()

    def test_queue_preview_closes_without_confirmation(self):
        context = ToolContext(self.app, QSettings(), Mock(), Mock())
        tool = CaptureTool(context)
        image = QImage(100, 100, QImage.Format.Format_RGB32)
        image.fill(QColor('white'))
        tool.edit_capture(image)
        editor = tool.controller.editors[0]
        QTest.mousePress(editor.canvas, Qt.MouseButton.LeftButton, pos=QPoint(10, 10))
        QTest.mouseRelease(editor.canvas, Qt.MouseButton.LeftButton, pos=QPoint(30, 30))
        self.assertTrue(editor.canvas.operations)
        with patch('screenshot.QMessageBox.question') as confirm:
            self.assertTrue(editor.close())
            confirm.assert_not_called()

    def test_capture_folder_button_works_with_empty_queue(self):
        with (tempfile.TemporaryDirectory() as directory,
              patch('screenshot.QStandardPaths.writableLocation', return_value=directory),
              patch('tinytools.capture_queue.QDesktopServices.openUrl', return_value=True) as open_url):
            window = Launcher(Registry(), Mock())
            self.addCleanup(window.suspend)
            window.reveal()
            queue = window.capture_queue
            self.assertFalse(queue.items.isVisible())
            self.assertTrue(queue.open_folder_button.isVisible())
            QTest.mouseClick(queue.open_folder_button, Qt.MouseButton.LeftButton)
            folder = Path(directory) / 'captures'
            self.assertTrue(folder.is_dir())
            open_url.assert_called_once_with(QUrl.fromLocalFile(folder.as_posix()))

    def test_repeated_capture_queues_png_files_without_opening_editors(self):
        self.addCleanup(self.app.clipboard().clear)
        window = Launcher(Registry(), Mock())
        self.addCleanup(window.suspend)
        window.collapse()
        settings = Mock()
        settings.value.return_value = False
        context = ToolContext(self.app, settings, Mock(), window.collapse,
                              suspend_launcher=window.suspend, resume_launcher=window.resume,
                              on_capture=window.capture_queue.append)
        tool = CaptureTool(context)
        self.addCleanup(tool.shutdown)
        image = QImage(600, 400, QImage.Format.Format_RGB32)
        image.fill(QColor('green'))
        image.setDevicePixelRatio(2)
        desktop = DesktopCapture([(QRect(0, 0, 300, 200), image)])
        with (tempfile.TemporaryDirectory() as directory,
              patch('screenshot.QStandardPaths.writableLocation', return_value=directory),
              patch('screenshot.desktop_image', return_value=desktop)):
            for _ in range(8):
                tool.activate()
                selector = tool.controller.selector
                QTest.mousePress(selector, Qt.MouseButton.LeftButton, pos=QPoint(20, 20))
                QTest.mouseRelease(selector, Qt.MouseButton.LeftButton, pos=QPoint(260, 140))
                self.assertIs(tool.controller.selector, selector)
                QTest.keyClick(selector, Qt.Key.Key_Return)
                self.assertIsNone(tool.controller.selector)
                self.assertFalse(tool.controller.editors)
                self.assertFalse(window.isVisible())

            window.reveal(activate=False)
            self.app.processEvents()
            items = window.capture_queue.items
            self.assertEqual(items.count(), 8)
            bar = items.horizontalScrollBar()
            self.assertGreater(bar.maximum(), 0)
            self.assertEqual(bar.value(), bar.minimum())
            viewport = items.viewport()
            QTest.mouseMove(viewport, QPoint(viewport.width() - 4, 20))
            QTest.qWait(130)
            self.assertGreater(bar.value(), bar.minimum())
            QApplication.sendEvent(viewport, QEvent(QEvent.Type.Leave))
            self.assertFalse(window.capture_queue.edge_timer.isActive())
            QTest.mouseMove(viewport, QPoint(4, 20))
            QTest.qWait(190)
            self.assertEqual(bar.value(), bar.minimum())
            paths = [Path(items.item(i).data(Qt.ItemDataRole.UserRole)) for i in range(items.count())]
            self.assertEqual(len(set(paths)), 8)
            self.assertTrue(all(path.is_file() and path.suffix == '.png' for path in paths))
            clipboard = self.app.clipboard()
            self.assertEqual(clipboard.mimeData().urls()[0].toLocalFile(), paths[0].as_posix())
            self.assertEqual(clipboard.image(), QImage(str(paths[0])))
            self.assertEqual((clipboard.image().width(), clipboard.image().height()), (482, 242))
            size = items.item(0).icon().availableSizes()[0]
            self.assertEqual(size.width(), 144)
            self.assertLessEqual(size.height(), 90)
            window.capture_queue.copy_item(items.item(7))
            self.assertEqual(clipboard.mimeData().urls()[0].toLocalFile(), paths[-1].as_posix())


if __name__ == '__main__':
    unittest.main()
