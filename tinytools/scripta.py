"""Host Scripta's existing editor assets in the Workstation notes window."""

import json
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory

from PySide6.QtCore import QEventLoop, QFile, QIODevice, QObject, QTimer, QUrl, Signal, Slot
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import (
    QWebEnginePage, QWebEngineProfile, QWebEngineSettings, QWebEngineUrlRequestInterceptor,
)
from PySide6.QtWebEngineWidgets import QWebEngineView


REQUIRED_FILES = ('index.html', 'editor.js', 'visual-markdown.js', 'style.css',
                  'vendor/marked.js', 'vendor/purify.js')


def find_assets(path):
    for folder in (path, path / 'app', path / 'web'):
        if all((folder / name).is_file() for name in REQUIRED_FILES):
            return folder
    return None


class EditorRequests(QWebEngineUrlRequestInterceptor):
    def __init__(self, folder, parent):
        super().__init__(parent)
        self.folder = folder

    def interceptRequest(self, request):
        url = request.requestUrl()
        if url.scheme() == 'data':
            return
        if url.isLocalFile() and Path(url.toLocalFile()).is_relative_to(self.folder):
            return
        request.block(True)


class EditorPage(QWebEnginePage):
    def __init__(self, profile, url, parent):
        super().__init__(profile, parent)
        self.editor_path = url.toLocalFile()

    def acceptNavigationRequest(self, url, navigation_type, is_main_frame):
        return is_main_frame and url.isLocalFile() and url.toLocalFile() == self.editor_path


class EditorBridge(QObject):
    changed = Signal(str, int, str)
    save_requested = Signal()

    @Slot(str, int, str)
    def edited(self, token, revision, markdown):
        self.changed.emit(token, revision, markdown)

    @Slot()
    def save(self):
        self.save_requested.emit()


class ScriptaEditor(QWebEngineView):
    ready = Signal()
    failed = Signal(str)

    def __init__(self, assets, parent):
        super().__init__(parent)
        self.prepared = self.loaded = False
        self.directory = TemporaryDirectory(prefix='tinytools-scripta-', ignore_cleanup_errors=True)
        folder = Path(self.directory.name)
        try:
            self.prepare_assets(assets, folder)
        except Exception:
            self.directory.cleanup()
            raise
        self.destroyed.connect(self.directory.cleanup)
        url = QUrl.fromLocalFile(str(folder / 'index.html'))
        self.profile = QWebEngineProfile(self)
        self.requests = EditorRequests(folder, self.profile)
        self.profile.setUrlRequestInterceptor(self.requests)
        page = EditorPage(self.profile, url, self.profile)
        self.setPage(page)
        page.settings().setAttribute(QWebEngineSettings.WebAttribute.LocalStorageEnabled, False)
        page.settings().setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanOpenWindows, False)
        self.bridge = EditorBridge(page)
        self.channel = QWebChannel(page)
        self.channel.registerObject('notes', self.bridge)
        page.setWebChannel(self.channel)
        page.renderProcessTerminated.connect(
            lambda *_: self.report_failure('思刻编辑器已中断。'))
        self.loadFinished.connect(self.check_ready)
        self.load(url)

    @staticmethod
    def prepare_assets(assets, folder):
        for name in (*REQUIRED_FILES, 'AppIcon.ico', 'scripta-logo-carved-stone.png'):
            if name == 'editor.js':
                continue
            source = assets / name
            if source.is_file():
                target = folder / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
        channel = QFile(':/qtwebchannel/qwebchannel.js')
        if not channel.open(QIODevice.OpenModeFlag.ReadOnly):
            raise OSError('无法加载 Qt WebChannel。')
        (folder / 'qwebchannel.js').write_bytes(bytes(channel.readAll()))
        index = folder / 'index.html'
        html = index.read_text(encoding='utf-8')
        editor_tag = '<script defer src="./editor.js"></script>'
        script = (assets / 'editor.js').read_text(encoding='utf-8-sig').rstrip()
        if editor_tag not in html or not script.endswith('})();') or 'function replaceDocument(' not in script:
            raise ValueError('当前思刻资源版本与随记不兼容。')
        index.write_text(html.replace(editor_tag, '<script defer src="./qwebchannel.js"></script>\n  ' + editor_tag),
                         encoding='utf-8')
        adapter = Path(__file__).with_name('scripta_adapter.js').read_text(encoding='utf-8')
        (folder / 'editor.js').write_text(script.removesuffix('})();') + adapter + '\n})();', encoding='utf-8')

    def check_ready(self, success):
        if success:
            self.page().runJavaScript('Boolean(window.workstationNotes)', self.editor_ready)
        else:
            self.report_failure('无法载入思刻编辑器。')

    def editor_ready(self, ready):
        if ready:
            self.prepared = True
            self.ready.emit()
        else:
            self.report_failure('思刻编辑器初始化失败。')

    def report_failure(self, message):
        self.prepared = self.loaded = False
        self.failed.emit(message)

    def open_note(self, token, title, markdown):
        self.loaded = False
        self.setEnabled(False)
        arguments = json.dumps([token, title, markdown])
        self.token = token
        self.page().runJavaScript(f'window.workstationNotes.open(...{arguments})',
                                  lambda result: self.note_ready(token, result))

    def note_ready(self, token, result):
        if token != self.token:
            return
        if result is not True:
            self.report_failure('无法在思刻中打开当前笔记。')
            return
        self.loaded = True
        self.setEnabled(True)

    def snapshot(self):
        result = []
        loop = QEventLoop()
        timeout = QTimer()
        timeout.setSingleShot(True)
        timeout.timeout.connect(loop.quit)

        def completed(value):
            result.append(value)
            loop.quit()

        self.page().runJavaScript('window.workstationNotes?.snapshot()', completed)
        if not result:
            timeout.start(2000)
            loop.exec(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)
        return json.loads(result[0]) if result and isinstance(result[0], str) else None
