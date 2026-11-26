from __future__ import annotations

import os
import threading
from dataclasses import replace
from queue import Empty, Full, Queue

from PySide6.QtCore import QObject, Signal

from engine.visual.assets import AssetCatalog
from engine.visual.compositor import PREVIEW_SIZE, VisualCompositor
from engine.visual.generators import GeneratorSettings
from engine.visual.layers import VisualLayer


def is_newer_preview_frame(sequence: int, displayed_sequence: int) -> bool:
    """Accept the next completed frame even when newer requests are still queued."""
    return int(sequence) > int(displayed_sequence)


class PreviewSignals(QObject):
    frame_ready = Signal(object, float, int)
    profile_ready = Signal(object)
    render_error = Signal(str)


class PreviewRenderWorker(threading.Thread):
    """Single-owner compositor thread with a one-item latest-frame queue.

    UI requests never wait for a render. When the renderer falls behind, stale
    pending requests are replaced with the newest playhead/layer snapshot.
    """

    def __init__(self, assets: AssetCatalog, render_size: tuple[int, int] = PREVIEW_SIZE):
        super().__init__(name="WaveformingPreview", daemon=True)
        self.signals = PreviewSignals()
        self._assets = assets
        self._render_size = tuple(render_size)
        self._requested_render_size = self._render_size
        self._queue: Queue = Queue(maxsize=1)
        self._stop_event = threading.Event()
        self._state_lock = threading.Lock()
        self._reset_feedback_requested = True
        self._reset_generators_requested = False
        self._compositor: VisualCompositor | None = None

    @property
    def render_size(self) -> tuple[int, int]:
        with self._state_lock:
            return self._requested_render_size

    def set_render_size(self, size: tuple[int, int]) -> None:
        """Switch preview resolution on the worker thread at the next frame boundary."""
        width, height = max(1, int(size[0])), max(1, int(size[1]))
        with self._state_lock:
            self._requested_render_size = (width, height)
            self._reset_feedback_requested = True

    def request_reset(self, *, reset_generators: bool = False) -> None:
        """Clear temporal feedback; retain costly simulation state unless requested."""
        with self._state_lock:
            self._reset_feedback_requested = True
            if reset_generators:
                self._reset_generators_requested = True

    def submit(
            self,
            packet: dict | None,
            seconds: float,
            layers: list[VisualLayer],
            settings: GeneratorSettings,
            screen: str,
            feedback_enabled: bool,
            feedback_amount: float,
            feedback_decay: float,
            feedback_shift: float,
            sequence: int,
            gpu_composite: bool = False,
    ) -> None:
        # Snapshot UI-owned state. Audio feature packets are immutable after emit;
        # large NumPy arrays are shared read-only to avoid duplicating RAM.
        request = {
            "packet": packet,
            # Keep the audio playhead and visual animation clock independent.
            "audio_seconds": float(seconds),
            "seconds": float(seconds),
            "layers": [VisualLayer.from_dict(layer.to_dict()) for layer in layers],
            "settings": replace(settings),
            "screen": str(screen),
            "feedback_enabled": bool(feedback_enabled),
            "feedback_amount": float(feedback_amount),
            "feedback_decay": float(feedback_decay),
            "feedback_shift": float(feedback_shift),
            "sequence": int(sequence),
            "gpu_composite": bool(gpu_composite),
        }
        try:
            self._queue.put_nowait(request)
        except Full:
            try:
                self._queue.get_nowait()
            except Empty:
                pass
            try:
                self._queue.put_nowait(request)
            except Full:
                pass

    @staticmethod
    def _lower_thread_priority() -> None:
        """Keep preview work below the Qt and real-time audio threads."""
        try:
            if os.name == "nt":
                import ctypes
                kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
                kernel32.GetCurrentThread.restype = ctypes.c_void_p
                kernel32.SetThreadPriority.argtypes = (ctypes.c_void_p, ctypes.c_int)
                kernel32.SetThreadPriority.restype = ctypes.c_int
                kernel32.SetThreadPriority(kernel32.GetCurrentThread(), -1)  # BELOW_NORMAL
            else:
                os.nice(5)
        except Exception:
            # Priority changes are best-effort and must never prevent rendering.
            pass

    def run(self) -> None:
        self._lower_thread_priority()
        try:
            self._compositor = VisualCompositor(self._assets, render_size=self._render_size)
            while not self._stop_event.is_set():
                try:
                    request = self._queue.get(timeout=0.2)
                except Empty:
                    continue
                if request is None:
                    break
                with self._state_lock:
                    reset_feedback = self._reset_feedback_requested
                    reset_generators = self._reset_generators_requested
                    requested_size = self._requested_render_size
                    self._reset_feedback_requested = False
                    self._reset_generators_requested = False
                if requested_size != self._render_size:
                    # Preserve independent generator simulation state when only
                    # preview quality changes; the compositor's dimensions are
                    # replaced, but stateful generator instances are retained.
                    old_compositor = self._compositor
                    self._render_size = requested_size
                    self._compositor = VisualCompositor(
                        self._assets, render_size=self._render_size
                    )
                    if old_compositor is not None:
                        self._compositor.generators = old_compositor.generators
                        self._compositor.generators.resize_states(self._render_size)
                elif reset_generators:
                    self._compositor.reset_feedback()
                elif reset_feedback:
                    self._compositor.reset_feedback(preserve_generators=True)
                if self._compositor is not None and not reset_generators:
                    self._compositor.generators.retain_layers(
                        {layer.layer_id: layer.generator for layer in request["layers"] if layer.visible}
                    )
                try:
                    render_args = {
                        "packet": request["packet"],
                        "seconds": request["seconds"],
                        "layers": request["layers"],
                        "settings": request["settings"],
                        "screen": request["screen"],
                    }
                    if request["gpu_composite"] and not request["feedback_enabled"]:
                        image = self._compositor.render_scene(
                            **render_args,
                            gpu_native=True,
                            include_guide=True,
                        )
                    else:
                        image = self._compositor.render_cpu_frame(
                            **render_args,
                            feedback_enabled=request["feedback_enabled"],
                            feedback_amount=request["feedback_amount"],
                            feedback_decay=request["feedback_decay"],
                            feedback_shift=request["feedback_shift"],
                        )
                    if self._compositor is not None:
                        self.signals.profile_ready.emit(dict(self._compositor.last_profile))
                    self.signals.frame_ready.emit(
                        image, request["audio_seconds"], request["sequence"]
                    )
                except Exception as exc:
                    self.signals.render_error.emit(f"Preview render failed: {exc}")
        except Exception as exc:
            self.signals.render_error.emit(f"Preview worker could not start: {exc}")

    def close(self, timeout: float = 2.0) -> None:
        self._stop_event.set()
        try:
            self._queue.put_nowait(None)
        except Full:
            try:
                self._queue.get_nowait()
            except Empty:
                pass
            try:
                self._queue.put_nowait(None)
            except Full:
                pass
        if self.is_alive():
            self.join(timeout=max(0.1, float(timeout)))
