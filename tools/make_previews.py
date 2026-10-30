"""Generate the 试听 preview for every voice (converted, not the raw reference)."""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import torch  # noqa: E402
torch.set_num_threads(1)

from app.backend.controller import CONTROLLER as C  # noqa: E402


def main() -> int:
    C.prepare()
    for _ in range(120):
        if C._bundle is not None:
            break
        time.sleep(0.5)
    if C._bundle is None:
        print("model not ready:", C._prepare_error)
        return 1

    ok = 0
    for v in C.bank.list():
        t0 = time.perf_counter()
        path = C.ensure_preview(v["id"])
        took = time.perf_counter() - t0
        status = "OK" if path else "FAIL"
        print(f"  {v['name'][:20]:22s} {status:5s} {took:5.1f}s")
        if path:
            ok += 1
    print(f"previews: {ok}/{len(C.bank.list())}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

