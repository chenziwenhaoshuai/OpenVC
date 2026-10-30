"""Application controller: owns the model, the voice bank and the live engine."""
from __future__ import annotations

import json
import threading
import time
import traceback
from collections import deque
from pathlib import Path
from typing import Optional

import numpy as np

from . import audio, denoise, downloader, engine_onnx, paths, voices



DEFAULT_SETTINGS = {
    "voice_id": None,
    "input_index": None,
    "output_index": None,
    "monitor_index": None,
    "monitor_enabled": True,
    "bypass": False,
    "denoise": False,
    "input_gain": 1.0,
    "output_gain": 1.0,
    "first_run_done": False,
}


class Controller:
    """Single source of truth for the HTTP layer and the SSE stream."""

    def __init__(self) -> None:
        paths.ensure_dirs()
        self.bank = voices.VoiceBank()
        # Prefer the ONNX Runtime backend whenever the graphs are present: it
        # needs no PyTorch, ships ~75 MB of models instead of 1.9 GB and runs
        # about 3.5x faster on CPU.
        self.backend = "onnx"

        saved = self._load_settings()
        # The ONNX export only ships the 120 ms model, so there is nothing to
        # select any more.
        self.model = "120ms"
        self.threads = 1
        self.chunk_samples = audio.CHUNK
        self.voice_id: Optional[str] = saved.get("voice_id")
        self.bypass = bool(saved.get("bypass", False))
        self.denoise = bool(saved.get("denoise", False))
        self.input_gain = float(saved.get("input_gain", 1.0))
        self.output_gain = float(saved.get("output_gain", 1.0))
        self.monitor_enabled = bool(saved.get("monitor_enabled", True))
        self.input_index = saved.get("input_index")
        self.output_index = saved.get("output_index")
        self.monitor_index = saved.get("monitor_index")
        self.first_run_done = bool(saved.get("first_run_done", False))

        self._bundle: object = None
        self._session = None
        self._engine: Optional[audio.RealtimeEngine] = None
        self._lock = threading.RLock()
        self._preparing = False
        self._prepare_error = ""
        self._logs: deque[str] = deque(maxlen=300)
        self._started_at = 0.0
        self._last_error = ""
        self._underrun_marks: deque[int] = deque(maxlen=40)
        self._cable_cache = False
        self._cable_checked_at = 0.0

        # Fall back to a usable voice if the saved one disappeared.
        if self.voice_id and self.bank.get(self.voice_id) is None:
            self.voice_id = None
        if self.voice_id is None:
            available = [v for v in self.bank.list() if v.get("has_embedding")]
            if available:
                self.voice_id = available[0]["id"]

    # -- settings --------------------------------------------------------
    def _load_settings(self) -> dict:
        try:
            if paths.SETTINGS_FILE.exists():
                data = json.loads(paths.SETTINGS_FILE.read_text("utf-8"))
                if isinstance(data, dict):
                    merged = dict(DEFAULT_SETTINGS)
                    merged.update(data)
                    return merged
        except Exception:
            pass
        return dict(DEFAULT_SETTINGS)

    def save_settings(self) -> None:
        payload = {
            "voice_id": self.voice_id,
            "input_index": self.input_index,
            "output_index": self.output_index,
            "monitor_index": self.monitor_index,
            "monitor_enabled": self.monitor_enabled,
            "denoise": self.denoise,
            "bypass": self.bypass,
            "input_gain": self.input_gain,
            "output_gain": self.output_gain,
            "first_run_done": self.first_run_done,
        }
        try:
            paths.SETTINGS_FILE.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), "utf-8")
        except Exception:
            pass

    # -- logging ---------------------------------------------------------
    def log(self, message: str) -> None:
        stamp = time.strftime("%H:%M:%S")
        line = f"[{stamp}] {message}"
        self._logs.append(line)
        print(line, flush=True)

    def logs(self) -> list[str]:
        return list(self._logs)

    # -- model -----------------------------------------------------------
    def prepare(self) -> None:
        with self._lock:
            if self._preparing or self._bundle is not None:
                return
            self._preparing = True
            self._prepare_error = ""
        threading.Thread(target=self._prepare_worker, name="prepare",
                         daemon=True).start()

    def _prepare_worker(self) -> None:
        try:
            missing = paths.missing_assets()
            if missing:
                raise FileNotFoundError(
                    "缺少模型文件: " + "、".join(missing) + "。请重新下载完整模型包")
            self.log("正在加载模型 ...")
            t0 = time.perf_counter()
            bundle = self._load_bundle()
            with self._lock:
                self._bundle = bundle
                self._session = None
            self.log(f"模型加载完成 ({time.perf_counter() - t0:.1f}s，"
                     f"{bundle.chunk_size * 10}ms 分块)")
        except Exception as exc:
            self._prepare_error = str(exc)
            self.log(f"模型加载失败: {exc}")
            traceback.print_exc()
        finally:
            with self._lock:
                self._preparing = False

    def _load_bundle(self):
        """Load the shared ONNX sessions (the only backend now)."""
        d = paths.onnx_dir()
        if d is None:
            raise FileNotFoundError(
                "缺少 ONNX 模型：请把 onnx/ 目录放到程序旁边（含 fbank/asr/gtm/dit/vocos）。")
        bundle = engine_onnx.load_onnx_bundle(d, threads=self.threads, verbose=False)
        spk = paths.onnx_speaker()
        if spk is not None:
            voices.set_embedder(
                lambda wav, p=spk: engine_onnx.OnnxSpeakerEncoder.embedding(wav, p))
        else:
            self.log("未附带说话人编码器，只能使用内置音色")
        return bundle

    # -- optional speaker encoder ---------------------------------------
    def speaker_ready(self) -> bool:
        """True when registering a new voice is possible."""
        return paths.onnx_speaker() is not None

    def download_speaker(self, on_progress=None, cancelled=None) -> str:
        """Fetch the speaker encoder. Blocking: call from a worker thread."""
        d = paths.onnx_dir()
        if d is None:
            raise RuntimeError("缺少 ONNX 模型目录")
        self.log("开始下载说话人编码器（约 369 MB，只需一次）…")
        path = downloader.download_speaker(d, on_progress=on_progress,
                                           cancelled=cancelled)
        voices.set_embedder(
            lambda wav, p=path: engine_onnx.OnnxSpeakerEncoder.embedding(wav, p))
        self.log("说话人编码器已就绪，可以添加新音色了")
        return str(path)

    def _make_session(self, emb):
        return engine_onnx.OnnxStreamVC(self._bundle, emb, steps=2)

    def _ensure_bundle(self) -> object:
        """Blocking load, used by preview generation."""
        with self._lock:
            if self._bundle is not None:
                return self._bundle
        try:
            bundle = self._load_bundle()
            with self._lock:
                self._bundle = bundle
            return bundle
        except Exception as exc:
            self._prepare_error = str(exc)
            return None

    # -- voices ----------------------------------------------------------
    def add_voice(self, wav_path: str, name: Optional[str] = None) -> dict:
        self.log(f"正在注册音色: {name or Path(wav_path).stem}")
        meta = self.bank.add(wav_path, name)
        self.log(f"音色已注册: {meta['name']} ({meta['duration']}s)")
        if not self._is_running():
            self.ensure_preview(meta["id"])
        return meta

    def select_voice(self, voice_id: str) -> None:
        if self.bank.get(voice_id) is None:
            raise KeyError(f"音色不存在: {voice_id}")
        was_running = self._is_running()
        if was_running:
            # Hot-swap: stop, rebuild the session with the new speaker, restart.
            self.stop()
        with self._lock:
            self.voice_id = voice_id
            self._session = None
        self.save_settings()
        self.log(f"目标音色: {voice_id}")
        if was_running:
            try:
                self.start({})
                self.log("已按新音色自动重启变声")
            except Exception as exc:
                self.log(f"按新音色重启失败: {exc}")

    def ensure_preview(self, voice_id: str) -> Optional[Path]:
        """Convert a fixed demo sentence with this voice and cache the result.

        This is what the user hears when they press 试听, so it must be the
        *converted* audio, not the raw reference.
        """
        out = self.bank.dir / f"{voice_id}.preview.wav"
        if out.exists():
            return out
        src = paths.PREVIEW_SOURCE
        if not src.exists():
            return None
        bundle = self._ensure_bundle()
        if bundle is None:
            return None
        try:
            emb = self.bank.embedding(voice_id)
            session = self._make_session(emb)
            session.warmup(1)
            wav = voices.load_wav_16k(src)
            chunk = session.CHUNK
            parts = []
            for pos in range(0, len(wav) - chunk + 1, chunk):
                piece = session.process_chunk(wav[pos:pos + chunk])
                if piece is not None:
                    parts.append(piece)
            if not parts:
                return None
            y = np.concatenate(parts)
            peak = float(np.abs(y).max()) if y.size else 0.0
            if peak > 0.98:
                y = y * (0.95 / peak)
            voices.write_wav(out, y)
            return out
        except Exception as exc:
            self.log(f"试听生成失败: {exc}")
            return None

    # -- self test -------------------------------------------------------
    def self_test(self) -> dict:
        with self._lock:
            if self._engine is not None and self._engine.is_running():
                return {"ok": False, "steps": [{
                    "name": "请先停止变声",
                    "ok": False,
                    "detail": "自检需要独占音频设备，请先点「停止」再检测。"}]}
        self.log("开始自检 ...")
        result = audio.self_test(self.input_index)
        for s in result["steps"]:
            self.log(f"  自检[{s['name']}] {'通过' if s['ok'] else '失败'} — {s['detail']}")
        return result

    # -- live engine -----------------------------------------------------
    def _is_running(self) -> bool:
        eng = self._engine
        return bool(eng is not None and eng.is_running())

    def start(self, config: dict) -> None:
        with self._lock:
            if self._engine is not None and self._engine.is_running():
                return

            if "voice_id" in config and config["voice_id"]:
                self.voice_id = config["voice_id"]
            if "input_index" in config:
                self.input_index = config["input_index"]
            if "output_index" in config:
                self.output_index = config["output_index"]
            if "monitor_index" in config:
                self.monitor_index = config["monitor_index"]
            self.bypass = bool(config.get("bypass", False))
            self.denoise = bool(config.get("denoise", self.denoise))
            self.input_gain = float(config.get("input_gain", 1.0))
            self.output_gain = float(config.get("output_gain", 1.0))
            self.monitor_enabled = bool(config.get("monitor_enabled", True))
            self.save_settings()

            if self._bundle is None:
                raise RuntimeError("模型尚未加载完成，请稍候再试。")

            devices = audio.list_devices()
            in_dev = audio.find_device(devices["input"], self.input_index) \
                if self.input_index is not None else devices["input"][0]
            out_dev = audio.find_device(devices["output"], self.output_index) \
                if self.output_index is not None else audio.find_default_cable_output()
            mon_dev = audio.find_device(devices["output"], self.monitor_index) \
                if (self.monitor_index is not None and self.monitor_enabled) else None

            if in_dev is None:
                raise RuntimeError("没有可用的输入设备")
            if out_dev is None:
                raise RuntimeError("没有可用的虚拟麦克风输出设备")

            session = None
            if not self.bypass and self.voice_id:
                emb = self.bank.embedding(self.voice_id)
                if self._session is None:
                    self._session = self._make_session(emb)
                    self._session.warmup(2)
                session = self._session
                session.reset()

            den = None
            if self.denoise:
                assets = denoise.find_assets(paths.ROOT)
                if assets is None:
                    self.log("降噪组件未安装，本次不启用降噪")
                else:
                    try:
                        den = denoise.Denoiser(*assets)
                        self.log("降噪已启用 (DeepFilterNet3)")
                    except Exception as exc:
                        self.log(f"降噪启动失败: {exc}")

            eng = audio.RealtimeEngine(
                input_device=in_dev,
                output_device=out_dev,
                monitor_device=mon_dev,
                session=session,
                denoiser=den,
                bypass=self.bypass or session is None,
                input_gain=self.input_gain,
                output_gain=self.output_gain,
            )
            eng.start()
            self._engine = eng
            self._started_at = time.time()
            self._last_error = ""
            self._underrun_marks.clear()
            self.log(f"已启动: 输入 {in_dev.name} → 输出 {out_dev.name}"
                     + (f" / 监听 {mon_dev.name}" if mon_dev else ""))

    def stop(self) -> None:
        with self._lock:
            if self._engine is not None:
                self._engine.stop()
                den = self._engine.denoiser
                self._engine = None
                if den is not None:
                    try:
                        den.close()
                    except Exception:
                        pass
                self.log("已停止")

    def engine(self) -> Optional[audio.RealtimeEngine]:
        return self._engine

    # -- state -----------------------------------------------------------
    def _warnings(self, stats: dict, cable_present: bool) -> list[dict]:
        out: list[dict] = []
        if not cable_present:
            out.append({"level": "error", "text": "未检测到虚拟声卡（VB-CABLE），会议软件里看不到本软件的声音。"})
        if self._prepare_error:
            out.append({"level": "error", "text": f"模型加载失败：{self._prepare_error}"})
        if stats.get("error"):
            out.append({"level": "error", "text": str(stats["error"])})
        elif self._last_error:
            out.append({"level": "error", "text": self._last_error})
        if stats.get("running"):
            if stats.get("rtf", 0) > 0.85:
                out.append({"level": "warn",
                            "text": f"CPU 占用偏高（实时率 {stats['rtf']:.2f}），可能出现卡顿，建议关闭其他程序。"})
            under = stats.get("underruns", 0)
            self._underrun_marks.append(under)
            if len(self._underrun_marks) >= 10:
                recent = self._underrun_marks[-1] - self._underrun_marks[0]
                if recent > 3:
                    out.append({"level": "warn", "text": "音频出现断续，请降低系统负载或换用 120ms 模型。"})
        return out

    def _cable_present(self) -> bool:
        """Device enumeration is not free; cache it — the tray UI polls at 10 Hz."""
        now = time.time()
        if now - self._cable_checked_at > 3.0:
            self._cable_cache = audio.find_default_cable_output() is not None
            self._cable_checked_at = now
        return self._cable_cache

    def state(self) -> dict:
        eng = self._engine
        stats = eng.stats.as_dict() if eng is not None else audio.Stats().as_dict()
        cable = self._cable_present()
        voice = self.bank.get(self.voice_id) if self.voice_id else None
        with self._lock:
            return {
                "ok": True,
                    "preparing": self._preparing,
                "prepare_error": self._prepare_error,
                "ready": self._bundle is not None,
                "running": self._is_running(),
                "voice_id": self.voice_id,
                "voice_name": (voice or {}).get("name"),
                "bypass": self.bypass,
                "input_index": self.input_index,
                "output_index": self.output_index,
                "monitor_index": self.monitor_index,
                "monitor_enabled": self.monitor_enabled,
            "denoise": self.denoise,
                "input_gain": self.input_gain,
                "output_gain": self.output_gain,
                "uptime": int(time.time() - self._started_at) if self._started_at else 0,
                "stats": stats,
                "cable_present": cable is not None,
                "first_run_done": self.first_run_done,
                "warnings": self._warnings(stats, cable is not None),
                "denoise": self.denoise,
                "denoise_available": denoise.find_assets(paths.ROOT) is not None,
                "speaker_model_loaded": engine_onnx.OnnxSpeakerEncoder.is_loaded(),
                "backend": self.backend,
                "logs": self.logs()[-40:],
            }


CONTROLLER = Controller()




