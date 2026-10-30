"""Filesystem layout for the OpenVC voice changer.

Works both from the source tree and from the portable (embeddable Python) build:

* source tree — ``ROOT`` is the repository root;
* portable build — ``ROOT`` is the folder next to ``OpenVC.exe``, so voices and
  models can be swapped without rebuilding anything.
"""
from __future__ import annotations

import sys
from pathlib import Path

FROZEN = bool(getattr(sys, "frozen", False))

if FROZEN:
    ROOT = Path(sys.executable).resolve().parent
else:
    APP_DIR = Path(__file__).resolve().parents[1]          # <repo>/app
    ROOT = APP_DIR.parent                                   # <repo>

VOICES_DIR = ROOT / "voices"
DATA_DIR = ROOT / "data"
LOG_DIR = DATA_DIR / "logs"
SETTINGS_FILE = DATA_DIR / "settings.json"
ASSETS_DIR = ROOT / "assets"
PREVIEW_SOURCE = ASSETS_DIR / "preview_source.wav"

TARGET_SR = 16000          # the VC model works at 16 kHz
CHUNK_SAMPLES = 2560       # 160 ms — streaming granularity of the upstream runtime

# ---------------------------------------------------------------------------
# ONNX Runtime graphs (community export of MeanVC2, graphs Apache-2.0).
# Running on ONNX Runtime keeps the whole app PyTorch-free.
# ---------------------------------------------------------------------------
ONNX_CANDIDATES = (ROOT / "onnx",)
_ONNX_ALWAYS = ("fbank", "gtm")
_ONNX_EITHER = ("asr", "dit", "vocos")     # exported in fp32 and int8 variants


def _graphs_in(directory: Path) -> bool:
    if not directory.is_dir():
        return False
    for name in _ONNX_ALWAYS:
        if not (directory / f"{name}.onnx").exists():
            return False
    for name in _ONNX_EITHER:
        if not ((directory / f"{name}.onnx").exists()
                or (directory / f"{name}.int8.onnx").exists()):
            return False
    return True


def onnx_dir() -> Path | None:
    for d in ONNX_CANDIDATES:
        if _graphs_in(d):
            return d
    return None


def onnx_speaker() -> Path | None:
    """Speaker encoder graph, if shipped (only needed to register a new voice)."""
    d = onnx_dir()
    if d is None:
        return None
    for rel in ("speaker.int8.onnx", "speaker.onnx",
                "speaker/speaker.int8.onnx", "speaker/speaker.onnx"):
        p = d / rel
        if p.exists():
            return p
    return None


def driver_pack() -> Path | None:
    """The bundled VB-CABLE installer, when this is the distributed folder."""
    d = ROOT / "驱动"
    if not d.is_dir():
        return None
    for p in sorted(d.glob("VBCABLE_Driver_Pack*.zip")):
        return p
    return None


def ensure_dirs() -> None:
    for d in (VOICES_DIR, DATA_DIR, LOG_DIR):
        d.mkdir(parents=True, exist_ok=True)


def missing_assets() -> list[str]:
    """Human readable names of missing files, empty when the app can run."""
    missing: list[str] = []
    if onnx_dir() is None:
        missing.append("ONNX 模型（onnx/ 目录）")
    if not PREVIEW_SOURCE.exists():
        missing.append("试听示例语音（assets/preview_source.wav）")
    return missing
