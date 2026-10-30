"""Target-voice bank: reference audio + cached speaker embeddings.

A "voice" is just a short reference recording of the person you want to sound
like.  MeanVC2 is zero-shot, so any clean 3–10 s clip works.

Layout on disk::

    voices/
        <id>.wav      # 16 kHz mono float32 reference
        <id>.emb.npy  # (1, 256) speaker embedding, computed once
        <id>.json     # {name, created, duration, ...}
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path
from typing import Optional

import numpy as np
import soundfile as sf

from . import paths

TARGET_SR = paths.TARGET_SR


# ---------------------------------------------------------------------------
# audio helpers
# ---------------------------------------------------------------------------

def load_wav_16k(path: str | Path, max_seconds: float = 12.0) -> np.ndarray:
    """Read any WAV/FLAC, mix to mono, resample to 16 kHz float32."""
    data, sr = sf.read(str(path), dtype="float32", always_2d=True)
    wav = data.mean(axis=1).astype(np.float32)

    if sr != TARGET_SR:
        import soxr
        wav = soxr.resample(wav, sr, TARGET_SR, quality="HQ").astype(np.float32)

    # Keep a representative window for long files.
    max_len = int(max_seconds * TARGET_SR)
    if len(wav) > max_len:
        start = _loudest_offset(wav, max_len)
        wav = wav[start:start + max_len]

    # Gentle level fix: only lift very quiet references, never clip a loud one.
    peak = float(np.max(np.abs(wav))) if wav.size else 0.0
    if peak > 0 and peak < 0.1:
        wav = wav * (0.3 / peak)
    return wav


def _loudest_offset(wav: np.ndarray, window: int) -> int:
    """Offset of the loudest ``window`` inside ``wav`` (25 % hop)."""
    hop = max(window // 4, 1)
    best_off, best_energy = 0, -1.0
    for off in range(0, max(len(wav) - window, 1), hop):
        seg = wav[off:off + window]
        e = float(np.dot(seg, seg))
        if e > best_energy:
            best_energy, best_off = e, off
    return best_off


def write_wav(path: Path, wav: np.ndarray, sr: int = TARGET_SR) -> None:
    """Write a 16 kHz mono clip, keeping the file small (PCM_16)."""
    sf.write(str(path), np.asarray(wav, dtype=np.float32), sr, subtype="PCM_16")


# ---------------------------------------------------------------------------
# Speaker embedder, injected by the controller so this module does not depend
# on the ONNX graphs directly.
# ---------------------------------------------------------------------------

_EMBEDDER = None


def set_embedder(fn) -> None:
    """Replace the speaker encoder (``None`` disables registration)."""
    global _EMBEDDER
    _EMBEDDER = fn


def _embed(wav: np.ndarray) -> np.ndarray:
    if _EMBEDDER is None:
        raise RuntimeError(
            "此版本不含说话人编码器，无法注册新音色；请使用内置音色。")
    return np.asarray(_EMBEDDER(wav), dtype=np.float32)


def _slug(name: str) -> str:
    s = re.sub(r"[^\w\u4e00-\u9fff-]+", "-", name.strip()).strip("-")
    if not s:
        s = "voice"
    return s[:40].lower()


# ---------------------------------------------------------------------------
# VoiceBank
# ---------------------------------------------------------------------------

class VoiceBank:
    def __init__(self, directory: Path | None = None):
        self.dir = Path(directory or paths.VOICES_DIR)
        self.dir.mkdir(parents=True, exist_ok=True)

    # -- queries ---------------------------------------------------------
    def list(self) -> list[dict]:
        out = []
        for meta_path in sorted(self.dir.glob("*.json")):
            vid = meta_path.stem
            try:
                meta = json.loads(meta_path.read_text("utf-8"))
            except Exception:
                continue
            meta["id"] = vid
            meta["has_embedding"] = (self.dir / f"{vid}.emb.npy").exists()
            meta["has_audio"] = (self.dir / f"{vid}.wav").exists()
            out.append(meta)
        return out

    def get(self, voice_id: str) -> Optional[dict]:
        for v in self.list():
            if v["id"] == voice_id:
                return v
        return None

    def embedding(self, voice_id: str) -> np.ndarray:
        """Cached embedding, computed on first use."""
        p = self.dir / f"{voice_id}.emb.npy"
        if p.exists():
            return np.load(p).astype(np.float32)

        meta = self.get(voice_id)
        if meta is None:
            raise KeyError(f"音色不存在: {voice_id}")
        wav_path = self.dir / f"{voice_id}.wav"
        if not wav_path.exists():
            raise FileNotFoundError(f"缺少参考音频: {wav_path}")
        wav = load_wav_16k(wav_path)
        emb = _embed(wav)
        np.save(p, emb)
        return emb

    # -- mutations -------------------------------------------------------
    def add(self, wav_path: str | Path, name: str | None = None) -> dict:
        wav_path = Path(wav_path)
        if not wav_path.exists():
            raise FileNotFoundError(f"找不到音频文件: {wav_path}")

        wav = load_wav_16k(wav_path)
        if wav.size < TARGET_SR:  # < 1 s
            raise ValueError("参考音频太短，请提供至少 2 秒的清晰语音。")

        digest = hashlib.sha256(wav.tobytes()).hexdigest()[:16]
        # Re-adding the same clip should return the existing voice, not a copy.
        for meta_path in self.dir.glob("*.json"):
            try:
                existing = json.loads(meta_path.read_text("utf-8"))
            except Exception:
                continue
            if existing.get("sha256") == digest:
                vid = meta_path.stem
                existing["id"] = vid
                existing["has_embedding"] = (self.dir / f"{vid}.emb.npy").exists()
                existing["has_audio"] = (self.dir / f"{vid}.wav").exists()
                return existing

        display = (name or wav_path.stem).strip()
        vid = _slug(display)
        # avoid collisions
        base, n = vid, 2
        while (self.dir / f"{vid}.json").exists():
            vid = f"{base}-{n}"
            n += 1

        sf.write(str(self.dir / f"{vid}.wav"), wav, TARGET_SR, subtype="PCM_16")

        emb = _embed(wav)
        np.save(self.dir / f"{vid}.emb.npy", emb)

        meta = {
            "name": display,
            "created": int(time.time()),
            "duration": round(len(wav) / TARGET_SR, 2),
            "source": str(wav_path),
            "sha256": digest,
        }
        (self.dir / f"{vid}.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), "utf-8")
        meta["id"] = vid
        meta["has_embedding"] = True
        meta["has_audio"] = True
        return meta

    def delete(self, voice_id: str) -> bool:
        hit = False
        for suffix in (".wav", ".emb.npy", ".json"):
            p = self.dir / f"{voice_id}{suffix}"
            if p.exists():
                p.unlink()
                hit = True
        return hit
