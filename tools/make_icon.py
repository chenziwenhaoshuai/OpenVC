"""Paint the OpenVC mark and write it as a multi-size .ico.

Windows accepts PNG-compressed entries inside an ICO container, so this needs no
image library: Qt paints the mark, we wrap the PNGs in an ICO header.
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QRectF, Qt  # noqa: E402
from PySide6.QtGui import (QColor, QGuiApplication, QImage, QLinearGradient,  # noqa: E402
                           QPainter, QPainterPath, QPen)

SIZES = (256, 128, 64, 48, 32, 16)


def paint(size: int) -> QImage:
    img = QImage(size, size, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing, True)
    s = float(size)

    grad = QLinearGradient(0, 0, s, s)
    grad.setColorAt(0.0, QColor("#2563eb"))
    grad.setColorAt(1.0, QColor("#3b82f6"))
    path = QPainterPath()
    path.addRoundedRect(QRectF(0, 0, s, s), s * 0.22, s * 0.22)
    p.fillPath(path, grad)

    body_w, body_h = s * 0.26, s * 0.40
    body_x, body_y = (s - body_w) / 2, s * 0.17
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(255, 255, 255, 245))
    p.drawRoundedRect(QRectF(body_x, body_y, body_w, body_h), body_w / 2, body_w / 2)

    pen = QPen(QColor(255, 255, 255, 235))
    pen.setWidthF(max(1.4, s * 0.055))
    pen.setCapStyle(Qt.RoundCap)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    arc_w = s * 0.46
    p.drawArc(QRectF((s - arc_w) / 2, s * 0.28, arc_w, s * 0.40), 180 * 16, 180 * 16)

    p.drawLine(int(s / 2), int(s * 0.70), int(s / 2), int(s * 0.82))
    p.drawLine(int(s * 0.36), int(s * 0.82), int(s * 0.64), int(s * 0.82))
    p.end()
    return img


def png_bytes(img: QImage) -> bytes:
    data = QByteArray()
    buf = QBuffer(data)
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "PNG")
    buf.close()
    return bytes(data)


def main() -> int:
    _app = QGuiApplication.instance() or QGuiApplication([])
    entries = [(size, png_bytes(paint(size))) for size in SIZES]

    header = struct.pack("<HHH", 0, 1, len(entries))
    offset = len(header) + 16 * len(entries)
    directory, payload = b"", b""
    for size, data in entries:
        dim = 0 if size >= 256 else size
        directory += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(data), offset)
        payload += data
        offset += len(data)

    out = ROOT / "assets/openvc.ico"
    out.write_bytes(header + directory + payload)
    print(f"wrote {out} ({out.stat().st_size} bytes, {len(entries)} sizes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())