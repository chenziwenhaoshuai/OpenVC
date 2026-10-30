"""End-to-end check of the ONNX backend inside the application."""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

from app.backend import engine_onnx, paths, voices  # noqa: E402
from app.backend.controller import CONTROLLER as C  # noqa: E402


def cos(a, b):
    a, b = np.asarray(a).reshape(-1), np.asarray(b).reshape(-1)
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-9))


print("backend:", C.backend)

t0 = time.perf_counter()
C.prepare()
for _ in range(200):
    if C._bundle is not None:
        break
    time.sleep(0.05)
print(f"prepare : {time.perf_counter()-t0:.2f}s  ready={C._bundle is not None} "
      f"variant={getattr(C._bundle, 'variant', '-')}")

# --- speaker encoder: ONNX vs the cached PyTorch embeddings ----------------
spk = paths.onnx_speaker()
if spk:
    bank = voices.VoiceBank()
    print("\n说话人嵌入一致性（ONNX int8 vs 已缓存的 torch 结果）:")
    for v in bank.list()[:4]:
        wav = voices.load_wav_16k(str(bank.dir / f"{v['id']}.wav"))
        cached = np.load(bank.dir / f"{v['id']}.emb.npy").astype(np.float32)
        fresh = engine_onnx.OnnxSpeakerEncoder.embedding(wav, spk)
        print(f"  {v['name'][:16]:18s} cos={cos(cached, fresh):.4f}")

# --- live conversion -------------------------------------------------------
devs = __import__("app.backend.audio", fromlist=["audio"]).list_devices()
audio = __import__("app.backend.audio", fromlist=["audio"])
cable = audio.find_default_cable_output()
C.start({"model": "120ms", "voice_id": C.voice_id,
         "input_index": devs["input"][0].index, "output_index": cable.index,
         "monitor_index": None, "monitor_enabled": False})
time.sleep(5)
st = C.state()
s = st["stats"]
print(f"\n运行    : running={st['running']} chunks={s['chunks']} rtf={s['rtf']:.3f} "
      f"latency={s['latency_ms']:.0f}ms underruns={s['underruns']} "
      f"proc={s['proc_ms']:.1f}ms")
C.stop()
print("RESULT  :", "PASS" if s["chunks"] > 10 and s["rtf"] < 0.6 else "FAIL")

