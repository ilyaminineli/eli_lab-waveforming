from __future__ import annotations

from collections import deque
from dataclasses import fields
from typing import Any

import numpy as np

from .analyzer import FeatureFrame


SCALAR_FIELDS = (
    "rms", "peak", "centroid", "centroid_norm", "rolloff", "bandwidth",
    "flatness", "entropy", "flux", "zcr", "stereo_width", "crest",
)


def _aggregate_frames(frames: list[FeatureFrame]) -> FeatureFrame:
    if not frames:
        zeros = np.zeros(64, dtype=np.float32)
        return FeatureFrame(
            rms=0.0, peak=0.0, centroid=0.0, centroid_norm=0.0, rolloff=0.0,
            bandwidth=0.0, flatness=0.0, entropy=0.0, flux=0.0, zcr=0.0,
            stereo_width=0.0, crest=0.0, bands=zeros, spectrum=zeros.copy(),
        )
    values = {name: float(np.mean([getattr(frame, name) for frame in frames])) for name in SCALAR_FIELDS}
    band_size = min(len(frame.bands) for frame in frames)
    spectrum_size = min(len(frame.spectrum) for frame in frames)
    bands = np.mean(np.stack([frame.bands[:band_size] for frame in frames]), axis=0).astype(np.float32)
    spectrum = np.mean(
        np.stack([frame.spectrum[:spectrum_size] for frame in frames]), axis=0
    ).astype(np.float32)
    return FeatureFrame(**values, bands=bands, spectrum=spectrum)


class FeatureBus:
    """Builds compact, temporally-aware track/group/master features from analyzer frames."""

    def __init__(self, *, history_seconds: float = 3.0, analysis_rate: float = 24.0):
        self.history_length = max(8, int(history_seconds * analysis_rate))
        self._envelopes: dict[str, dict[str, float]] = {}
        self._onsets: dict[str, deque[float]] = {}
        self._previous_rms: dict[str, float] = {}
        self._last_event: dict[str, float] = {}

    @staticmethod
    def _raw(frame: FeatureFrame) -> dict[str, float | bool]:
        bands = np.asarray(frame.bands, dtype=np.float32)
        count = len(bands)
        low = float(np.mean(bands[:max(1, count // 4)])) if count else 0.0
        mid_start = max(1, count // 4)
        mid_end = max(mid_start + 1, (3 * count) // 4)
        mid = float(np.mean(bands[mid_start:mid_end])) if count else 0.0
        high = float(np.mean(bands[(3 * count) // 4:])) if count else 0.0
        energy = float(np.tanh(max(0.0, frame.rms) * 4.5))
        transient = float(np.clip(frame.flux * 32.0, 0.0, 1.0))
        return {
            "rms": float(frame.rms),
            "energy": energy,
            "low": low,
            "mid": mid,
            "high": high,
            "onset": transient,
            "spectral_flux": float(frame.flux),
            "centroid": float(frame.centroid_norm),
            "flatness": float(frame.flatness),
            "stereo_width": float(frame.stereo_width),
            "active": bool(frame.rms > 1e-4),
        }

    def _smooth(self, key: str, raw: dict[str, float | bool], position: float) -> dict[str, Any]:
        state = self._envelopes.setdefault(key, {})
        alpha = 0.34
        result: dict[str, Any] = {}
        for name, value in raw.items():
            if isinstance(value, bool):
                result[name] = value
            else:
                previous = state.get(name, float(value))
                smoothed = previous + alpha * (float(value) - previous)
                state[name] = smoothed
                result[name] = float(smoothed)

        history = self._onsets.setdefault(key, deque(maxlen=self.history_length))
        onset = float(raw["onset"])
        history.append(1.0 if onset >= 0.42 else 0.0)
        result["density"] = float(sum(history) / max(1, len(history)))

        previous_rms = self._previous_rms.get(key, float(raw["rms"]))
        novelty = abs(float(raw["rms"]) - previous_rms) * 4.0 + float(raw["spectral_flux"]) * 20.0
        result["novelty"] = float(np.clip(novelty, 0.0, 1.0))
        self._previous_rms[key] = float(raw["rms"])
        result["position"] = float(position)
        return result

    def reset(self) -> None:
        self._envelopes.clear()
        self._onsets.clear()
        self._previous_rms.clear()
        self._last_event.clear()

    def update(
        self,
        packet: dict | None,
        source_groups: dict[str, str] | None = None,
    ) -> dict:
        """Return the analyzer packet enriched with track, group, master and event data."""
        packet = dict(packet or {})
        frames: dict[str, FeatureFrame] = dict(packet.get("frames") or {})
        position = float(packet.get("position", 0.0))
        group_map = source_groups or {}

        track_features: dict[str, dict[str, Any]] = {}
        group_members: dict[str, list[FeatureFrame]] = {}
        events: list[dict[str, Any]] = []
        for source_id, frame in frames.items():
            values = self._smooth(source_id, self._raw(frame), position)
            track_features[source_id] = values
            group_id = group_map.get(source_id)
            if group_id:
                group_members.setdefault(group_id, []).append(frame)
            onset = float(values["onset"])
            previous_event = self._last_event.get(source_id, -1e9)
            if onset >= 0.60 and position - previous_event >= 0.075:
                events.append({
                    "kind": "transient",
                    "source_id": source_id,
                    "strength": onset,
                    "position": position,
                })
                self._last_event[source_id] = position

        group_frames: dict[str, FeatureFrame] = {}
        group_features: dict[str, dict[str, Any]] = {}
        for group_id, members in group_members.items():
            group_frames[group_id] = _aggregate_frames(members)
            member_values = [track_features[source_id] for source_id in frames
                             if group_map.get(source_id) == group_id]
            keys = ("rms", "energy", "low", "mid", "high", "onset",
                    "spectral_flux", "centroid", "flatness", "stereo_width",
                    "density", "novelty")
            group_features[group_id] = {
                key: float(np.mean([item[key] for item in member_values])) for key in keys
            }
            group_features[group_id]["active_tracks"] = sum(
                1 for item in member_values if item["active"]
            )
            group_features[group_id]["track_count"] = len(member_values)
            group_features[group_id]["position"] = position

        master_frame = _aggregate_frames(list(frames.values()))
        if track_features:
            names = ("rms", "energy", "low", "mid", "high", "onset",
                     "spectral_flux", "centroid", "flatness", "stereo_width",
                     "density", "novelty")
            master = {
                key: float(np.mean([item[key] for item in track_features.values()]))
                for key in names
            }
            master["active_tracks"] = sum(1 for item in track_features.values() if item["active"])
            master["track_count"] = len(track_features)
        else:
            master = {key: 0.0 for key in (
                "rms", "energy", "low", "mid", "high", "onset", "spectral_flux",
                "centroid", "flatness", "stereo_width", "density", "novelty",
            )}
            master.update(active_tracks=0, track_count=0)
        master["position"] = position
        packet.update({
            "track_features": track_features,
            "group_frames": group_frames,
            "group_features": group_features,
            "master_frame": master_frame,
            "master_features": master,
            "events": events,
        })
        return packet
