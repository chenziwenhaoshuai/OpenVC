"""Measure DeepFilterNet3 through the libDF C API.

Builds a noisy version of a clean recording, denoises it, and reports
SNR improvement plus per-chunk cost.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
import soundfile as sf  # noqa: E402

from app.backend import voices  # noqa: E402
from app.backend.denoise import Denoiser, find_assets  # noqa: E402

CHUNK = 2560


def best_lag(ref: np.ndarray, test: np.ndarray, max_lag: int = 4000) -> int:
    """Lag (in samples) that aligns `test` onto `ref`."""
    n = min(ref.size, test.size)
    a = ref[:n] - ref[:n].mean()
    b = test[:n] - test[:n].mean()
    size = 1 << int(np.ceil(np.log2(2 * n)))
    corr = np.fft.irfft(np.fft.rfft(b, size) * np.conj(np.fft.rfft(a, size)), size)
    corr = np.concatenate([corr[-max_lag:], corr[:max_lag + 1]])
    lags = np.concatenate([np.arange(-max_lag, 0), np.arange(0, max_lag + 1)])
    return int(lags[int(np.argmax(np.abs(corr)))])


def aligned_snr(ref: np.ndarray, test: np.ndarray) -> tuple:
    lag = best_lag(ref, test)
    if lag >= 0:
        t = test[lag:]
    else:
        t = np.concatenate([np.zeros(-lag, np.float32), test])
    n = min(ref.size, t.size)
    r, t = ref[:n], t[:n]
    gain = float(np.dot(r, t) / max(np.dot(t, t), 1e-12))
    t = t * gain
    noise = t - r
    return float(10 * np.log10(np.sum(r ** 2) / max(np.sum(noise ** 2), 1e-12))), lag, gain


def run(den: Denoiser, x: np.ndarray) -> np.ndarray:
    out = []
    for p in range(0, x.size - CHUNK + 1, CHUNK):
        out.append(den.process(x[p:p + CHUNK]))
    return np.concatenate(out)


def main() -> int:
    assets = find_assets(ROOT)
    print("assets  :", assets[0].name if assets else None)
    if assets is None:
        return 1

    t0 = time.perf_counter()
    den = Denoiser(*assets)
    print(f"init    : {time.perf_counter()-t0:.2f}s  frame={den.frame_length}")

    clean = voices.load_wav_16k(str(ROOT / "voices/demo-女声-2.wav"))
    clean = clean[: 16000 * 6]
    clean = clean / (np.abs(clean).max() + 1e-9) * 0.5

    rng = np.random.default_rng(7)
    for snr_in in (5, 10):
        noise = rng.standard_normal(clean.size).astype(np.float32)
        noise *= np.sqrt(np.mean(clean ** 2) / np.mean(noise ** 2) / (10 ** (snr_in / 10)))
        noisy = (clean + noise).astype(np.float32)

        den.reset()
        t0 = time.perf_counter()
        out = run(den, noisy)
        dt = time.perf_counter() - t0
        chunks = max(1, noisy.size // CHUNK)

        s_al, lag, gain = aligned_snr(clean, out)
        s_na, lag_n, _ = aligned_snr(clean, noisy)
        print(f"\n--- 输入 SNR {snr_in} dB ---")
        print(f"  带噪（对齐后）     : {s_na:6.2f} dB   lag={lag_n}")
        print(f"  降噪后（对齐后）   : {s_al:6.2f} dB   lag={lag}  增益={gain:.3f}")
        print(f"  改善               : {s_al - s_na:+5.2f} dB")
        print(f"  每块耗时           : {dt/chunks*1000:5.1f} ms / 160 ms  "
              f"(RTF {dt/chunks/(CHUNK/16000):.3f})")

    # pure noise: how much does it actually remove?
    noise_only = (rng.standard_normal(16000 * 3) * 0.05).astype(np.float32)
    den.reset()
    quiet = run(den, noise_only)
    print(f"\n纯噪声衰减         : "
          f"{20*np.log10(np.sqrt(np.mean(noise_only**2))/np.sqrt(np.mean(quiet**2))):5.1f} dB")

    sf.write(ROOT / "data/logs/denoise_out.wav", out, 16000)
    den.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


