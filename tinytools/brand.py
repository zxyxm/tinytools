"""Shared, resolution-independent Workstation identity."""
from pathlib import Path
from PySide6.QtGui import QIcon

APP_TITLE = '工作台 Workstation'
ASSET_DIR = Path(__file__).resolve().parent.parent / 'assets'


def app_icon():
    return QIcon(str(ASSET_DIR / 'workstation.svg'))
