"""Real-time audio I/O — deliberately close to upstream ``run_rt.run_realtime``.

The upstream runtime opens a single duplex ``sd.Stream`` at 16 kHz with
``blocksize = 2560`` (160 ms) and runs the model inside the PortAudio callback.
We keep exactly that shape because it is the configuration the authors tested:
one callback, one clock, no ring buffers, no resampling, no drift correction.

What the app adds on top is only what a desktop tool needs:

* device enumeration that prefers the virtual cable and hides duplicates;
* an optional second output stream for local monitoring;
* per-chunk statistics (cost, underruns) for the UI;
* a ``bypass`` mode for A/B testing the routing.

The 16 kHz requirement is satisfied by opening through **MME**, which performs
sample-rate conversion in the Windows mapper for every device on this machine.
WASAPI shared mode refuses 16 kHz here (48 kHz mix format only), so MME is the
backend that keeps the upstream code path unchanged.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional

import numpy as np
import sounddevice as sd

TARGET_SR = 16000
CHUNK = 2560                      # 160 ms — same as runtime/run_rt.py

# MME first: it is the only backend here that accepts 16 kHz for every device.
# WASAPI is kept as a fallback (its 48 kHz-only mix format is handled by the
# device list, but a user may still pick one explicitly).
HOST_PREFERENCE = ("MME", "Windows WASAPI")


# ---------------------------------------------------------------------------
# Devices
# ---------------------------------------------------------------------------

@dataclass
class Device:
    index: int
    name: str
    hostapi: str
    in_channels: int
    out_channels: int
    default_rate: float

    def as_dict(self) -> dict:
        return {
            "index": self.index,
            "name": self.name,
            "hostapi": self.hostapi,
            "in_channels": self.in_channels,
            "out_channels": self.out_channels,
            "default_rate": self.default_rate,
        }


def _host_rank(name: str) -> int:
    try:
        return HOST_PREFERENCE.index(name)
    except ValueError:
        return len(HOST_PREFERENCE)


def _norm_name(name: str) -> str:
    """Collapse 'CABLE Input (VB-Audio Virtual Cable)' -> 'cable input'."""
    base = name.split("(")[0].strip().lower()
    return base or name.lower()


def list_devices() -> dict[str, list[Device]]:
    """Usable endpoints, de-duplicated across host APIs, MME first.

    Windows exposes the same physical device once per host API (MME, WASAPI,
    DirectSound, WDM-KS).  Showing all of them would be confusing, so each name
    appears once, represented by the preferred host API that accepts 16 kHz.
    """
    apis = sd.query_hostapis()
    inputs: list[Device] = []
    outputs: list[Device] = []
    for api in apis:
        if api["name"] not in HOST_PREFERENCE:
            continue
        for dev_index in api["devices"]:
            info = sd.query_devices(dev_index)
            dev = Device(
                index=dev_index,
                name=info["name"],
                hostapi=api["name"],
                in_channels=int(info["max_input_channels"]),
                out_channels=int(info["max_output_channels"]),
                default_rate=float(info["default_samplerate"]),
            )
            if dev.in_channels > 0:
                inputs.append(dev)
            if dev.out_channels > 0:
                outputs.append(dev)

    def rank(d: Device, prefer_cable: bool):
        return (_host_rank(d.hostapi),
                0 if (prefer_cable and "CABLE" in d.name) else 1,
                0 if (not prefer_cable and "CABLE" not in d.name) else 1,
                d.index)

    def dedupe(devs: list[Device], prefer_cable: bool) -> list[Device]:
        ordered = sorted(devs, key=lambda d: rank(d, prefer_cable))
        picked: dict[str, Device] = {}
        for d in ordered:
            key = _norm_name(d.name)
            if key not in picked:
                picked[key] = d
        # A generic mapper is only useful when nothing concrete exists.
        concrete = [d for k, d in picked.items() if "sound mapper" not in k]
        return concrete if concrete else list(picked.values())

    return {"input": dedupe(inputs, False), "output": dedupe(outputs, True)}


def find_device(devices: list[Device], index: int) -> Optional[Device]:
    for d in devices:
        if d.index == index:
            return d
    return None


def find_default_cable_output() -> Optional[Device]:
    for d in list_devices()["output"]:
        if "CABLE Input" in d.name:
            return d
    return None


def find_monitor_device() -> Optional[Device]:
    for d in list_devices()["output"]:
        if "CABLE" not in d.name:
            return d
    return None


# ---------------------------------------------------------------------------
# Self test — the "why can't they hear me" diagnostic
# ---------------------------------------------------------------------------

def self_test(mic_index: Optional[int] = None, duration: float = 1.2) -> dict:
    """Play a tone into the virtual cable and read it back.

    This exercises exactly the path a meeting app sees: our output goes to
    ``CABLE Input``, the meeting app records ``CABLE Output``.  If the tone
    comes back, the routing is correct and any remaining problem is on the
    meeting-app side.
    """
    import threading

    steps: list[dict] = []

    def step(name: str, ok: bool, detail: str) -> None:
        steps.append({"name": name, "ok": bool(ok), "detail": detail})

    cable_out = find_default_cable_output()
    capture = None
    for d in list_devices()["input"]:
        if "CABLE Output" in d.name:
            capture = d
            break

    step("检测虚拟声卡", cable_out is not None and capture is not None,
         f"输出 {cable_out.name}" if cable_out and capture else
         "未找到 VB-CABLE，请先安装虚拟声卡")

    if cable_out is None or capture is None:
        return {"ok": False, "steps": steps}

    # --- tone round trip ------------------------------------------------
    try:
        sr = TARGET_SR
        n = int(sr * duration)
        t = np.arange(n) / sr
        tone = (0.35 * np.sin(2 * np.pi * 1000 * t)).astype(np.float32)
        recorded = np.zeros(int(sr * (duration + 0.8)), dtype=np.float32)
        mark = threading.Event()

        def play() -> None:
            with sd.OutputStream(device=cable_out.index, samplerate=sr, channels=1,
                                 dtype="float32", blocksize=CHUNK, latency="high") as st:
                mark.set()
                for pos in range(0, len(tone), CHUNK):
                    st.write(tone[pos:pos + CHUNK])

        th = threading.Thread(target=play, daemon=True)
        th.start()
        mark.wait(timeout=2.0)
        with sd.InputStream(device=capture.index, samplerate=sr, channels=1,
                            dtype="float32", blocksize=CHUNK, latency="high") as st:
            got = 0
            while got < len(recorded):
                block, _ = st.read(min(CHUNK, len(recorded) - got))
                recorded[got:got + len(block)] = block[:, 0]
                got += len(block)
        th.join(timeout=2.0)

        peak = float(np.abs(recorded).max())
        spec = np.abs(np.fft.rfft(recorded * np.hanning(len(recorded))))
        freqs = np.fft.rfftfreq(len(recorded), 1 / sr)
        dominant = float(freqs[int(np.argmax(spec))])
        ok = peak > 0.05 and 900 <= dominant <= 1100
        step("虚拟麦克风回环", ok,
             f"峰值 {peak:.2f}，主频 {dominant:.0f} Hz" if ok else
             f"没有收到测试音（峰值 {peak:.3f}）—— VB-CABLE 可能被其他程序独占")
    except Exception as exc:
        step("虚拟麦克风回环", False, f"测试失败: {exc}")

    # --- microphone -----------------------------------------------------
    try:
        mic = find_device(list_devices()["input"], mic_index) if mic_index is not None else None
        if mic is None:
            for d in list_devices()["input"]:
                if "CABLE" not in d.name:
                    mic = d
                    break
        if mic is None:
            step("麦克风输入", False, "没有可用的麦克风")
        else:
            with sd.InputStream(device=mic.index, samplerate=TARGET_SR, channels=1,
                                dtype="float32", blocksize=CHUNK, latency="high") as st:
                level = 0.0
                for _ in range(6):
                    block, _ = st.read(CHUNK)
                    level = max(level, float(np.abs(block[:, 0]).max()))
            step("麦克风输入", True,
                 f"{mic.name}，当前电平 {level:.2f}"
                 + ("（很安静，说话时应该能看到电平跳动）" if level < 0.01 else ""))
    except Exception as exc:
        step("麦克风输入", False, f"打不开麦克风: {exc}")

    return {"ok": all(s["ok"] for s in steps), "steps": steps}


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

@dataclass
class Stats:
    running: bool = False
    proc_ms: float = 0.0
    proc_ms_max: float = 0.0
    rtf: float = 0.0
    out_buf_ms: float = 0.0
    latency_ms: float = 0.0
    underruns: int = 0
    overruns: int = 0
    chunks: int = 0
    in_peak: float = 0.0
    out_peak: float = 0.0
    in_rate: int = TARGET_SR
    out_rate: int = TARGET_SR
    error: str = ""

    def as_dict(self) -> dict:
        return {
            "running": self.running,
            "proc_ms": round(self.proc_ms, 1),
            "proc_ms_max": round(self.proc_ms_max, 1),
            "rtf": round(self.rtf, 3),
            "out_buf_ms": round(self.out_buf_ms, 1),
            "latency_ms": round(self.latency_ms, 1),
            "underruns": self.underruns,
            "overruns": self.overruns,
            "chunks": self.chunks,
            "in_peak": round(self.in_peak, 3),
            "out_peak": round(self.out_peak, 3),
            "in_rate": self.in_rate,
            "out_rate": self.out_rate,
            "error": self.error,
        }


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class RealtimeEngine:
    """Duplex stream: microphone -> model -> virtual microphone."""

    def __init__(self,
                 input_device: Device,
                 output_device: Device,
                 monitor_device: Optional[Device] = None,
                 session=None,
                 denoiser=None,
                 bypass: bool = False,
                 input_gain: float = 1.0,
                 output_gain: float = 1.0,
                 on_stats: Optional[Callable[[Stats], None]] = None,
                 on_output: Optional[Callable[[np.ndarray], None]] = None,
                 on_input: Optional[Callable[[np.ndarray], None]] = None):
        self.input_device = input_device
        self.output_device = output_device
        self.monitor_device = monitor_device
        self.session = session
        self.denoiser = denoiser
        # A denoiser alone (no VC session) is still a useful mode.
        self.bypass = bool(bypass or (session is None and denoiser is None))
        self.input_gain = float(input_gain)
        self.output_gain = float(output_gain)
        self.on_stats = on_stats
        self.on_output = on_output
        self.on_input = on_input

        self.stats = Stats()
        self._stream = None
        self._mon_stream = None
        self._stop = threading.Event()
        self._lock = threading.Lock()

        self._in_acc = np.zeros(0, dtype=np.float32)      # partial input chunk
        self._out_buf = np.zeros(0, dtype=np.float32)     # model output queue
        self._mon_buf = np.zeros(0, dtype=np.float32)
        self._ema = 0.0

    # -- lifecycle -------------------------------------------------------
    def start(self) -> None:
        if self.stats.running:
            return
        self._stop.clear()
        self._in_acc = np.zeros(0, dtype=np.float32)
        self._out_buf = np.zeros(0, dtype=np.float32)
        self._mon_buf = np.zeros(0, dtype=np.float32)
        if self.denoiser is not None:
            try:
                self.denoiser.reset()
            except Exception:
                pass

        self._stream = self._open_duplex()
        self._stream.start()

        if self.monitor_device is not None:
            try:
                self._mon_stream = sd.OutputStream(
                    device=self.monitor_device.index,
                    samplerate=TARGET_SR, channels=1, dtype="float32",
                    blocksize=CHUNK, latency="high",
                    callback=self._mon_callback)
                self._mon_stream.start()
            except Exception as exc:
                self.stats.error = f"监听设备不可用: {exc}"
                self._mon_stream = None

        self.stats.running = True
        threading.Thread(target=self._reporter, name="stats", daemon=True).start()

    def _open_duplex(self):
        last = None
        try:
            return sd.Stream(
                device=(self.input_device.index, self.output_device.index),
                samplerate=TARGET_SR, blocksize=CHUNK, channels=1,
                dtype="float32", latency="high", callback=self._callback)
        except Exception as exc:
            last = exc
        raise RuntimeError(
            f"无法以 16 kHz 打开音频流（输入 {self.input_device.name} / "
            f"输出 {self.output_device.name}）：{last}")

    def stop(self) -> None:
        self._stop.set()
        for stream in (self._stream, self._mon_stream):
            if stream is not None:
                try:
                    stream.stop()
                    stream.close()
                except Exception:
                    pass
        self._stream = None
        self._mon_stream = None
        self.stats.running = False

    # -- audio callback (upstream logic) ---------------------------------
    def _callback(self, indata, outdata, frames, time_info, status):
        if status:
            self.stats.overruns += 1

        samples = indata[:, 0].astype(np.float32)
        if self.input_gain != 1.0:
            samples = samples * self.input_gain
        self.stats.in_peak = float(np.max(np.abs(samples))) if samples.size else 0.0
        if self.on_input is not None:
            try:
                self.on_input(samples.copy())
            except Exception:
                pass

        if self.bypass and self.denoiser is None:
            out = samples.copy()
        else:
            # PortAudio normally hands us exactly CHUNK samples; guard anyway.
            if self._in_acc.size:
                samples = np.concatenate([self._in_acc, samples])
            if samples.size < CHUNK:
                self._in_acc = samples
                out = None
            else:
                chunk = samples[:CHUNK]
                self._in_acc = samples[CHUNK:]
                t0 = time.perf_counter()
                if self.denoiser is not None:
                    try:
                        chunk = self.denoiser.process(chunk)
                    except Exception as exc:
                        self.stats.error = f"降噪失败: {exc}"
                        self.denoiser = None       # carry on without it
                try:
                    out = chunk if self.bypass else self.session.process_chunk(chunk)
                except Exception as exc:
                    self.stats.error = f"推理失败: {exc}"
                    out = None
                dt = (time.perf_counter() - t0) * 1000.0
                self.stats.chunks += 1
                self._ema = dt if self._ema == 0 else self._ema * 0.8 + dt * 0.2
                self.stats.proc_ms = self._ema
                self.stats.proc_ms_max = max(self.stats.proc_ms_max, dt)
                self.stats.rtf = self._ema / (CHUNK / TARGET_SR * 1000.0)

        if out is not None and len(out):
            if self.on_output is not None:
                try:
                    self.on_output(np.asarray(out, dtype=np.float32).copy())
                except Exception:
                    pass
            self._out_buf = (np.concatenate([self._out_buf, out])
                             if self._out_buf.size else out)

        needed = len(outdata)
        if self._out_buf.size >= needed:
            block = self._out_buf[:needed]
            self._out_buf = self._out_buf[needed:]
        else:
            block = np.zeros(needed, dtype=np.float32)
            if self._out_buf.size:
                block[:self._out_buf.size] = self._out_buf
            self._out_buf = np.zeros(0, dtype=np.float32)
            if self.stats.chunks > 2:            # ignore start-up silence
                self.stats.underruns += 1

        if self.output_gain != 1.0:
            block = block * self.output_gain
        outdata[:, 0] = np.clip(block, -1.0, 1.0)
        self.stats.out_peak = float(np.max(np.abs(outdata[:, 0])))

        if self._mon_stream is not None:
            with self._lock:
                self._mon_buf = (np.concatenate([self._mon_buf, outdata[:, 0]])
                                 if self._mon_buf.size else outdata[:, 0].copy())
                if self._mon_buf.size > TARGET_SR:
                    self._mon_buf = self._mon_buf[-TARGET_SR:]

    def _mon_callback(self, outdata, frames, time_info, status):
        with self._lock:
            buf = self._mon_buf
            if buf.size >= frames:
                self._mon_buf = buf[frames:]
                outdata[:, 0] = buf[:frames]
            else:
                outdata[:, 0] = 0.0
                if buf.size:
                    outdata[:buf.size, 0] = buf
                self._mon_buf = np.zeros(0, dtype=np.float32)

    # -- reporting -------------------------------------------------------
    def _reporter(self) -> None:
        while not self._stop.is_set():
            time.sleep(0.2)
            buf_ms = self._out_buf.size / TARGET_SR * 1000.0
            model_ms = (self.session.chunk_size * 10.0
                        if self.session is not None else 0.0)
            self.stats.out_buf_ms = buf_ms
            self.stats.latency_ms = (CHUNK / TARGET_SR * 1000.0
                                     + self.stats.proc_ms
                                     + model_ms
                                     + buf_ms)
            if self.on_stats is not None:
                try:
                    self.on_stats(self.stats)
                except Exception:
                    pass

    def is_running(self) -> bool:
        return self.stats.running
