"""Verify a packaged build end to end (run with the bundled interpreter)."""
from __future__ import annotations

import sys
import time

t0 = time.perf_counter()
from app.backend import audio  # noqa: E402
from app.backend.controller import CONTROLLER as C  # noqa: E402
print(f"import   : {time.perf_counter() - t0:.2f}s  backend={C.backend}")

t0 = time.perf_counter()
C.prepare()
for _ in range(400):
    if C._bundle is not None:
        break
    time.sleep(0.05)
print(f"model    : {time.perf_counter() - t0:.2f}s  ready={C._bundle is not None}")

devs = audio.list_devices()
cable = audio.find_default_cable_output()
print(f"devices  : {len(devs['input'])} in / {len(devs['output'])} out "
      f"| cable={cable.name if cable else 'MISSING'}")
print(f"voices   : {len(C.bank.list())}")

C.start({"model": "120ms", "voice_id": C.voice_id,
         "input_index": devs["input"][0].index, "output_index": cable.index,
         "monitor_index": None, "monitor_enabled": False})
time.sleep(5)
st = C.state()
s = st["stats"]
print(f"running  : {st['running']}  chunks={s['chunks']}  rtf={s['rtf']:.3f}  "
      f"latency={s['latency_ms']:.0f}ms  proc={s['proc_ms']:.1f}ms  underruns={s['underruns']}")
C.stop()
ok = s["chunks"] > 10 and s["rtf"] < 0.6
print("RESULT   :", "PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
