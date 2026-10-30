"""ONNX Runtime backend for MeanVC2 streaming voice conversion.

Uses the community ONNX export of MeanVC2 (``kiarina/MeanVC2-ONNX``, graphs
Apache-2.0) instead of PyTorch.  The streaming bookkeeping is a faithful port of
the upstream ``VCRunner.process_chunk`` — the same sliding ASR window, BN
interpolation, ODE loop, DiT KV cache reuse and vocoder cross-fade — with every
network call replaced by one ONNX graph.

The public surface (``process_chunk`` / ``reset`` / ``warmup`` / ``CHUNK``)\nmatches what :mod:`app.backend.audio` expects from a session.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import numpy as np
import onnxruntime as ort

CHUNK = 2560          # 160 ms at 16 kHz
BN_WINDOW = 19
BN_STRIDE = 16
REQUIRED_CACHE = 8
ASR_OFFSET_INIT = 8
ASR_OFFSET_STEP = 4
CHUNK_SIZE = 12
BLOCK_SIZE = 4
VOCODER_OVERLAP = 2
WAV_OVERLAP = 160
WAV_PAD = (VOCODER_OVERLAP - 1) * 160 - WAV_OVERLAP

_DOWN = np.linspace(1, 0, WAV_OVERLAP, dtype=np.float32)
_UP = np.linspace(0, 1, WAV_OVERLAP, dtype=np.float32)


def interp_linear_align_corners(x: np.ndarray, size: int) -> np.ndarray:
    """``F.interpolate(mode='linear', align_corners=True)`` along axis 0."""
    n = x.shape[0]
    if n == 1:
        return np.repeat(x, size, axis=0)
    pos = np.arange(size, dtype=np.float32) * np.float32((n - 1) / (size - 1))
    lo = np.minimum(np.floor(pos).astype(np.int64), n - 2)
    w = (pos - lo.astype(np.float32))[:, None]
    return (x[lo] * (1 - w) + x[lo + 1] * w).astype(np.float32)


@dataclass
class OnnxBundle:
    """The five call-time graphs, loaded once and shared."""

    directory: Path
    sessions: dict
    threads: int = 1
    load_seconds: float = 0.0
    variant: str = "int8"
    version: str = ""

    @property
    def chunk_size(self) -> int:
        return CHUNK_SIZE

    @property
    def block_size(self) -> int:
        return BLOCK_SIZE

    @property
    def min_bn_len(self) -> int:
        return CHUNK_SIZE + BLOCK_SIZE


def _session(path: Path, threads: int) -> ort.InferenceSession:
    opts = ort.SessionOptions()
    opts.intra_op_num_threads = max(1, int(threads))
    opts.inter_op_num_threads = 1
    opts.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    opts.log_severity_level = 3
    return ort.InferenceSession(str(path), opts, providers=["CPUExecutionProvider"])


def resolve_graphs(directory: Path) -> tuple[dict[str, Path], str]:
    """Pick the best available variant: int8 > fp32 > int8-mixed."""
    wanted = ("fbank", "asr", "gtm", "dit", "vocos")
    plan: dict[str, Path] = {}
    variant_parts: list[str] = []
    for name in wanted:
        int8 = directory / f"{name}.int8.onnx"
        fp32 = directory / f"{name}.onnx"
        if name == "fbank":
            plan[name] = fp32              # only exported in fp32
        elif int8.exists():
            plan[name] = int8
            variant_parts.append(f"{name}:int8")
        elif fp32.exists():
            plan[name] = fp32
            variant_parts.append(f"{name}:fp32")
        else:
            raise FileNotFoundError(f"缺少 ONNX 图: {name}.onnx")
    return plan, ",".join(variant_parts)


def load_onnx_bundle(directory: Path, threads: int = 1, verbose: bool = True) -> OnnxBundle:
    started = time.perf_counter()
    plan, variant = resolve_graphs(directory)
    if verbose:
        print(f"[onnx] loading from {directory} ({variant}) ...", flush=True)
    sessions = {name: _session(path, threads) for name, path in plan.items()}
    bundle = OnnxBundle(
        directory=directory,
        sessions=sessions,
        threads=threads,
        load_seconds=time.perf_counter() - started,
        variant=variant,
    )
    if verbose:
        print(f"[onnx] ready in {bundle.load_seconds:.2f}s", flush=True)
    return bundle


class OnnxStreamVC:
    """One streaming conversion session bound to a speaker embedding."""

    CHUNK = CHUNK

    #: names the audio layer expects from any session implementation
    @property
    def chunk_size(self) -> int:
        return CHUNK_SIZE

    @property
    def block_size(self) -> int:
        return BLOCK_SIZE

    def __init__(self, bundle: OnnxBundle, spk_emb: np.ndarray,
                 steps: int = 2, seed: Optional[int] = None,
                 noise_fn: Optional[Callable[[int], np.ndarray]] = None):
        self.bundle = bundle
        self.s = bundle.sessions
        self.steps = int(steps)
        self.rng = np.random.default_rng(seed)
        self.noise_fn = noise_fn
        self.set_target(spk_emb)

    def set_target(self, spk_emb: np.ndarray) -> None:
        self.spk = np.asarray(spk_emb, dtype=np.float32).reshape(1, 256)
        self.k_mem, self.v_mem = self.s["gtm"].run(None, {"spks": self.spk})
        self.reset()

    def reset(self) -> None:
        self.samples_cache = np.zeros(0, np.float32)
        self.frame_cache: Optional[np.ndarray] = None
        self.encoder_output_cache: Optional[np.ndarray] = None
        self.asr_offset = ASR_OFFSET_INIT
        self.att_cache = np.zeros((6, 4, REQUIRED_CACHE, 128), np.float32)
        self.cnn_cache = np.zeros((6, 1, 256, 8), np.float32)
        self.kv = [np.zeros((1, 2, 0, 64), np.float32) for _ in range(8)]
        self.vc_offset = 0
        self.noise_cache: Optional[np.ndarray] = None
        self.vocoder_cache: Optional[np.ndarray] = None
        self.last_wav: Optional[np.ndarray] = None
        self.bn_buffer: Optional[np.ndarray] = None

    # -- ASR -------------------------------------------------------------
    def _encode_chunk(self, samples: np.ndarray) -> Optional[np.ndarray]:
        padded = (np.concatenate((self.samples_cache, samples))
                  if self.samples_cache.size else samples)
        if len(padded) < 400:
            self.samples_cache = padded
            return None

        n = 1 + (len(padded) - 400) // 160
        idx = np.arange(400)[None, :] + 160 * np.arange(n)[:, None]
        frames = (padded[idx] * np.float32(1 << 15)).astype(np.float32)

        fb = self.s["fbank"].run(None, {"frames": frames})[0]
        self.samples_cache = padded[160 * n:]
        if self.frame_cache is not None:
            fb = np.concatenate([self.frame_cache, fb], axis=0)
        if self.asr_offset >= 4000:
            self.asr_offset = max(REQUIRED_CACHE, self.asr_offset - 4000)

        bns = []
        i = 0
        while i + BN_WINDOW <= fb.shape[0]:
            out, self.att_cache, self.cnn_cache = self.s["asr"].run(None, {
                "xs": fb[None, i:i + BN_WINDOW],
                "offset": np.array(self.asr_offset, np.int64),
                "required_cache_size": np.array(REQUIRED_CACHE, np.int64),
                "att_cache": self.att_cache,
                "cnn_cache": self.cnn_cache,
            })
            bns.append(out[0])
            self.asr_offset += ASR_OFFSET_STEP
            i += BN_STRIDE
        self.frame_cache = fb[i:]

        if not bns:
            return None
        bn = np.concatenate(bns, axis=0)
        if self.encoder_output_cache is not None:
            bn = np.concatenate([self.encoder_output_cache, bn], axis=0)
        self.encoder_output_cache = bn[-1:]
        if bn.shape[0] < 2:
            return None
        return interp_linear_align_corners(bn, CHUNK_SIZE + BLOCK_SIZE + 1)[1:]

    # -- DiT -------------------------------------------------------------
    def _noise(self, n: int) -> np.ndarray:
        if self.noise_fn is not None:
            return self.noise_fn(n)
        return self.rng.standard_normal((1, n, 80), dtype=np.float32)

    def _vc_step(self, cond: np.ndarray) -> np.ndarray:
        dt = 1.0 / self.steps
        x = np.array(self._noise(cond.shape[0]), dtype=np.float32, copy=True)
        if self.noise_cache is not None:
            x[:, :BLOCK_SIZE, :] = self.noise_cache
        self.noise_cache = x[:, -BLOCK_SIZE:, :].copy()

        if self.vc_offset >= 4000:
            self.vc_offset = 0
            self.kv = [np.zeros((1, 2, 0, 64), np.float32) for _ in range(8)]

        feed = {
            "cond": cond[None],
            "spks": self.spk,
            "k_mem": self.k_mem,
            "v_mem": self.v_mem,
            "offset": np.array(self.vc_offset, np.int64),
        }
        for j in range(4):
            feed[f"k_cache{j}"] = self.kv[2 * j]
            feed[f"v_cache{j}"] = self.kv[2 * j + 1]

        for i in range(self.steps):
            t_val = 1.0 - i * dt
            r_val = max(0.0, t_val - dt)
            feed["x"] = x
            feed["t"] = np.array([t_val], np.float32)
            feed["r"] = np.array([r_val], np.float32)
            outs = self.s["dit"].run(None, feed)
            x = (x - np.float32(dt) * outs[0]).astype(np.float32)
            if i == self.steps - 1:
                self.kv = list(outs[1:])

        self.vc_offset += CHUNK_SIZE
        return np.ascontiguousarray(x[:, :CHUNK_SIZE, :].transpose(0, 2, 1))

    # -- vocoder ---------------------------------------------------------
    def _decode_mel(self, mel: np.ndarray) -> np.ndarray:
        if self.vocoder_cache is not None:
            mel = np.concatenate([self.vocoder_cache, mel], axis=-1)
        self.vocoder_cache = mel[:, :, -VOCODER_OVERLAP:]
        mel = ((mel + 1) / 2).astype(np.float32)
        wav = self.s["vocos"].run(None, {"mel": mel})[0].reshape(-1)

        if self.last_wav is not None:
            wav = wav[WAV_PAD:]
            front = wav[:WAV_OVERLAP]
            smooth = self.last_wav * _DOWN + front * _UP
            new = np.concatenate([smooth, wav[WAV_OVERLAP:-WAV_OVERLAP]])
        else:
            new = wav[:-WAV_OVERLAP]
        self.last_wav = wav[-WAV_OVERLAP:]
        return new.astype(np.float32)

    # -- public ----------------------------------------------------------
    def process_chunk(self, samples: np.ndarray) -> Optional[np.ndarray]:
        bn_new = self._encode_chunk(np.asarray(samples, dtype=np.float32))
        if bn_new is None:
            return None
        self.bn_buffer = (bn_new if self.bn_buffer is None
                          else np.concatenate([self.bn_buffer, bn_new], axis=0))

        need = CHUNK_SIZE + BLOCK_SIZE
        parts = []
        for _ in range(4):
            if self.bn_buffer.shape[0] < need:
                break
            cond = self.bn_buffer[:need]
            self.bn_buffer = self.bn_buffer[CHUNK_SIZE:]
            parts.append(self._decode_mel(self._vc_step(cond)))
        if not parts:
            return None
        return np.concatenate(parts)

    def warmup(self, n: int = 2) -> None:
        z = np.zeros(CHUNK, dtype=np.float32)
        for _ in range(n):
            try:
                self.process_chunk(z)
            except Exception:
                break
        self.reset()


class OnnxSpeakerEncoder:
    """Reference waveform -> 256-d speaker embedding (CC BY-SA 3.0 weights)."""

    _session: Optional[ort.InferenceSession] = None
    _path: Optional[Path] = None

    @classmethod
    def load(cls, path: Path) -> ort.InferenceSession:
        if cls._session is None or cls._path != path:
            opts = ort.SessionOptions()
            opts.intra_op_num_threads = 1
            opts.log_severity_level = 3
            cls._session = ort.InferenceSession(
                str(path), opts, providers=["CPUExecutionProvider"])
            cls._path = path
        return cls._session

    @classmethod
    def is_loaded(cls) -> bool:
        return cls._session is not None

    @classmethod
    def embedding(cls, wav_16k: np.ndarray, path: Path) -> np.ndarray:
        session = cls.load(path)
        x = np.asarray(wav_16k, dtype=np.float32).reshape(1, -1)
        name = session.get_inputs()[0].name
        out = session.run(None, {name: x})[0]
        return np.asarray(out, dtype=np.float32).reshape(1, -1)


