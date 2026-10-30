"""On-demand download of the optional speaker-encoder graph.

The speaker encoder is only needed to register a new reference voice, and it is
by far the largest file (369 MB — it is WavLM-Large).  Shipping it makes the
whole package four times bigger for a feature most users never touch, so it is
fetched the first time someone actually adds a voice.

Downloads resume from a partial file, retry, and fall back to a mirror, because
a 369 MB transfer over a flaky link should not start from zero.
"""
from __future__ import annotations

import ssl
import time
import urllib.request
from pathlib import Path
from typing import Callable, Optional

SPEAKER_NAME = "speaker.int8.onnx"
SPEAKER_BYTES = 387_106_790          # exact size of the published file
SPEAKER_MIRRORS = (
    "https://huggingface.co/kiarina/MeanVC2-ONNX/resolve/main/speaker/speaker.int8.onnx",
    "https://hf-mirror.com/kiarina/MeanVC2-ONNX/resolve/main/speaker/speaker.int8.onnx",
)
_ATTEMPTS_PER_MIRROR = 3
_TIMEOUT = 60
_CHUNK = 1 << 20

Progress = Callable[[int, int], None]


class DownloadError(RuntimeError):
    """Raised when every mirror failed."""


class Cancelled(DownloadError):
    """Raised when the caller asked to stop."""


def _attempt(url: str, part: Path, expect: int,
             on_progress: Optional[Progress],
             cancelled: Optional[Callable[[], bool]]) -> int:
    """One HTTP request, resuming the existing partial file when possible."""
    offset = part.stat().st_size if part.exists() else 0
    headers = {"User-Agent": "OpenVC/1.0"}
    if offset:
        headers["Range"] = f"bytes={offset}-"

    req = urllib.request.Request(url, headers=headers)
    context = ssl.create_default_context()
    with urllib.request.urlopen(req, timeout=_TIMEOUT, context=context) as resp:
        if offset and getattr(resp, "status", 200) != 206:
            offset = 0                       # server ignored Range: start over
        length = int(resp.headers.get("Content-Length") or 0)
        total = (length + offset) if length else expect
        done = offset
        with open(part, "ab" if offset else "wb") as fh:
            while True:
                if cancelled is not None and cancelled():
                    raise Cancelled("已取消下载")
                buf = resp.read(_CHUNK)
                if not buf:
                    break
                fh.write(buf)
                done += len(buf)
                if on_progress is not None:
                    on_progress(done, max(total, done))
    return part.stat().st_size


def download_speaker(directory: Path,
                     on_progress: Optional[Progress] = None,
                     cancelled: Optional[Callable[[], bool]] = None) -> Path:
    """Fetch the speaker encoder into ``directory`` and return its path."""
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / SPEAKER_NAME
    part = directory / (SPEAKER_NAME + ".part")
    if target.exists() and target.stat().st_size >= SPEAKER_BYTES * 0.99:
        return target

    last_error: Optional[Exception] = None
    for url in SPEAKER_MIRRORS:
        for attempt in range(_ATTEMPTS_PER_MIRROR):
            try:
                size = _attempt(url, part, SPEAKER_BYTES, on_progress, cancelled)
                if size >= SPEAKER_BYTES * 0.99:
                    part.replace(target)
                    return target
                last_error = DownloadError(f"文件不完整（{size} 字节）")
            except Cancelled:
                if part.exists():
                    part.unlink()
                raise
            except Exception as exc:
                last_error = exc
                time.sleep(1.5 * (attempt + 1))
                # keep the partial file so the next attempt resumes

    raise DownloadError(f"下载失败：{last_error}")
