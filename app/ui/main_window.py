"""Native desktop window for the OpenVC voice changer.

A plain Qt application: no HTTP server, no browser, no webview.  The heavy
lifting is still done by :mod:`app.backend`, which is UI agnostic; this module
only renders its state and forwards user actions.
"""
from __future__ import annotations

import threading
import time
import traceback
from typing import Callable, Optional

from PySide6.QtCore import QEventLoop, QSize, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QFileDialog, QFrame,
    QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QPushButton,
    QProgressDialog, QScrollArea, QSizePolicy, QSlider, QToolButton,
    QVBoxLayout, QWidget,
)

from app.backend import audio, paths
from app.backend.controller import CONTROLLER

from .theme import C, QSS, pill_style

WARN_HINTS = {
    "VB-CABLE": "https://vb-audio.com/Cable/",
}


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

class Worker(QThread):
    """Run a blocking call off the UI thread."""

    done = Signal(object)
    failed = Signal(str)
    progress = Signal(int, int)

    def __init__(self, fn: Callable, parent=None):
        super().__init__(parent)
        self._fn = fn

    def run(self) -> None:  # noqa: D102
        try:
            self.done.emit(self._fn())
        except Exception as exc:  # pragma: no cover - shown to the user
            traceback.print_exc()
            self.failed.emit(str(exc))


class LevelBar(QWidget):
    """Thin horizontal level meter."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._v = 0.0
        self.setFixedHeight(6)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_level(self, value: float) -> None:
        value = max(0.0, min(1.0, value))
        if abs(value - self._v) > 0.004:
            self._v = value
            self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(C["meter_bg"]))
        p.drawRoundedRect(self.rect(), 3, 3)
        if self._v > 0:
            w = int(self.width() * self._v)
            grad = QColor(C["ok"])
            if self._v > 0.75:
                grad = QColor(C["bad"])
            elif self._v > 0.5:
                grad = QColor("#d4e157")
            p.setBrush(grad)
            p.drawRoundedRect(0, 0, max(w, 3), self.height(), 3, 3)


class StatTile(QFrame):
    def __init__(self, caption: str, parent=None):
        super().__init__(parent)
        self.setObjectName("Stat")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 7, 10, 7)
        lay.setSpacing(1)
        self.value = QLabel("—")
        self.value.setObjectName("StatValue")
        cap = QLabel(caption)
        cap.setObjectName("StatLabel")
        lay.addWidget(self.value)
        lay.addWidget(cap)

    def set_value(self, text: str) -> None:
        if self.value.text() != text:
            self.value.setText(text)


class IconButton(QToolButton):
    """Tool button whose glyph is painted, not taken from a font.

    Unicode symbols like ▶ ✕ ✓ are missing from many CJK UI fonts, which would
    render as tofu boxes; drawing them keeps the UI identical everywhere.
    """

    def __init__(self, kind: str, tip: str = "", parent=None):
        super().__init__(parent)
        self._kind = kind
        self._active = False
        self.setToolTip(tip)
        self.setFixedSize(26, 26)
        self.setCursor(Qt.PointingHandCursor)
        if kind == "play":
            self.setObjectName("Play")
        elif kind == "cross":
            self.setObjectName("Del")

    def set_kind(self, kind: str) -> None:
        self._kind = kind
        self.update()

    def set_active(self, active: bool) -> None:
        self._active = active
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rect = self.rect().adjusted(2, 2, -2, -2)
        cx, cy = rect.center().x() + 0.5, rect.center().y() + 0.5

        if self._kind in ("play", "pause"):
            p.setPen(Qt.NoPen)
            p.setBrush(QColor("#ffffff" if self._active else C["muted"]))
            if self._kind == "pause":
                p.drawRoundedRect(int(cx - 5), int(cy - 5), 4, 10, 1, 1)
                p.drawRoundedRect(int(cx + 1), int(cy - 5), 4, 10, 1, 1)
            else:
                from PySide6.QtGui import QPolygonF
                from PySide6.QtCore import QPointF
                tri = QPolygonF([QPointF(cx - 4, cy - 6),
                                 QPointF(cx + 6, cy),
                                 QPointF(cx - 4, cy + 6)])
                p.drawPolygon(tri)
        elif self._kind == "cross":
            p.setPen(QPen(QColor(C["muted"]), 1.6, Qt.SolidLine, Qt.RoundCap))
            d = 4.5
            p.drawLine(int(cx - d), int(cy - d), int(cx + d), int(cy + d))
            p.drawLine(int(cx + d), int(cy - d), int(cx - d), int(cy + d))
        elif self._kind == "dot":
            if self._active:
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(C["accent"]))
                p.drawEllipse(int(cx - 4), int(cy - 4), 8, 8)


class VoiceRow(QFrame):
    played = Signal(str)
    removed = Signal(str)
    picked = Signal(str)

    def __init__(self, meta: dict, parent=None):
        super().__init__(parent)
        self.setObjectName("Voice")
        self.voice_id = meta["id"]
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(48)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(9, 6, 8, 6)
        lay.setSpacing(9)

        avatar = QLabel((meta.get("name") or "?")[:1].upper())
        avatar.setObjectName("Avatar")
        avatar.setAlignment(Qt.AlignCenter)
        avatar.setFixedSize(30, 30)
        lay.addWidget(avatar)

        col = QVBoxLayout()
        col.setSpacing(0)
        name = QLabel(meta.get("name") or meta["id"])
        name.setObjectName("VoiceName")
        dur = meta.get("duration") or 0
        info = QLabel(f"{dur:.1f} 秒" if dur else "")
        info.setObjectName("VoiceInfo")
        col.addWidget(name)
        col.addWidget(info)
        lay.addLayout(col, 1)

        self.check = IconButton("dot")
        self.check.setEnabled(False)
        lay.addWidget(self.check)

        play = IconButton("play", "试听")
        play.clicked.connect(lambda: self.played.emit(self.voice_id))
        lay.addWidget(play)

        dele = IconButton("cross", "删除")
        dele.clicked.connect(lambda: self.removed.emit(self.voice_id))
        lay.addWidget(dele)

        self._name = name
        self._info = info
        self._play = play

    def set_active(self, active: bool) -> None:
        self.setProperty("active", "true" if active else "false")
        self.style().unpolish(self)
        self.style().polish(self)
        self.check.set_active(active)

    def set_playing(self, playing: bool) -> None:
        self._play.set_kind("pause" if playing else "play")
        self._play.set_active(playing)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self.picked.emit(self.voice_id)
        super().mousePressEvent(event)


# ---------------------------------------------------------------------------
# main window
# ---------------------------------------------------------------------------

class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName("Root")
        self.setWindowTitle("OpenVC 实时变声器")
        self.setMinimumSize(940, 700)
        self.resize(1080, 780)
        icon = paths.ASSETS_DIR / "openvc.ico"
        if icon.exists():
            self.setWindowIcon(QIcon(str(icon)))

        self.ctl = CONTROLLER
        self._rows: dict[str, VoiceRow] = {}
        self._loading = True
        self._players: list[Worker] = []
        self._pending_preview: Optional[str] = None

        self._build()
        self.setStyleSheet(QSS)
        self._load_devices()
        self._load_voices()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh)
        self._timer.start(100)

        QTimer.singleShot(300, self._maybe_onboard)

    # -- construction ----------------------------------------------------
    def _card(self, title: str) -> tuple[QFrame, QVBoxLayout]:
        frame = QFrame()
        frame.setObjectName("Card")
        outer = QVBoxLayout(frame)
        outer.setContentsMargins(16, 14, 16, 14)
        outer.setSpacing(9)
        if title:
            head = QLabel(title)
            head.setObjectName("CardTitle")
            outer.addWidget(head)
        return frame, outer

    def _label(self, text: str) -> QLabel:
        lab = QLabel(text)
        lab.setObjectName("FieldLabel")
        return lab

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 14)
        root.setSpacing(11)

        # ---- header
        top = QHBoxLayout()
        top.setSpacing(11)
        logo = QLabel("◉")
        logo.setFixedSize(40, 40)
        logo.setAlignment(Qt.AlignCenter)
        logo.setStyleSheet(
            "background: qlineargradient(x1:0,y1:0,x2:1,y2:1,"
            f"stop:0 {C['accent']}, stop:1 {C['accent2']});"
            "border-radius: 11px; color: white; font-size: 19px;")
        top.addWidget(logo)

        titles = QVBoxLayout()
        titles.setSpacing(1)
        t1 = QLabel("OpenVC 实时变声器")
        t1.setObjectName("Title")
        t2 = QLabel("本地运行 · 零样本音色克隆 · 虚拟麦克风")
        t2.setObjectName("Subtitle")
        titles.addWidget(t1)
        titles.addWidget(t2)
        top.addLayout(titles)
        top.addStretch(1)

        self.pill = QLabel("启动中")
        self.pill.setObjectName("Pill")
        self.pill.setAlignment(Qt.AlignCenter)
        top.addWidget(self.pill)

        spec = QLabel("120ms 分块")
        spec.setObjectName("Pill")
        spec.setAlignment(Qt.AlignCenter)
        spec.setToolTip("每 120 ms 音频推理一次，端到端延迟约 0.4 秒")
        top.addWidget(spec)

        self.test_btn = QPushButton("自检")
        self.test_btn.setObjectName("Ghost")
        self.test_btn.setToolTip("检查虚拟声卡和麦克风")
        self.test_btn.clicked.connect(self._on_selftest)
        top.addWidget(self.test_btn)
        root.addLayout(top)

        # ---- banners
        self.banner_box = QVBoxLayout()
        self.banner_box.setSpacing(6)
        root.addLayout(self.banner_box)

        # ---- body
        body = QHBoxLayout()
        body.setSpacing(11)

        left, lbox = self._card("音频路由")
        self.in_combo = QComboBox()
        self.out_combo = QComboBox()
        self.mon_combo = QComboBox()
        for lab, w in (("麦克风输入", self.in_combo),
                       ("虚拟麦克风（输出）", self.out_combo)):
            lbox.addWidget(self._label(lab))
            lbox.addWidget(w)
        self.cable_hint = QLabel("")
        self.cable_hint.setObjectName("Hint")
        self.cable_hint.setTextFormat(Qt.RichText)
        self.cable_hint.setWordWrap(True)
        lbox.addWidget(self.cable_hint)

        lbox.addWidget(self._label("本地监听（可选）"))
        lbox.addWidget(self.mon_combo)

        row = QHBoxLayout()
        row.setSpacing(16)
        self.monitor_chk = QCheckBox("开启监听")
        self.bypass_chk = QCheckBox("直通（不变声）")
        self.denoise_chk = QCheckBox("降噪")
        self.denoise_chk.setToolTip(
            "DeepFilterNet3 抑制键盘声、风扇声、街道噪声。\n"
            "会增加约 30 ms 处理时间，环境安静时可以关掉。")
        self.monitor_chk.setChecked(True)
        row.addWidget(self.monitor_chk)
        row.addWidget(self.bypass_chk)
        row.addWidget(self.denoise_chk)
        row.addStretch(1)
        lbox.addLayout(row)

        self._adv_toggle = QPushButton("音量微调")
        self._adv_toggle.setObjectName("Ghost")
        self._adv_toggle.setCheckable(True)
        self._adv_toggle.clicked.connect(self._toggle_adv)
        lbox.addWidget(self._adv_toggle, alignment=Qt.AlignLeft)

        self._adv = QWidget()
        av = QVBoxLayout(self._adv)
        av.setContentsMargins(0, 4, 0, 0)
        av.setSpacing(6)
        self.in_gain, self.in_gain_lab = self._slider_row(av, "输入增益", 0, 300)
        self.out_gain, self.out_gain_lab = self._slider_row(av, "输出增益", 0, 200)
        self._adv.setVisible(False)
        lbox.addWidget(self._adv)
        lbox.addStretch(1)
        body.addWidget(left, 1)

        right, rbox = self._card("目标音色")
        self.voice_scroll = QScrollArea()
        self.voice_scroll.setWidgetResizable(True)
        self.voice_scroll.setMinimumHeight(210)
        self.voice_scroll.setFrameShape(QFrame.NoFrame)
        self.voice_scroll.viewport().setAutoFillBackground(False)
        self.voice_scroll.viewport().setStyleSheet("background: transparent;")
        holder = QWidget()
        holder.setAutoFillBackground(False)
        holder.setStyleSheet("background: transparent;")
        self.voice_box = QVBoxLayout(holder)
        self.voice_box.setContentsMargins(0, 0, 4, 0)
        self.voice_box.setSpacing(6)
        self.voice_box.addStretch(1)
        self.voice_scroll.setWidget(holder)
        rbox.addWidget(self.voice_scroll, 1)

        addrow = QHBoxLayout()
        addrow.setSpacing(7)
        self.add_btn = QPushButton("选择参考音频…")
        self.add_btn.clicked.connect(self._on_add_voice)
        addrow.addWidget(self.add_btn, 1)
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("名称（可选）")
        self.name_edit.setFixedWidth(130)
        addrow.addWidget(self.name_edit)
        rbox.addLayout(addrow)
        hint = QLabel("3–10 秒清晰人声，wav/flac 最佳。会自动转 16 kHz 并生成试听。")
        hint.setObjectName("Hint")
        hint.setWordWrap(True)
        rbox.addWidget(hint)
        body.addWidget(right, 1)
        root.addLayout(body, 1)

        # ---- transport
        trans_card, tbox = self._card("")
        trans = QHBoxLayout()
        trans.setSpacing(10)
        self.start_btn = QPushButton("开始变声")
        self.start_btn.setObjectName("Primary")
        self.start_btn.setMinimumHeight(42)
        self.start_btn.setMinimumWidth(130)
        self.start_btn.clicked.connect(self._on_start)
        self.stop_btn = QPushButton("停止")
        self.stop_btn.setObjectName("Danger")
        self.stop_btn.setMinimumHeight(42)
        self.stop_btn.clicked.connect(self._on_stop)
        trans.addWidget(self.start_btn)
        trans.addWidget(self.stop_btn)

        nowbox = QVBoxLayout()
        nowbox.setSpacing(0)
        n1 = QLabel("对方会听到")
        n1.setObjectName("NowLabel")
        self.now_value = QLabel("—")
        self.now_value.setObjectName("NowValue")
        nowbox.addWidget(n1)
        nowbox.addWidget(self.now_value)
        trans.addSpacing(8)
        trans.addLayout(nowbox)
        trans.addStretch(1)

        meters = QVBoxLayout()
        meters.setSpacing(5)
        for text, attr in (("输入", "in_bar"), ("输出", "out_bar")):
            line = QHBoxLayout()
            line.setSpacing(7)
            lab = QLabel(text)
            lab.setObjectName("FieldLabel")
            lab.setFixedWidth(26)
            bar = LevelBar()
            setattr(self, attr, bar)
            line.addWidget(lab)
            line.addWidget(bar, 1)
            meters.addLayout(line)
        meters.setContentsMargins(0, 0, 0, 0)
        wrap = QWidget()
        wrap.setLayout(meters)
        wrap.setMinimumWidth(230)
        trans.addWidget(wrap)
        tbox.addLayout(trans)

        stats = QHBoxLayout()
        stats.setSpacing(7)
        self.tiles = {}
        for key, cap in (("latency", "端到端延迟"), ("rtf", "实时率 RTF"),
                         ("proc", "单块耗时"), ("under", "欠载次数"),
                         ("chunks", "已处理块"), ("uptime", "运行时长")):
            tile = StatTile(cap)
            self.tiles[key] = tile
            stats.addWidget(tile)
        tbox.addLayout(stats)

        self.log_toggle = QPushButton("运行日志")
        self.log_toggle.setObjectName("Ghost")
        self.log_toggle.setCheckable(True)
        self.log_toggle.clicked.connect(self._toggle_log)
        tbox.addWidget(self.log_toggle, alignment=Qt.AlignLeft)
        self.log_view = QPlainTextEdit()
        self.log_view.setObjectName("Log")
        self.log_view.setReadOnly(True)
        self.log_view.setFixedHeight(110)
        self.log_view.setVisible(False)
        tbox.addWidget(self.log_view)
        root.addWidget(trans_card)

        # ---- footer
        foot = QHBoxLayout()
        fl = QLabel("会议软件里把麦克风选成 <b>CABLE Output</b>。关闭本窗口即停止变声。")
        fl.setObjectName("Hint")
        fl.setTextFormat(Qt.RichText)
        foot.addWidget(fl)
        foot.addStretch(1)
        self.conn = QLabel("")
        self.conn.setObjectName("Hint")
        foot.addWidget(self.conn)
        q = QPushButton("退出程序")
        q.setObjectName("Ghost")
        q.clicked.connect(self.close)
        foot.addWidget(q)
        root.addLayout(foot)

    def _slider_row(self, parent_layout, text: str, lo: int, hi: int):
        line = QHBoxLayout()
        lab = self._label(text)
        lab.setFixedWidth(58)
        slider = QSlider(Qt.Horizontal)
        slider.setRange(lo, hi)
        slider.setValue(100 if hi == 300 else 100)
        out = QLabel("1.00")
        out.setFixedWidth(38)
        out.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        slider.valueChanged.connect(lambda v: out.setText(f"{v/100:.2f}"))
        line.addWidget(lab)
        line.addWidget(slider, 1)
        line.addWidget(out)
        parent_layout.addLayout(line)
        return slider, out

    # -- small toggles ---------------------------------------------------
    def _toggle_adv(self) -> None:
        self._adv.setVisible(self._adv_toggle.isChecked())

    def _toggle_log(self) -> None:
        self.log_view.setVisible(self.log_toggle.isChecked())

    # -- data ------------------------------------------------------------
    def _load_devices(self) -> None:
        self._loading = True
        devs = audio.list_devices()
        st = self.ctl.state()

        self.in_combo.clear()
        for d in devs["input"]:
            self.in_combo.addItem(d.name, d.index)
        self.out_combo.clear()
        for d in devs["output"]:
            self.out_combo.addItem(d.name, d.index)

        cable = audio.find_default_cable_output()
        if cable:
            self.out_combo.setCurrentIndex(
                max(0, self.out_combo.findData(cable.index)))

        self.mon_combo.clear()
        self.mon_combo.addItem("（不监听）", None)
        for d in devs["output"]:
            if "CABLE" not in d.name:
                self.mon_combo.addItem(d.name, d.index)

        if st["input_index"] is not None:
            i = self.in_combo.findData(st["input_index"])
            if i >= 0:
                self.in_combo.setCurrentIndex(i)
        if st["output_index"] is not None:
            i = self.out_combo.findData(st["output_index"])
            if i >= 0:
                self.out_combo.setCurrentIndex(i)
        if st["monitor_index"] is not None:
            i = self.mon_combo.findData(st["monitor_index"])
            if i >= 0:
                self.mon_combo.setCurrentIndex(i)
        else:
            mon = audio.find_monitor_device()
            if mon:
                i = self.mon_combo.findData(mon.index)
                if i >= 0:
                    self.mon_combo.setCurrentIndex(i)

        self.monitor_chk.setChecked(bool(st["monitor_enabled"]))
        self.bypass_chk.setChecked(bool(st["bypass"]))
        self.denoise_chk.setChecked(bool(st.get("denoise", False)))
        available = bool(st.get("denoise_available", False))
        self.denoise_chk.setEnabled(available)
        if not available:
            self.denoise_chk.setToolTip("未安装降噪组件（denoise 文件夹）")
        self.in_gain.setValue(int(round(float(st["input_gain"]) * 100)))
        self.out_gain.setValue(int(round(float(st["output_gain"]) * 100)))

        self._update_cable_hint(st["cable_present"])
        self._loading = False


    def _update_cable_hint(self, present: bool) -> None:
        if present:
            self.cable_hint.setText(
                "会议软件里把麦克风选成 <b>CABLE Output</b>。")
        elif paths.driver_pack() is not None:
            tpl = ('<span style="color:WARN">未检测到虚拟声卡。请解压并运行本目录 '
                   '<b>驱动\\</b> 文件夹里的 VBCABLE_Setup_x64.exe'
                   '（右键 → 以管理员身份运行），装完重启电脑。</span>')
            self.cable_hint.setText(tpl.replace("WARN", C["warn"]))
        else:
            tpl = ('<span style="color:WARN">未检测到 VB-CABLE，会议软件里看不到'
                   '本软件的声音。请到 <a href="https://vb-audio.com/Cable/" '
                   'style="color:WARN">vb-audio.com/Cable</a> 安装后重启。</span>')
            self.cable_hint.setText(tpl.replace("WARN", C["warn"]))

    def _load_voices(self) -> None:
        voices = self.ctl.bank.list()
        for row in self._rows.values():
            row.setParent(None)
            row.deleteLater()
        self._rows.clear()

        while self.voice_box.count() > 1:
            item = self.voice_box.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for meta in voices:
            row = VoiceRow(meta)
            row.picked.connect(self._on_pick_voice)
            row.played.connect(self._on_preview)
            row.removed.connect(self._on_delete_voice)
            self.voice_box.insertWidget(self.voice_box.count() - 1, row)
            self._rows[meta["id"]] = row
        self._apply_voice_state()

    def _apply_voice_state(self) -> None:
        active = self.ctl.voice_id
        for vid, row in self._rows.items():
            row.set_active(vid == active)

    # -- periodic refresh ------------------------------------------------
    def _refresh(self) -> None:
        st = self.ctl.state()
        s = st["stats"]

        if st["running"]:
            self.pill.setText("● 运行中")
            pill_style(self.pill, "live")
        elif st["ready"]:
            self.pill.setText("就绪")
            pill_style(self.pill, "ready")
        elif st["preparing"]:
            self.pill.setText("加载模型中…")
            pill_style(self.pill, "idle")
        elif st["prepare_error"]:
            self.pill.setText("加载失败")
            pill_style(self.pill, "bad")
        else:
            self.pill.setText("启动中")
            pill_style(self.pill, "idle")

        self.start_btn.setEnabled(st["ready"] and not st["running"])
        self.stop_btn.setEnabled(st["running"])
        self.start_btn.setText("加载模型中…" if st["preparing"] else "开始变声")

        self.now_value.setText(
            "原声（直通）" if st["bypass"] else (st["voice_name"] or "—"))

        lat = s.get("latency_ms") or 0
        self.tiles["latency"].set_value(f"{lat:.0f} ms" if lat else "—")
        rtf = s.get("rtf") or 0
        self.tiles["rtf"].set_value(f"{rtf:.2f}" if rtf else "—")
        proc = s.get("proc_ms") or 0
        self.tiles["proc"].set_value(f"{proc:.0f} ms" if proc else "—")
        self.tiles["under"].set_value(str(s.get("underruns", 0)))
        self.tiles["chunks"].set_value(str(s.get("chunks", 0)))
        up = st.get("uptime") or 0
        self.tiles["uptime"].set_value(
            f"{up // 60}分{up % 60}秒" if up >= 60 else (f"{up}秒" if up else "—"))

        self.in_bar.set_level((s.get("in_peak") or 0) * 1.4)
        self.out_bar.set_level((s.get("out_peak") or 0) * 1.4)

        self._apply_banners(st.get("warnings") or [])

        logs = "\n".join(st.get("logs") or [])
        if logs and logs != self.log_view.toPlainText():
            self.log_view.setPlainText(logs)
            bar = self.log_view.verticalScrollBar()
            bar.setValue(bar.maximum())

        self.conn.setText("")

    def _apply_banners(self, warnings: list) -> None:
        key = tuple(w["text"] for w in warnings)
        if getattr(self, "_banner_key", None) == key:
            return
        self._banner_key = key

        while self.banner_box.count():
            item = self.banner_box.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for w in warnings:
            frame = QFrame()
            frame.setObjectName("Banner")
            frame.setProperty("level", w.get("level", "warn"))
            lay = QHBoxLayout(frame)
            lay.setContentsMargins(12, 8, 12, 8)
            lab = QLabel(w["text"])
            lab.setObjectName("BannerText")
            lab.setProperty("level", w.get("level", "warn"))
            lab.setWordWrap(True)
            lab.setTextFormat(Qt.PlainText)
            lay.addWidget(lab)
            self.banner_box.addWidget(frame)

    # -- actions ---------------------------------------------------------
    def _config(self) -> dict:
        return {
            "voice_id": self.ctl.voice_id,
            "input_index": self.in_combo.currentData(),
            "output_index": self.out_combo.currentData(),
            "monitor_index": self.mon_combo.currentData(),
            "monitor_enabled": self.monitor_chk.isChecked(),
            "bypass": self.bypass_chk.isChecked(),
            "denoise": self.denoise_chk.isChecked(),
            "input_gain": self.in_gain.value() / 100.0,
            "output_gain": self.out_gain.value() / 100.0,
        }

    def _on_start(self) -> None:
        if not self.ctl.state()["ready"]:
            self._toast("模型还在加载，请稍候", error=True)
            return
        if not self.ctl.voice_id and not self.bypass_chk.isChecked():
            self._toast("请先选择一个目标音色", error=True)
            return
        self.start_btn.setEnabled(False)
        try:
            self.ctl.start(self._config())
        except Exception as exc:
            self._toast(f"启动失败：{exc}", error=True)
            self.start_btn.setEnabled(True)

    def _on_stop(self) -> None:
        self.ctl.stop()

    def _on_pick_voice(self, vid: str) -> None:
        try:
            self.ctl.select_voice(vid)
        except Exception as exc:
            self._toast(f"切换失败：{exc}", error=True)
            return
        self._apply_voice_state()

    def _on_preview(self, vid: str) -> None:
        row = self._rows.get(vid)
        if row is None:
            return
        row.set_playing(True)

        def job():
            path = self.ctl.ensure_preview(vid)
            if path is None:
                raise RuntimeError("试听生成失败")
            import winsound
            winsound.PlaySound(str(path), winsound.SND_FILENAME | winsound.SND_ASYNC)
            return path

        w = Worker(job)
        w.failed.connect(lambda msg: self._toast(f"试听失败：{msg}", error=True))
        w.done.connect(lambda _p: QTimer.singleShot(2600, lambda: row.set_playing(False)))
        w.start()
        self._players.append(w)

    def _on_delete_voice(self, vid: str) -> None:
        meta = self.ctl.bank.get(vid) or {}
        if QMessageBox.question(
                self, "删除音色",
                f"确定删除「{meta.get('name', vid)}」？") != QMessageBox.Yes:
            return
        self.ctl.bank.delete(vid)
        if self.ctl.voice_id == vid:
            self.ctl.voice_id = None
            self.ctl.save_settings()
        self._load_voices()

    def _fetch_speaker(self) -> bool:
        """Offer to download the speaker encoder; True when it is usable."""
        answer = QMessageBox.question(
            self, "需要下载一次音色模型",
            "添加新音色需要「说话人编码器」，大小 369 MB，只需下载一次。\n\n"
            "内置的 6 个音色不需要它，可以直接用来变声。\n\n"
            "现在下载吗？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
        if answer != QMessageBox.Yes:
            return False

        dlg = QProgressDialog("正在连接…", "取消", 0, 100, self)
        dlg.setWindowTitle("下载说话人编码器")
        dlg.setWindowModality(Qt.WindowModal)
        dlg.setMinimumDuration(0)
        dlg.setAutoClose(False)
        dlg.setAutoReset(False)
        dlg.setValue(0)

        state = {"cancel": False}
        dlg.canceled.connect(lambda: state.__setitem__("cancel", True))

        holder = {}

        def job():
            return self.ctl.download_speaker(
                on_progress=lambda done, total: holder["w"].progress.emit(done, total),
                cancelled=lambda: state["cancel"])

        w = Worker(job)
        holder["w"] = w
        loop = QEventLoop()
        result = {"ok": False}

        def on_progress(done: int, total: int) -> None:
            if total <= 0:
                return
            dlg.setValue(int(done * 100 / total))
            dlg.setLabelText(
                f"正在下载… {done / 1048576:.0f} / {total / 1048576:.0f} MB")

        def on_done(_path) -> None:
            result["ok"] = True
            loop.quit()

        def on_failed(msg: str) -> None:
            self._toast(f"下载失败：{msg}", error=True)
            loop.quit()

        w.progress.connect(on_progress)
        w.done.connect(on_done)
        w.failed.connect(on_failed)
        w.start()
        loop.exec()
        dlg.close()
        w.wait(3000)
        self._players.append(w)
        if result["ok"]:
            self._toast("说话人编码器已就绪")
        return result["ok"]

    def _on_add_voice(self) -> None:
        if not self.ctl.speaker_ready() and not self._fetch_speaker():
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "选择参考音频", "",
            "音频文件 (*.wav *.flac *.ogg *.mp3);;所有文件 (*.*)")
        if not path:
            return
        name = self.name_edit.text().strip() or None
        self.add_btn.setEnabled(False)
        self.add_btn.setText("处理中…")

        def job():
            meta = self.ctl.add_voice(path, name)
            self.ctl.ensure_preview(meta["id"])
            return meta

        w = Worker(job)
        w.done.connect(self._on_voice_added)
        w.failed.connect(lambda msg: self._toast(f"添加失败：{msg}", error=True))
        w.finished.connect(self._reset_add_btn)
        w.start()
        self._players.append(w)

    def _reset_add_btn(self) -> None:
        self.add_btn.setEnabled(True)
        self.add_btn.setText("选择参考音频…")

    def _on_voice_added(self, meta: dict) -> None:
        self.name_edit.clear()
        self._load_voices()
        self._on_pick_voice(meta["id"])
        self._toast(f"已添加音色：{meta['name']}")

    def _on_selftest(self) -> None:
        self.test_btn.setEnabled(False)
        self.test_btn.setText("检测中…")

        w = Worker(lambda: self.ctl.self_test())
        w.done.connect(self._show_selftest)
        w.failed.connect(lambda msg: self._toast(f"自检失败：{msg}", error=True))
        w.finished.connect(self._reset_test_btn)
        w.start()
        self._players.append(w)

    def _reset_test_btn(self) -> None:
        self.test_btn.setEnabled(True)
        self.test_btn.setText("自检")

    def _show_selftest(self, result: dict) -> None:
        box = QMessageBox(self)
        box.setWindowTitle("自检结果")
        if result.get("ok"):
            box.setIcon(QMessageBox.Information)
            box.setText("自检通过 ✅")
        else:
            box.setIcon(QMessageBox.Warning)
            box.setText("自检发现问题")
        lines = []
        for s in result.get("steps", []):
            mark = "✓" if s["ok"] else "✕"
            lines.append(f"{mark}  {s['name']}\n     {s['detail']}")
        box.setInformativeText("\n\n".join(lines))
        box.exec()

    # -- misc ------------------------------------------------------------
    def _toast(self, text: str, error: bool = False) -> None:
        box = QMessageBox(self)
        box.setWindowTitle("提示")
        box.setIcon(QMessageBox.Critical if error else QMessageBox.Information)
        box.setText(text)
        box.exec()

    def _maybe_onboard(self) -> None:
        if self.ctl.first_run_done:
            return
        st = self.ctl.state()
        if st["cable_present"]:
            cable = "✅ 已检测到 VB-CABLE。"
        elif paths.driver_pack() is not None:
            cable = ("⚠️ 未检测到虚拟声卡。\n"
                     "     先运行本目录「驱动」文件夹里的 VBCABLE_Setup_x64.exe\n"
                     "     （右键 → 以管理员身份运行），装完重启电脑。")
        else:
            cable = "⚠️ 未检测到 VB-CABLE，请先安装虚拟声卡后再试。"
        box = QMessageBox(self)
        box.setWindowTitle("欢迎使用 OpenVC")
        box.setIcon(QMessageBox.Information)
        box.setText("三步开始变声")
        box.setInformativeText(
            f"1. 确认虚拟声卡\n     {cable}\n\n"
            "2. 选一个目标音色\n     点音色卡片右侧的 ▶ 可以先试听效果。\n\n"
            "3. 开始变声并切换麦克风\n"
            "     点「开始变声」，然后在会议软件里把麦克风选成 CABLE Output。")
        test = box.addButton("先做个自检", QMessageBox.ActionRole)
        box.addButton("知道了", QMessageBox.AcceptRole)
        box.exec()
        if box.clickedButton() is test:
            self._on_selftest()
        self.ctl.first_run_done = True
        self.ctl.save_settings()

    def closeEvent(self, event) -> None:  # noqa: N802
        if self.ctl.state()["running"]:
            if QMessageBox.question(
                    self, "退出", "退出会停止变声，确定吗？") != QMessageBox.Yes:
                event.ignore()
                return
        self._timer.stop()
        try:
            self.ctl.stop()
        finally:
            QApplication.instance().quit()
        event.accept()


