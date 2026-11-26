"""Small plugin contract; the launcher knows nothing about individual tools."""
from dataclasses import dataclass
from importlib import import_module
import logging
from pathlib import Path
import pkgutil
from typing import Callable, Protocol

from PySide6.QtCore import QSettings
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication


class Tool(Protocol):
    def activate(self) -> None: ...
    def can_exit(self) -> bool: ...
    def shutdown(self) -> None: ...


@dataclass(frozen=True)
class ToolSpec:
    id: str
    name: str
    description: str
    keywords: tuple[str, ...] = ()
    symbol: str = '◇'
    shortcut: str = ''
    hotkey_key: int = 0
    hotkey_modifiers: int = 0x0001


@dataclass
class ToolContext:
    app: QApplication
    settings: QSettings
    notify: Callable[[str, str], None]
    hide_launcher: Callable[[], None]
    suspend_launcher: Callable[[], None] | None = None
    resume_launcher: Callable[[], None] | None = None
    on_capture: Callable[[Path, QImage], None] | None = None
    capture_error: Callable[[str], None] | None = None
    hold_launcher: Callable[[bool], None] | None = None


class Registry:
    def __init__(self):
        self.specs = {}
        self.factories = {}
        self.instances = {}
        self.errors = []

    def register(self, spec, factory):
        if not isinstance(spec, ToolSpec) or not spec.id or spec.id in self.specs:
            raise ValueError('工具 ID 为空、重复，或 SPEC 类型不正确')
        if not callable(factory):
            raise TypeError('create_tool 必须是可调用对象')
        self.specs[spec.id] = spec
        self.factories[spec.id] = factory

    def discover(self, package='tinytools.plugins'):
        root = import_module(package)
        for module in pkgutil.iter_modules(root.__path__, root.__name__ + '.'):
            try:
                plugin = import_module(module.name)
                self.register(plugin.SPEC, plugin.create_tool)
            except Exception as error:
                logging.exception('Plugin discovery failed: %s', module.name)
                self.errors.append(f'{module.name}: {error}')

    def search(self, query):
        words = query.casefold().split()
        return [spec for spec in self.specs.values()
                if all(word in ' '.join((spec.name, spec.description, *spec.keywords)).casefold()
                       for word in words)]

    def activate(self, tool_id, context):
        if tool_id not in self.instances:
            instance = self.factories[tool_id](context)
            for method in ('activate', 'can_exit', 'shutdown'):
                if not callable(getattr(instance, method, None)):
                    raise TypeError(f'工具 {tool_id} 缺少 {method} 方法')
            self.instances[tool_id] = instance
        self.instances[tool_id].activate()

    def can_exit(self):
        return all(tool.can_exit() for tool in list(self.instances.values()))

    def shutdown(self):
        for tool in list(self.instances.values()):
            try:
                tool.shutdown()
            except Exception:
                logging.exception('Tool shutdown failed')
