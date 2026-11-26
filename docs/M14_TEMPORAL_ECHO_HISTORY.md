# M14 — Temporal Echo and transition-local history

**Status:** Implemented on `main`

## Purpose

`temporal_echo` is a scene-pair transition renderer. It first resolves the outgoing and incoming scene snapshots with the same pair weights used by dissolve, then lays timestamped historical versions of that resolved frame over the current frame.

The effect owns a dedicated `TemporalEchoHistoryBuffer`. It is independent of the compositor's ordinary `feedback_enabled`, `feedback_amount`, `feedback_decay` and `feedback_shift` controls. The echo buffer stores pre-echo source frames only, so an echoed output is never fed back into its own history.

## Authored settings

Settings live under `SceneTransition.metadata.temporal_echo` and are copied into `ScenePairRenderContract.metadata.transition_metadata`. They are persisted by project transitions and cue routes.

Example:

```json
{
  "temporal_echo": {
    "enabled": true,
    "history_seconds": 0.48,
    "max_samples": 8,
    "sample_interval_seconds": 0.125,
    "strength": 0.42,
    "decay": 0.72,
    "offset_x": 0.0,
    "offset_y": 0.0,
    "direction_x": 1.0,
    "direction_y": 0.0,
    "directional_persistence": 0.025,
    "history_scale": 0.5,
    "blend_mode": "Screen"
  }
}
```

| Setting | Meaning |
|---|---|
| `history_seconds` | Maximum age retained in the buffer |
| `max_samples` | Hard upper bound on stored frames (2–32) |
| `sample_interval_seconds` | Fixed cadence for capturing history frames and time unit used by the decay curve |
| `strength` | Total opacity budget distributed across available historical samples |
| `decay` | Per-sample-interval decay factor (0–0.99) |
| `offset_x`, `offset_y` | Additional normalized horizontal/vertical displacement at the oldest history age |
| `direction_x`, `direction_y` | Direction vector; normalized by the settings loader |
| `directional_persistence` | Normalized travel along the direction vector over the full history window |
| `history_scale` | Stored frame scale to control memory use (0.125–1.0) |
| `blend_mode` | Screen, Add, Lighten, Overlay or Normal |

The desktop scene panel exposes these controls when `TEMPORAL ECHO` is selected. The current values are stored when committing a manual transition or routing an XM cue.

## Sampling and composition

Each rendered transition sample is timestamped with the project/show-time passed to `render_scene_pair()`. The buffer captures at the configured timestamp interval (default 125 ms, aligned with the app's balanced 8 FPS preview profile); intervening render frames do not add redundant history samples. Before the current base frame is stored, the buffer:

1. removes samples older than `history_seconds`;
2. computes each remaining sample's age from timestamps, not wall-clock time or render-call count;
3. applies the decay curve and normalizes the combined opacity to `strength`;
4. resizes the stored frame to the current canvas, applies the time-scaled spatial/directional offset, and returns the historical overlays;
5. stores a downsampled copy of the current pre-echo base frame and trims the deque to `max_samples`.

This makes a fixed timestamped input sequence reproducible even when sampled out of order by an offline test harness. The preview worker and offline renderer use the same compositor method and the same history implementation. Exact frame-for-frame comparison requires the same timestamped input samples; the live preview's latest-frame queue can discard stale render requests under load, while offline export processes its requested frame cadence.

## Reset and isolation rules

History is cleared when:

- a different transition ID becomes active;
- show time moves backwards (seek/loop);
- the render dimensions change;
- preview or offline rendering leaves the active scene-pair path.

The explicit compositor method `reset_temporal_echo()` clears only this buffer. `reset_feedback()` continues to affect only ordinary compositor feedback, and therefore the two effects can be enabled, tuned or reset independently.

## Validation

The CI smoke workflow checks:

- multiple timestamped samples and the configured history bound;
- decay/strength settings and normalized direction vectors;
- deterministic byte-identical replay for identical timestamped input sequences;
- backward-seek, transition-ID and frame-size resets;
- contract JSON persistence of the temporal-echo configuration;
- byte-identical output from independent compositor instances given the same timestamped scene-pair input sequence;
- ordinary unimplemented M14 families still retain their explicit hold behavior.

## Performance considerations

History images are downsampled before storage (default 50%) and retained in a bounded deque. Echo overlays are composited after the outgoing/incoming scene pair is resolved and before optional ordinary feedback. This avoids keeping an unbounded sequence of full-resolution frames and avoids recursive echo accumulation.
