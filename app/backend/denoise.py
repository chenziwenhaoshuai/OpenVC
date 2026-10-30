"""DeepFilterNet3 noise suppression through the official libDF C API.

The reference implementation is PyTorch, but the upstream project also ships
``libDF`` — the same DSP and network, compiled to a native library, reading the
ONNX export through tract.  Calling that keeps this app PyTorch-free and avoids
re-implementing DeepFilterNet's streaming STFT / ERB / deep-filter logic, which
is exactly the kind of code that is easy to get subtly wrong.

DeepFilterNet3 works at 48 kHz full band; our pipeline runs at 16 kHz, so the
audio is upsampled, denoised frame by frame (480 samples = 10 ms) and
downsampled again.  Both resamplers keep state across chunks.
"""
from __future__ import annotations

import ctypes
from pathlib import Path
from typing import Optional

import numpy as np
import soxr

DFN_SR = 48000
PIPE_SR = 16000


class DenoiseError(RuntimeError):
    """The native library is missing or refused to start."""


class Denoiser:
    """Stateful streaming denoiser; feed it 16 kHz chunks, get 16 kHz back."""

    frame_length: int = 480

    def __init__(self, dll_path: Path, model_tar: Path,
                 atten_lim_db: float = 100.0):
        dll_path = Path(dll_path)
        model_tar = Path(model_tar)
        if not dll_path.exists():
            raise DenoiseError(f"缺少降噪库: {dll_path.name}")
        if not model_tar.exists():
            raise DenoiseError(f"缺少降噪模型: {model_tar.name}")

        try:
            lib = ctypes.CDLL(str(dll_path))
        except OSError as exc:
            raise DenoiseError(f"无法加载降噪库: {exc}") from exc

        lib.df_create.restype = ctypes.c_void_p
        lib.df_create.argtypes = [ctypes.c_char_p, ctypes.c_float, ctypes.c_char_p]
        lib.df_get_frame_length.restype = ctypes.c_size_t
        lib.df_get_frame_length.argtypes = [ctypes.c_void_p]
        lib.df_process_frame.restype = None
        lib.df_process_frame.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_float),
            ctypes.POINTER(ctypes.c_float),
        ]
        lib.df_set_atten_lim.restype = None
        lib.df_set_atten_lim.argtypes = [ctypes.c_void_p, ctypes.c_float]
        lib.df_free.restype = None
        lib.df_free.argtypes = [ctypes.c_void_p]

        self._lib = lib
        self._state = lib.df_create(str(model_tar).encode("utf-8"),
                                    ctypes.c_float(float(atten_lim_db)), None)
        if not self._state:
            raise DenoiseError("降噪模型初始化失败")
        self.frame_length = int(lib.df_get_frame_length(self._state)) or 480
        self.reset()

    # -- lifecycle -------------------------------------------------------
    def reset(self) -> None:
        """Drop every buffered sample so a new take starts clean."""
        self._up = soxr.ResampleStream(PIPE_SR, DFN_SR, 1, dtype="float32")
        self._down = soxr.ResampleStream(DFN_SR, PIPE_SR, 1, dtype="float32")
        self._in48 = np.zeros(0, np.float32)
        self._out48 = np.zeros(0, np.float32)
        self._out16 = np.zeros(0, np.float32)
        self._primed = False

    def close(self) -> None:
        if getattr(self, "_state", None):
            self._lib.df_free(self._state)
            self._state = None

    def __del__(self):                      # pragma: no cover - best effort
        try:
            self.close()
        except Exception:
            pass

    # -- processing ------------------------------------------------------
    def _frames(self, block48: np.ndarray) -> np.ndarray:
        """Run the network over whole 480-sample frames."""
        n = self.frame_length
        out = np.empty_like(block48)
        src = block48.ctypes.data_as(ctypes.POINTER(ctypes.c_float))
        dst = out.ctypes.data_as(ctypes.POINTER(ctypes.c_float))
        self._lib.df_process_frame(self._state, src, dst)
        return out

    def process(self, chunk: np.ndarray) -> np.ndarray:
        """Denoise one 16 kHz chunk; always returns the same number of samples."""
        chunk = np.ascontiguousarray(chunk, dtype=np.float32)
        want = chunk.size

        up = self._up.resample_chunk(chunk, last=False)
        self._in48 = np.concatenate([self._in48, up.astype(np.float32)])

        n = self.frame_length
        pieces = []
        while self._in48.size >= n:
            frame = np.ascontiguousarray(self._in48[:n])
            self._in48 = self._in48[n:]
            pieces.append(self._frames(frame))
            self._primed = True

        if pieces:
            self._out48 = np.concatenate([self._out48, np.concatenate(pieces)])
        if self._out48.size:
            down = self._down.resample_chunk(self._out48, last=False)
            self._out48 = np.zeros(0, np.float32)
            self._out16 = np.concatenate([self._out16, down.astype(np.float32)])

        if self._out16.size >= want:
            out = self._out16[:want]
            self._out16 = self._out16[want:]
            return out
        # Only during the first chunks, while the resamplers fill up.
        out = np.zeros(want, np.float32)
        have = self._out16.size
        if have:
            out[want - have:] = self._out16
            self._out16 = np.zeros(0, np.float32)
        return out


def find_assets(root: Path) -> Optional[tuple[Path, Path]]:
    """Return (library, model) when the denoiser is installed."""
    dll = None
    for rel in ("denoise/df.dll", "denoise/libdf.dll", "df.dll"):
        if (root / rel).exists():
            dll = root / rel
            break
    if dll is None:
        return None
    for rel in ("denoise/DeepFilterNet3_onnx.tar.gz", "DeepFilterNet3_onnx.tar.gz"):
        if (root / rel).exists():
            return dll, root / rel
    return None
