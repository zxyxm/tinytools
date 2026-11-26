"""Regenerate PNG/ICO brand assets from the SVG. Run with the project Python."""
from pathlib import Path
import struct
from PySide6.QtCore import QBuffer, QIODevice, QRectF
from PySide6.QtGui import QImage, QPainter, QColor, QFont
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication


def export():
    app = QApplication.instance() or QApplication([])
    root = Path(__file__).resolve().parent.parent / 'assets'
    svg = QSvgRenderer(str(root / 'workstation.svg'))
    if not svg.isValid():
        raise RuntimeError('Invalid brand SVG')
    entries = []
    sizes = [16, 24, 32, 48, 64, 128, 256]
    for size in sizes:
        image = QImage(size, size, QImage.Format.Format_ARGB32)
        image.fill(QColor(0, 0, 0, 0))
        painter = QPainter(image)
        svg.render(painter)
        painter.end()
        buffer = QBuffer()
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        if not image.save(buffer, 'PNG'):
            raise RuntimeError('Cannot encode PNG')
        entries.append(bytes(buffer.data()))
        if size == 256:
            (root / 'workstation.png').write_bytes(entries[-1])
    offset = 6 + 16 * len(entries)
    header = struct.pack('<HHH', 0, 1, len(entries))
    for size, data in zip(sizes, entries):
        header += struct.pack('<BBBBHHII', size % 256, size % 256, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
    (root / 'workstation.ico').write_bytes(header + b''.join(entries))

    preview = QImage(1000, 400, QImage.Format.Format_RGB32)
    preview.fill(QColor('#F6F3FF'))
    p = QPainter(preview)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    svg.render(p, QRectF(72, 70, 260, 260))
    p.setPen(QColor('#211B45'))
    font = QFont('Microsoft YaHei UI')
    font.setPixelSize(56)
    font.setBold(True)
    p.setFont(font)
    p.drawText(388, 194, '工作台')
    font.setPixelSize(31)
    font.setBold(False)
    p.setFont(font)
    p.setPen(QColor('#574B79'))
    p.drawText(390, 243, 'Workstation')
    for size, x in [(48, 747), (32, 823), (16, 883)]:
        svg.render(p, QRectF(x, 207 - size / 2, size, size))
    p.end()
    if not preview.save(str(root / 'workstation-brand.png')):
        raise RuntimeError('Cannot save preview')
    print('Exported SVG-derived PNG, ICO and brand preview')


if __name__ == '__main__':
    export()
