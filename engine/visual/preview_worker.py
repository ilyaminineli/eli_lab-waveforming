from __future__ import annotations

import threading
from dataclasses import replace
from queue import Empty, Full, Queue

from PySide6.QtCore import QObject, Signal

from engine.visual.assets import AssetCatalog
from engine.visual.compositor import PREVIEW_SIZE, VisualCompositor
from engine.visual.generators import GeneratorSettings
from engine.visual.layers import VisualLayer


class PreviewSignals(QObject):
    frame_ready = Signal(object, float, int)
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
        self._queue: Queue = Queue(maxsize=1)
        self._stop_event = threading.Event()
        self._state_lock = threading.Lock()
        self._reset_requested = True
        self._compositor: VisualCompositor | None = None

    def request_reset(self) -> None:
        with self._state_lock:
            self._reset_requested = True

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
    ) -> None:
        # Snapshot UI-owned state. Audio feature packets are immutable after emit;
        # large NumPy arrays are shared read-only to avoid duplicating RAM.
        request = {
            "packet": packet,
            "seconds": float(seconds),
            "layers": [VisualLayer.from_dict(layer.to_dict()) for layer in layers],
            "settings": replace(settings),
            "screen": str(screen),
            "feedback_enabled": bool(feedback_enabled),
            "feedback_amount": float(feedback_amount),
            "feedback_decay": float(feedback_decay),
            "feedback_shift": float(feedback_shift),
            "sequence": int(sequence),
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

    def run(self) -> None:
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
                    reset = self._reset_requested
                    self._reset_requested = False
                if reset:
                    self._compositor.reset_feedback()
                try:
                    image = self._compositor.render(
                        packet=request["packet"],
                        seconds=request["seconds"],
                        layers=request["layers"],
                        settings=request["settings"],
                        screen=request["screen"],
                        feedback_enabled=request["feedback_enabled"],
                        feedback_amount=request["feedback_amount"],
                        feedback_decay=request["feedback_decay"],
                        feedback_shift=request["feedback_shift"],
                    )
                    self.signals.frame_ready.emit(
                        image, request["seconds"], request["sequence"]
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
