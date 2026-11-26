"""Collect visible Windows frame bounds before the screenshot overlay appears."""

import ctypes
from ctypes import wintypes
import sys

from PySide6.QtCore import QRect


def visible_window_rects():
    if sys.platform != 'win32':
        return []

    user32 = ctypes.windll.user32
    get_attribute = ctypes.windll.dwmapi.DwmGetWindowAttribute
    get_attribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
    user32.GetTopWindow.argtypes = [wintypes.HWND]
    user32.GetTopWindow.restype = wintypes.HWND
    user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
    user32.GetWindow.restype = wintypes.HWND
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsIconic.argtypes = [wintypes.HWND]
    user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]

    desktop_classes = {'Progman', 'WorkerW', 'Shell_TrayWnd', 'Shell_SecondaryTrayWnd', 'tooltips_class32'}
    bounds = []
    seen = set()
    hwnd = user32.GetTopWindow(None)
    while hwnd and hwnd not in seen:
        seen.add(hwnd)
        if (user32.IsWindowVisible(hwnd) and not user32.IsIconic(hwnd)
                and not user32.GetWindowLongW(hwnd, -20) & 0x20):  # GWL_EXSTYLE, WS_EX_TRANSPARENT
            name = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, name, len(name))
            cloaked = wintypes.DWORD()
            get_attribute(hwnd, 14, ctypes.byref(cloaked), ctypes.sizeof(cloaked))  # DWMWA_CLOAKED
            if name.value not in desktop_classes and not cloaked.value:
                rect = wintypes.RECT()
                status = get_attribute(hwnd, 9, ctypes.byref(rect), ctypes.sizeof(rect))  # DWMWA_EXTENDED_FRAME_BOUNDS
                if status == 0 or user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                    frame = QRect(rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top)
                    if not frame.isEmpty():
                        bounds.append(frame)
        hwnd = user32.GetWindow(hwnd, 2)  # GW_HWNDNEXT
    return bounds
