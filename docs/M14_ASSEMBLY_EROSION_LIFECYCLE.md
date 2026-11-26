# M14 — Deterministic assembly and erosion

**Status:** Implemented on `main` (renderer lifecycle slice)

## Contract

Assembly and erosion are derived render operations. They do not rewrite VisualScene objects, scene lifecycle state, layer snapshots, or cue routes. The compositor derives a deterministic fragment layout from the transition seed, transition ID, stable object/layer identity, and normalized progress. Sampling the same contract at the same progress always produces the same layout.

## Assembly

The incoming scene is rendered as a set of deterministic fragments. At progress 0 fragments are displaced and attenuated; as progress approaches 1 they converge to their source positions and recover their original alpha. At the endpoint the rendered frame is exactly the incoming scene render.

## Erosion

The outgoing scene is rendered as deterministic fragments. At progress 0 the fragments exactly reconstruct the source image; as progress approaches 1 fragments disperse and lose alpha. At the endpoint the scene content is fully eroded. The screen plate remains present.

## Determinism and safety

The seed is derived from the persisted transition seed, transition ID and stable layer ID using SHA-256. Each fragment's motion is calculated directly from its index and the eased progress; no global RNG, wall clock, mutable particle simulation or source-scene mutation is used. Fragment count is bounded to limit CPU cost. Zero progress and completed progress have explicit endpoint fast paths.

Assembly/erosion render only their relevant scene side. Raster and vector generators share the same fragment compositor after normal layer rendering, so all generator families are supported without inventing vector topology.

## Profiles

The scene-pair profile reports fragment count, lifecycle direction and progress for diagnosis. Existing path-map warnings and morph metrics remain unchanged.

## Validation

The CI smoke workflow verifies JSON round-trip of seed-bearing contracts, byte-identical repeated output at a fixed sample, unchanged source scene/layer snapshots, exact assembly and erosion endpoint behavior, and that lifecycle rendering keeps the screen plate while not rendering the hidden scene.

## Next

Temporal echo remains a separate transition-local history-buffer increment. It must be keyed by transition identity and sampled show time, reset on backward seeks/transition changes, and share the same deterministic live/offline replay contract. It should not reuse the compositor's optional global feedback buffer implicitly.
