"""Light theme for the native Qt UI."""
from __future__ import annotations

C = {
    "bg": "#eef2f7",
    "panel": "#ffffff",
    "panel2": "#f7f9fc",
    "line": "#e2e8f0",
    "line2": "#cbd5e1",
    "text": "#1e293b",
    "muted": "#64748b",
    "accent": "#2563eb",
    "accent2": "#3b82f6",
    "ok": "#16a34a",
    "warn": "#b45309",
    "bad": "#dc2626",
    "meter_bg": "#e8edf5",
    "avatar_bg": "#e0eaff",
    "avatar_fg": "#2b4b8f",
}

QSS = f"""
* {{ outline: none; }}

QWidget#Root {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #f7f9fc, stop:0.5 {C['bg']}, stop:1 #e9eef6);
    color: {C['text']};
    font-family: "Microsoft YaHei UI", "Segoe UI";
    font-size: 13px;
}}

QFrame#Card {{
    background: {C['panel']};
    border: 1px solid {C['line']};
    border-radius: 12px;
}}

QLabel#Title {{ font-size: 17px; font-weight: 600; color: #0f172a; }}
QLabel#Subtitle {{ color: {C['muted']}; font-size: 11px; }}
QLabel#CardTitle {{ color: #334155; font-size: 12px; font-weight: 600; }}
QLabel#FieldLabel {{ color: {C['muted']}; font-size: 11px; }}
QLabel#Hint {{ color: {C['muted']}; font-size: 11px; }}
QLabel#NowLabel {{ color: {C['muted']}; font-size: 11px; }}
QLabel#NowValue {{ color: {C['accent']}; font-size: 14px; font-weight: 600; }}

QLabel#Pill {{
    border-radius: 11px; padding: 4px 12px; font-size: 12px;
    background: {C['panel2']}; color: {C['muted']}; border: 1px solid {C['line']};
}}
QLabel#Pill[state="ready"] {{ color: #1d4ed8; border-color: #bfdbfe; background: #eff6ff; }}
QLabel#Pill[state="live"]  {{ color: #15803d; border-color: #bbf7d0; background: #dcfce7; }}
QLabel#Pill[state="bad"]   {{ color: #b91c1c; border-color: #fecaca; background: #fee2e2; }}

QComboBox, QLineEdit {{
    background: #ffffff; border: 1px solid {C['line2']};
    border-radius: 8px; padding: 6px 9px; color: {C['text']};
    min-height: 20px;
    selection-background-color: {C['accent']};
}}
QComboBox:hover, QLineEdit:hover {{ border-color: #94a3b8; }}
QComboBox:focus, QLineEdit:focus {{ border-color: {C['accent']}; }}
QComboBox::drop-down {{ border: none; width: 20px; }}
QComboBox QAbstractItemView {{
    background: #ffffff; border: 1px solid {C['line2']};
    selection-background-color: #eff6ff; selection-color: #1d4ed8;
    color: {C['text']}; padding: 4px;
}}

QPushButton {{
    background: #ffffff; border: 1px solid {C['line2']};
    border-radius: 9px; padding: 7px 16px; color: #334155;
}}
QPushButton:hover:!disabled {{ border-color: {C['accent']}; color: {C['accent']}; }}
QPushButton:pressed:!disabled {{ background: #eff6ff; }}
QPushButton:disabled {{ color: #a9b6c6; border-color: {C['line']}; background: #f4f6f9; }}
QPushButton#Primary {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 {C['accent']}, stop:1 {C['accent2']});
    border: none; color: white; font-weight: 600;
}}
QPushButton#Primary:hover:!disabled {{ background: #1d4ed8; }}
QPushButton#Primary:disabled {{ background: #c7d7f5; color: #f2f6ff; }}
QPushButton#Danger {{ background: #ffffff; border: 1px solid #fecaca; color: #b91c1c; }}
QPushButton#Danger:hover:!disabled {{ background: #fef2f2; border-color: #fca5a5; }}
QPushButton#Big {{ font-size: 14px; padding: 11px 30px; font-weight: 600; }}
QPushButton#Ghost {{ background: transparent; border: 1px solid {C['line']}; color: {C['muted']}; }}
QPushButton#Ghost:hover:!disabled {{ color: {C['accent']}; border-color: {C['accent']}; }}
QPushButton#Ghost:checked {{ background: #eff6ff; border-color: {C['accent']}; color: {C['accent']}; }}

QToolButton {{
    background: #ffffff; border: 1px solid {C['line2']};
    border-radius: 12px; color: {C['muted']};
    min-width: 24px; max-width: 24px; min-height: 24px; max-height: 24px;
}}
QToolButton:hover {{ background: #eff6ff; border-color: {C['accent']}; }}
QToolButton#Play:hover {{ background: #eff6ff; }}
QToolButton#Del {{ border: none; background: transparent; }}

QCheckBox {{ color: #334155; font-size: 12px; spacing: 7px; }}
QCheckBox::indicator {{
    width: 15px; height: 15px; border-radius: 4px;
    border: 1px solid {C['line2']}; background: #ffffff;
}}
QCheckBox::indicator:hover {{ border-color: {C['accent']}; }}
QCheckBox::indicator:checked {{
    background: {C['accent']}; border-color: {C['accent']};
}}

QSlider::groove:horizontal {{
    height: 4px; background: #e2e8f0; border-radius: 2px;
}}
QSlider::sub-page:horizontal {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 {C['accent']}, stop:1 {C['accent2']});
    border-radius: 2px;
}}
QSlider::handle:horizontal {{
    width: 12px; height: 12px; margin: -5px 0; border-radius: 6px;
    background: #ffffff; border: 2px solid {C['accent']};
}}

QScrollArea {{ background: transparent; border: none; }}
QScrollBar:vertical {{ background: transparent; width: 8px; margin: 0; }}
QScrollBar::handle:vertical {{ background: #cbd5e1; border-radius: 4px; min-height: 24px; }}
QScrollBar::handle:vertical:hover {{ background: #94a3b8; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}

QFrame#Voice {{
    background: {C['panel2']}; border: 1px solid {C['line']}; border-radius: 10px;
}}
QFrame#Voice[active="true"] {{
    background: #eff6ff; border: 1px solid {C['accent']};
}}
QFrame#Voice:hover {{ border-color: #93c5fd; }}
QLabel#VoiceName {{ font-size: 13px; color: #1e293b; }}
QLabel#VoiceInfo {{ color: {C['muted']}; font-size: 10px; }}
QLabel#Avatar {{
    background: {C['avatar_bg']}; border-radius: 15px;
    color: {C['avatar_fg']}; font-size: 12px; font-weight: 600;
}}

QFrame#Banner {{ border-radius: 9px; }}
QFrame#Banner[level="warn"]  {{ background: #fffbeb; border: 1px solid #fde68a; }}
QFrame#Banner[level="error"] {{ background: #fef2f2; border: 1px solid #fecaca; }}
QLabel#BannerText {{ font-size: 12px; }}
QLabel#BannerText[level="warn"]  {{ color: #92400e; }}
QLabel#BannerText[level="error"] {{ color: #991b1b; }}

QFrame#Stat {{
    background: {C['panel2']}; border: 1px solid {C['line']}; border-radius: 9px;
}}
QLabel#StatValue {{ font-size: 15px; color: #0f172a; }}
QLabel#StatLabel {{ color: {C['muted']}; font-size: 10px; }}

QPlainTextEdit#Log {{
    background: {C['panel2']}; border: 1px solid {C['line']}; border-radius: 8px;
    color: #475569; font-family: Consolas; font-size: 11px; padding: 6px;
}}

QMessageBox {{ background: {C['panel']}; }}
QMessageBox QLabel {{ color: {C['text']}; }}
QDialog {{ background: {C['panel']}; }}
QToolTip {{
    background: #1e293b; color: #f8fafc; border: none;
    padding: 4px 8px; border-radius: 4px;
}}
"""


def pill_style(widget, state: str) -> None:
    widget.setProperty("state", state)
    widget.style().unpolish(widget)
    widget.style().polish(widget)
