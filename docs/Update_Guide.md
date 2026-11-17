# **WAVEFORMING — proposed next development direction**

After looking at the repository structure and its current documentation, I think the next stage should be a substantial evolution of WAVEFORMING rather than simply adding more generators.

**The central change I recommend is turning it from a relatively fixed audio-reactive composition tool into a multi-channel audiovisual instrument with an intelligent generative director.**

Your reference image already communicates an interesting visual identity: dark paper, technical registration marks, overlapping mathematical constructions, imperfect linework, restrained colours and a sense of analogue-meets-digital interference. I would preserve that identity.

[Pauric Freeman On Working with Sound, Image, Input Devices and Human Perception | Derivative](https://images.openai.com/static-rsc-4/zfLfHW_CG8gZVrgg5LynKHgPZDy5k4JFtXLh-rZAG1ARiGVPGfB6_FOZaiNLKANT5PioZ93O_Crbhtm064S262RyuLWy1jhZj-uyXmShWVWEzG2EXRB6hMhHRDR7U1W9GQkCCDbovWJ4zcUuv694F_-SWl1CWS0MNTfOjznM2Uk?purpose=inline)

[derivative.ca](https://derivative.ca/community-post/pauric-freeman-working-sound-image-input-devices-and-human-perception/65814?utm_source=chatgpt.com)

There are three interconnected problems to solve:

1. The audio engine needs to handle entire multitrack projects, not just a handful of sources.
2. The visual renderer needs a fundamentally more efficient rendering architecture.
3. The composition system needs to introduce movement, variation, development and unexpected events without sacrificing artistic control.

The important distinction: a better GPU renderer alone won't solve the creative limitations, and more audio channels alone won't make the compositions more interesting.

## **1. What the current implementation actually does**

The repository already contains a meaningful foundation, and I would not discard it.

The current implementation has:

| Area        | Current capability                                 | Main limitation                                         |
| ----------- | -------------------------------------------------- | ------------------------------------------------------- |
| Audio       | Shared playback clock, source controls             | In-memory PCM and per-source processing                 |
| Analysis    | RMS, FFT, spectral descriptors, correlation        | Limited temporal and musical intelligence               |
| Generators  | 10 mathematical families plus geometric generators | Not yet a sufficiently broad instrument library         |
| Compositor  | Layer stack, masks, blending, paper relief         | CPU image-space rendering                               |
| Composition | Auto Compose, Variate, Auto Variate                | Relatively coarse changes and limited temporal planning |
| Preview     | 600 × 450 at approximately 15 FPS                  | Performance ceiling and no adaptive renderer            |
| Export      | Project coordinate space at 1920 × 1440            | Full-resolution offline rendering not implemented       |

One particularly important detail: your README explicitly describes the compositor as CPU-rendered, with GPU rendering deferred to a future milestone. A 4060 cannot accelerate work that is still being performed primarily through CPU-side NumPy and Pillow operations.

The current code also shows that audio analysis is already separated from the audio output callback, which is good architectural groundwork.

### **The biggest architectural problems**

**A. Multichannel audio is not yet designed for your project scale.**

Your four projects contain:

- edn11: 12 stems
- ethixeat: 10 stems
- LenTOASEMA: 18 stems
- total fvckery: 10 stems

**Target project scale**

# **50 tracks**

Across four projects, based on the supplied file tree.

05101520edn11ethixeatLenTOASEMAtotal fvckery

The current playback engine has an in-memory buffer for each track and creates additional per-track analysis copies. It also performs individual source analysis and calculates pairwise source correlation.

The correlation calculation is especially worth reconsidering: a complete pairwise matrix scales approximately as \\(N^2\\). With 50 sources, there are 1,225 unique pairs.

You do not necessarily need every track correlated with every other track on every analysis update.

**B. The visual engine has too much work to do per frame.**

The existing compositor has caching and clipped layer operations, but many visual operations still involve full image buffers, NumPy conversions and Pillow image transformations.

The biggest architectural improvement is to separate:

- simulation updates;
- geometry generation;
- rasterisation;
- compositing;
- post-processing;
- display.

These operations do not all need to happen at the same frequency.

**C. Auto Variate is not really a generative director yet.**

The existing director can construct a composition and vary its parameters. However, a composition change every 12 seconds is not equivalent to understanding and developing a musical passage.

I would retain AUTO COMPOSE and VARIATE, but evolve them into an actual composition system.

## **2. Audio architecture: move from 7 to 50+ sources**

Recommended priority: M1

I would set the architecture target at 64 simultaneous stems, even though your immediate project requires 50. This gives enough room for additional tracks, bus channels and future projects.

### **A. Introduce project groups and audio buses**

Instead of treating all WAVs as an undifferentiated list, use a hierarchy:

**WAVEFORMING SESSION**

64-source target

**edn11**

12 individual stems

Drums

Synths

Bass

Voice

FX

**ethixeat**

10 individual stems

Drums

Bass

Pads

Leads

FX

**LenTOASEMA**

18 individual stems

Percussion

Drums

Synths

Noise

Other

**total fvckery**

10 individual stems

Drums

Leads

Pads

Clicks

FX

**MASTER BUS**

Playback and output analysis

These categories can be editable rather than hardcoded. The original directories should be retained as project-group metadata.

I would support:

- Individual tracks.
- Named groups.
- Group-level mute, solo and gain.
- Master mix.
- Group-based visual routing.
- Individual track-based visual routing.

### **B. Replace the current analysis strategy**

The existing analyzer calculates a large descriptor set for each enabled source. I would split this into three levels.

| Analysis level | Data                                           | Frequency              |
| -------------- | ---------------------------------------------- | ---------------------- |
| Transient      | Onsets, peak, envelope                         | Approximately 30–60 Hz |
| Spectral       | FFT, centroid, flux, frequency bands           | Approximately 15–30 Hz |
| Structural     | Density, activity, rhythmic patterns, sections | Approximately 2–5 Hz   |

These are proposed analysis rates, not measured performance results.

The most important missing feature is *persistent temporal understanding*.

For example, the visual system should recognise:

- A kick pattern becoming increasingly dense.
- A drum loop that suddenly drops out.
- A synth that gradually enters the arrangement.
- A texture that becomes noisier.
- A sustained sound that contrasts with increasingly fragmented percussion.

A single FFT frame cannot communicate these developments.

### **C. Stop calculating every possible correlation**

The current analysis worker calculates pairwise zero-lag correlation across enabled tracks. For a large project I would replace that with selective relationships:

- Track-to-group relationship.
- Group-to-group relationship.
- Track-to-master relationship.
- User-selected track pairs.
- Transient coincidence.
- Spectral similarity.

Most importantly, use a reduced feature representation for visual interaction.

The full analysis data can remain available for inspection, while a compact feature bus feeds the visual engine.

### **D. Add a feature bus**

I would introduce:

`engine/audio/feature_bus.py`

This provides an immutable, time-stamped snapshot of the musical state:

```
FeaturePacket(    timestamp=...,    transport_position=...,    tracks={...},    groups={...},    master={...},    events=[...],    structure={...},)
```

Each track should expose meaningful values such as:

```
{    "rms": 0.0,    "low": 0.0,    "mid": 0.0,    "high": 0.0,    "onset": 0.0,    "spectral_flux": 0.0,    "centroid": 0.0,    "density": 0.0,    "novelty": 0.0,    "active": True,}
```

The values above represent the proposed interface, not existing implementation.

The visual engine should never need to understand WAV files, playback buffers or audio callbacks. It receives feature snapshots and events.

This is an important decoupling.

### **E. Improve playback memory handling**

There are two practical choices.

**Option 1: In-memory mode**

Keep decoded audio in memory, but use compact buffers, shared memory views, preallocated mixing arrays and selective analysis.

**Option 2: Streamed mode**

Read audio from disk in blocks, using background readers and ring buffers. This reduces memory consumption for longer projects but introduces more buffering and synchronization complexity.

My recommendation is a hybrid:

- Preload shorter stems.
- Stream longer stems.
- Keep playback sample-accurate against one master clock.
- Resample asynchronously during project preparation.
- Never perform disk access or expensive memory allocation inside the audio callback.

The current callback also allocates a block per track, copies analysis snapshots and uses a lock while mixing. That is a particularly important performance target.

## **3. Visual rendering: make the RTX 4060 actually useful**

Recommended priority: M2

This is arguably the biggest technical change.

Your current renderer follows this approximate sequence:

**Current rendering path**

1

Audio feature packet

2

Python generator calculations

3

NumPy arrays

4

Pillow RGBA images

5

CPU blend operations

6

Paper relief processing

7

QImage conversion

8

Qt display

The proposed architecture:

**New rendering architecture**

**Audio Feature Bus**

Time-stamped snapshots and musical events

**Visual Simulation**

CPU-side state, geometry and event scheduling

**GPU RENDER GRAPH**

RTX 4060

Geometry shaders

Particle systems

Feedback buffers

Layer compositing

Displacement

Glitch processing

**OpenGL texture output**

Direct Qt OpenGL presentation

### **Recommended technology**

I would keep PySide6 as the application framework and investigate:

- `QOpenGLWidget` for the rendering surface.
- OpenGL 3.3 Core or newer.
- GLSL shaders for visual instruments and compositing.
- GPU-resident framebuffers for feedback.
- Instanced rendering for particles and repeated geometry.
- PBOs or asynchronous readback only when CPU access is actually required.

I would not introduce a second rendering framework unnecessarily.

Also, avoid treating CUDA as the default answer. Your visual operations are largely graphics operations, so OpenGL and GLSL are a more direct fit than moving every NumPy calculation to CUDA.

### **Performance targets**

I would establish separate targets for interactive preview and offline export.

| Metric               | Initial target        |
| -------------------- | --------------------- |
| Preview resolution   | 1280 × 960            |
| Preview frame rate   | 30 FPS                |
| Optional preview     | 1920 × 1440           |
| Offline export       | 1920 × 1440           |
| Audio sources        | 64                    |
| Active visual layers | 16–24                 |
| GPU feedback         | Supported             |
| Preview stability    | No audio interruption |

These are engineering targets to test, not promises about the machine's achievable performance.

**An important principle:** preview rendering must never block audio playback. If a frame takes longer than the available frame budget, the renderer should discard that outdated frame and render the newest state.

## **4. Make the visual system less stable and more expressive**

Recommended priority: M3

I think your current visual direction is aesthetically quite promising. The limitation is that the mathematical generators are currently closer to individual effects than fully developed visual instruments.

I would create a visual instrument library with distinct families.

[CEC — eContact! 19.2 — Vector Synthesis: An investigation into sound-modulated light by Derek Holzer](https://images.openai.com/static-rsc-4/VfC4444f_YHYfY0RATYnkNDWOat30DPTNHhjJV8g8Y99BLnJIDSggA80l3Q52vhCWmZrh33agBqcTznWQj0oPo9uuwQSrqXt-kqBwffeZQOShOJVLeD4uBCyyeWGAzyYCNsGg0m_Auxmu5sB-07uvaK4hLIJpkk9BOxujnDJGLs?purpose=inline)

**01 — Oscillatory Systems**

Lissajous figures, phase orbits, coupled oscillators, interference patterns and parametric trajectories.

Suitable for sustained synths, resonances and melodic textures.

[Abstract fractal. Fractal art background for creative design. Decoration for wallpaper desktop, poster, cover booklet, card. Psychedelic. Print for clothes, t-shirt.](https://images.openai.com/static-rsc-4/G_UdC6alUJdzp93jpd2heUco0Ke9NUVP3ko5agoXz3IP7PSKtgEFtdg0LrNn9MRXgq_6a7CfnqCP-kNzyTbjCV9dVHsLw44fMvPwDA60C9tChzOkDRBtANY2TdM2cAIcCAvD7HOEI7i63kdDUvXOtc_ii9XdSW66luQg-Nk3rGvxU6edJkC4KEH7-QKLrDDq?purpose=inline)

**02 — Recursive Systems**

Fractals, recursive polygons, branching structures, tessellations and cellular automata.

Suitable for evolving arrangements and layered patterns.

[dark space with moving particle simulations show speed and evolution](https://images.openai.com/static-rsc-4/_ohKj7ikZ4c6tYiNKyEABCyxXCzUMEernKaieP69eyqBlqaTtl3CqcT2xx5P2xYPe4ve8GVZ_37wji6riU-DSklv_6S_uAjpa6V-IJGXo46TCx6jfHv_r2n1M2FGnt2-zzhfrnc_gk6bwcLFMID_kuVRqE-48tW73kegZH-Vhyh5zg95MC6iBM1A0S253kRE?purpose=inline)

**03 — Dynamic Systems**

Vector fields, attractors, particle swarms, nonlinear motion and chaotic systems.

Suitable for bass movement, distorted material and complex textures.

[Glitch Abstract Black and White Background](https://images.openai.com/static-rsc-4/qG6aAliP3m2L2zf3yc6rOESaNBlSx4rjgNtm9POM7GCrT04--qwcGBrvxWSpRnARLJVmc74xRnUzfHXplzfB7cNtxDqMJZyRBcB2pX4lypQwjgeahpPal6EgBD4asNW1IjS7SRcfgd2aceiYM-H6MMCLaeH-bORSiD4Q_I7OJi9UcvqLe8x9VXIynY0bL48e?purpose=inline)

**04 — Signal Systems**

Feedback, displacement, frame fragmentation, image memory, scanlines and signal corruption.

Suitable for breaks, transients, clicks, glitches and sudden events.

[Brutalist Poster Design Graphics Made With Helvetica Typography Aesthetics And Geometric Forms](https://images.openai.com/static-rsc-4/GhMPGlAS-65Hum3zOYXkZ6gwOoY2AGuMiESbCOWsyx7j9nnSofMMPCLPLlml7go58H2TI8kqSZ5X14ooGUUWPTXUjOXYL1wjOPmwDJ57SnSJNCCbm7PCyYv_XQ8HmFFSua24LSo72ZkNDxeagln0tOnktco64XByHN5XZPIxgkJxyq_As-XZSMV6mHhC_Bte?purpose=inline)

**05 — Structural Systems**

Technical diagrams, grids, measurement marks, mathematical typography, wireframe construction and modular compositions.

Suitable for establishing the visual identity and providing compositional structure.

### **More important than adding instruments: make them behave differently**

For example:

A phase orbit should not simply grow when the synth gets louder.

Instead, it could:

- Drift according to phase relationships.
- Develop asymmetry when spectral flux rises.
- Break into separate trajectories on transient events.
- Gradually return to its original configuration during a quieter passage.

Likewise, a particle system should not simply receive audio amplitude as its speed.

Its vector field could change topology according to musical conditions, with transient events briefly changing particle attraction or repulsion.

This would create considerably more convincing audiovisual relationships.

## **5. Introduce an actual generative composition director**

Recommended priority: M4

This is the feature I would consider the creative centre of the new application.

I propose a system called **COMPOSITION DIRECTOR**.

Instead of automatically changing the entire composition every 12 seconds, it continuously evaluates the musical state and manages the visual composition over time.

### **A. Give visual layers compositional roles**

Each layer should have a role rather than simply a generator name.

| Role       | Function                                         |
| ---------- | ------------------------------------------------ |
| ANCHOR     | Establishes the main visual motif                |
| STRUCTURE  | Creates grids, frames and technical geometry     |
| MOTION     | Introduces movement and spatial change           |
| TEXTURE    | Adds particles, interference and granular detail |
| GLITCH     | Creates sudden disruptions                       |
| ACCENT     | Provides isolated high-impact events             |
| ATMOSPHERE | Adds subtle background activity                  |

For example, an arrangement might contain:

**COMPOSITION — 001**

**ANCHOR / PHASE ORBIT**

MASTER

Slow deformation controlled by melodic material

**STRUCTURE / GEOMETRIC PLATE**

Static technical framework

**MOTION / PARTICLE FIELD**

Micro-rhythmic motion driven by percussion

**TEXTURE / REACTION DIFFUSION**

Slow texture development

**GLITCH / FEEDBACK SYSTEM**

Triggered by transient density and spectral changes

### **B. Introduce a state machine for audiovisual composition**

I would create distinct visual states:

**I. DORMANT**

Minimal geometry, mostly static, negative space.

**II. EMERGENCE**

New geometry appears, motifs establish themselves.

**III. DEVELOPMENT**

Layer multiplication, transformations and interactions.

**IV. INSTABILITY**

Fracture, displacement, irregular events and visual density.

**V. RELEASE**

Visual collapse, fading structures, transition and silence.

Conceptual sequence. The director should also allow transitions between non-adjacent states.

The director should not blindly follow this exact sequence. It needs to determine what makes sense from the music, its history and the selected composition recipe.

### **C. Add controlled randomness**

I would introduce three separate types of variation:

**1. Micro-variation**

Small continuous changes in position, scale, geometry, distortion, density and phase.

**2. Event variation**

Unexpected mutations triggered by musical activity, including particle bursts, geometric fractures and temporary image corruption.

**3. Structural variation**

Changing the composition itself: introducing or removing layers, changing dominant motifs and altering spatial arrangements.

Give each a separate intensity control.

### **D. Introduce visual memory**

This is particularly important.

The current renderer already supports temporal feedback. I would develop it into a more sophisticated visual memory system.

For example:

- Previous geometric structures remain as ghost images.
- New geometry gradually overwrites old geometry.
- A transient briefly freezes or displaces the previous image.
- A recurring musical motif can restore a previously seen visual motif.
- A breakdown can expose older visual material.

This could create the impression that the composition has a visual memory rather than merely generating another unrelated frame.

## **6. Multichannel routing: one sound should not equal one visual layer**

With 50 stems, creating 50 independent visual layers would probably be the wrong approach.

It could become visually overcrowded and computationally expensive.

Instead, create a **visual modulation matrix**.

**MODULATION MATRIX — EXAMPLE**

| **Audio source** | **Visual destination**            |
| ---------------- | --------------------------------- |
| Final Kick       | Geometry fracture / scale impulse |
| Final Bass       | Attractor deformation             |
| Snare 1          | Horizontal displacement           |
| High Sticks      | Particle density                  |
| Drone Synth      | Slow geometric deformation        |
| Single Vox FX    | Typography / fragmentation        |
| Speech Sample    | Textual and structural events     |

This should be a configurable system rather than a fixed preset.

A particularly useful feature would be modulation chaining:

`Kick → Transient Detector → Event Router → Geometric Fracture`

Or:

`Drone Synth → Low-pass Envelope → Smoothing → Phase Deformation`

You could even have several different sources contribute to one parameter:

\\[ P(t)=w_1A(t)+w_2B(t)+w_3C(t) \\]

Where the source values can be independently smoothed, clamped, inverted, quantised or transformed.

### **Proposed control types**

- Direct mapping.
- Inverted mapping.
- Envelope follower.
- Threshold trigger.
- Sample-and-hold.
- Randomised modulation.
- Quantised modulation.
- Slew limiter.
- LFO.
- Event probability.

This would make WAVEFORMING substantially more interesting to operate.

## **7. More sophisticated rhythm and temporal understanding**

I would also introduce a separate temporal analysis system.

The goal is not necessarily to force the music into conventional BPM grids. IDM often deliberately disrupts those expectations.

Instead, use multiple levels of time:

| Temporal layer  | Purpose                          |
| --------------- | -------------------------------- |
| Sample-level    | Playback synchronisation         |
| Transient-level | Sudden visual impulses           |
| Micro-rhythm    | Stuttering and fragmented events |
| Beat-level      | Repeating patterns               |
| Bar-level       | Larger visual changes            |
| Section-level   | Composition development          |
| Long-term       | Recurring visual motifs          |

A beat detector should be optional, not the sole source of temporal understanding.

The system should also work with unusual time signatures, irregular sequences, free-time textures and samples that do not follow a conventional tempo.

I would support manual markers and section boundaries alongside automatic detection. This will be especially useful when preparing a fully composed MV.

## **8. Interface redesign**

I would avoid making the new interface a giant mixer with 50 rows visible simultaneously.

Instead, I would organise it around four working environments.

**01 / SESSION**

Audio

[The Faceless Dancer](https://images.openai.com/static-rsc-4/-7bdLZgSMpuk2qqePI2ar-vDPa2pAjcc0MPih2i-egLBcn5_DIO0IX5fUVPtWsW2zmsUdmHfDEF9qn0ajIt-XCOQRex_hHOb4F6xKmRTHHEHUMkoOtOjLQ3M_FpLtxMCXxHzB5aUg-v7MiPaDB5pZeB7G53_Sk1I7J0mjjmMGyI?purpose=inline)

[facelessdancer.com](https://facelessdancer.com/?utm_source=chatgpt.com)

Project browser, folder groups, stem import, waveform overview, playback, buses, source management and track-level analysis.

**02 / INSTRUMENTS**

Generation

[In Pictures: TouchDesigner Summit 2019 Montréal | Derivative](https://images.openai.com/static-rsc-4/M01nif-pLej0YhIr-9cn1lgvEHWes8rxmwlEBEbkzcq2Wb58NvzbXgTMvwk5Y9pcYG21xuuCiYO7-rWqZ0cFpRBbr4UymLhn7LQy2V1-0BG9-1jU9jhN5fIpbY2a9kjmkPF12Wh1g1_sF3x2A2-b19smZnHDYmsL9KO22tEIkEA?purpose=inline)

[derivative.ca](https://derivative.ca/community-post/pictures-touchdesigner-summit-2019-montr%C3%A9al/61151?utm_source=chatgpt.com)

Generator library, parameter editing, modulation matrix, event routing and simulation controls.

**03 / COMPOSITION**

Director

[NODUSmap — Graph Design Platform](https://images.openai.com/static-rsc-4/UZuZdEkhMsAUSBE7_m2iWv2BY7MH4Ja77iYHlaNTOXqLxe8WKA4YcYrrZaR2da5tmqusQvHb32SgNSkhiVYKC0A3dgJaqAc5Y7Rrh8hkqZSDQCcZCWpakSU8nFWFuXEro-5hqZbBu3uHqkT9j8Mf7O-0MNAi7Fi24N4LCyJ30kU?purpose=inline)

[nodusmap.com](https://nodusmap.com/?utm_source=chatgpt.com)

Layer roles, composition recipes, visual states, automatic variation and manual intervention.

**04 / PERFORMANCE**

Output

[HYPERFLUX — Audio-Reactive VJ Visualiser](https://images.openai.com/static-rsc-4/AebgO8ImGZ8tH2OENfu1EguUUfQS3SkM_c9bGuf8-F-LbGJNnwMkiVtiL8JWbNKMwtiWl3p0VBPX_J7OmFgz99ubCRToDtz_NgDCocCf8xdiCLEKXBXPfQaH4rD5npJYGxrWTDnpNtbA77-kQkNeRFoxIqY5RGxxGrs-0wHaiTE?purpose=inline)

[hyperfluxvj.com](https://www.hyperfluxvj.com/?utm_source=chatgpt.com)

Large visual output, playback cues, performance controls, transitions, recording and export.

### **A particularly useful addition: visual instruments as presets**

Every generator should have a recognisable default configuration.

For example:

- Lissajous / Phase Disruption
- Fractal / Recursive Decay
- Attractor / Chaotic Drift
- Cellular / Rhythmic Growth
- Feedback / Signal Corruption
- Geometry / Structural Instability

You should be able to load a preset, route a source to it, and immediately begin experimenting.

Presets should store both their parameters and modulation connections.

## **9. Proposed development roadmap**

I would divide the evolution into seven milestones, keeping the existing application functional throughout.

1. **M1 — Multichannel Foundation**

   First priority
   - 64-source architecture.
   - Folder-based project groups.
   - Group and master buses.
   - Improved audio callback.
   - Selective analysis.
   - Feature bus.
   - Project save/load.

   Acceptance: your complete 50-track project loads, plays and remains synchronised.
2. **M2 — GPU Rendering Core**
   - OpenGL renderer.
   - GLSL shader pipeline.
   - GPU framebuffers.
   - GPU layer blending.
   - Feedback and displacement.
   - Adaptive preview resolution.

   Acceptance: visual rendering no longer depends on the Pillow compositor for interactive operation.
3. **M3 — Visual Instrument Library**
   - Oscillatory systems.
   - Recursive systems.
   - Attractors and vector fields.
   - Signal and glitch instruments.
   - Structural geometry.
   - Individual instrument presets.

   Acceptance: several visually distinct instruments can run together with independent state.
4. **M4 — Composition Director**
   - Compositional roles.
   - Composition states.
   - Micro/event/structural variation.
   - Visual memory.
   - Intelligent variation.
   - Reproducible random seeds.

   Acceptance: compositions develop over time instead of only changing parameters.
5. **M5 — Modulation and Temporal Analysis**
   - Visual modulation matrix.
   - Event routing.
   - Rhythmic analysis.
   - Section detection.
   - Manual markers.
   - Automation and cue points.

   Acceptance: the same instrument can respond differently to multiple independent musical sources.
6. **M6 — Advanced Performance Environment**
   - Live overrides.
   - Visual scene transitions.
   - MIDI/OSC integration.
   - Performance recording.
   - Scene snapshots.
   - Director intensity controls.

   Acceptance: the system can operate as a live audiovisual instrument.
7. **M7 — Offline MV Production**
   - Timeline-based composition.
   - Deterministic frame rendering.
   - 1080p and 1440p export.
   - Audio/video muxing.
   - Render queue.
   - Reproducible project output.

   Acceptance: a complete audiovisual composition can be exported without relying on real-time recording.

## **10. Important engineering decisions**

I would establish some non-negotiable rules before implementation.

| Area              | Decision                                    |
| ----------------- | ------------------------------------------- |
| Audio playback    | Independent of visual rendering             |
| Audio callback    | No disk I/O, FFT or blocking operations     |
| Feature analysis  | Background, selective and multirate         |
| Visual simulation | Independent from rasterisation              |
| GPU rendering     | Persistent GPU-resident resources           |
| Preview           | Latest-frame rendering, no queue backlog    |
| Export            | Deterministic, offline rendering            |
| Composition       | Reproducible random seeds                   |
| Compatibility     | Existing projects and presets migrated      |
| Testing           | Performance benchmarks alongside unit tests |

I would also add a built-in diagnostics panel showing:

- Audio callback execution time.
- Audio underruns and dropouts.
- Analysis processing time.
- GPU frame time.
- CPU render time.
- Per-instrument simulation time.
- Active texture memory.
- Frame rate and dropped frames.

This will help us identify whether bottlenecks originate in audio processing, simulation, rendering or Qt presentation.

## **11. What I would implement first**

I would deliberately resist starting with the composition director or adding another 3D generator.

The first two milestones need to establish a reliable foundation.

My recommended order is:

**First: multichannel audio architecture.**

Your actual MV workflow depends on handling 50 stems. The current seven-source UI limit is explicitly hardcoded in `app/main_window.py`, so this is not just a theoretical scalability issue.

**Second: GPU renderer.**

Move the real-time visual path away from Pillow. Keep the existing generators operational initially through a compatibility layer, while introducing GPU-native instruments.

**Third: temporal intelligence.**

Develop musical events, feature history, visual state management and the composition director.

**Fourth: visual instrument expansion.**

Only after the rendering architecture is stable should we expand the generator library substantially.

## **12. Proposed next repository structure**

I would evolve the existing structure without rewriting everything into an entirely different application.

```
engine/
├── audio/
│   ├── playback.py
│   ├── source.py
│   ├── analyzer.py
│   ├── feature_bus.py
│   ├── event_detector.py
│   ├── temporal_analyzer.py
│   ├── mixer.py
│   └── streaming.py
│
├── project/
│   ├── session.py
│   ├── groups.py
│   ├── tracks.py
│   └── serialization.py
│
├── visual/
│   ├── instruments/
│   │   ├── oscillatory.py
│   │   ├── recursive.py
│   │   ├── dynamic.py
│   │   ├── signal.py
│   │   └── structural.py
│   │
│   ├── gpu/
│   │   ├── renderer.py
│   │   ├── framebuffer.py
│   │   ├── shader_manager.py
│   │   ├── texture_manager.py
│   │   ├── compositor.py
│   │   └── shaders/
│   │
│   ├── simulation.py
│   ├── modulation.py
│   ├── event_router.py
│   ├── composition_director.py
│   ├── composition_state.py
│   ├── visual_memory.py
│   └── layers.py
│
├── timeline/
│   ├── markers.py
│   ├── automation.py
│   └── cues.py
│
└── export/
    ├── offline_renderer.py
    └── video_export.py
```

The existing `engine/visual/generators.py` should initially remain available as the compatibility implementation while its generators are migrated individually.

## **13. A few decisions to settle before the first implementation**

I have enough information to propose the architecture, but there is one important distinction concerning how you want to use WAVEFORMING: whether it is primarily a tool for generating finished MVs, a live instrument, or both.

My recommendation is both, with offline MV production as the primary design target.

**WAVEFORMING — development configuration**

**1. Primary workflow**

Offline MV production first

Live audiovisual instrument first

Both, sharing the same composition engine

**2. Rendering backend**

OpenGL / GLSL (recommended)

OpenGL plus CPU compatibility fallback

Investigate other GPU frameworks

**3. Audio storage**

Preloaded audio in memory

Stream all stems from disk

Hybrid, automatic memory/streaming selection

**4. Composition director**

Manual composition only

Semi-automatic with adjustable creative control

Highly autonomous generative composition

**5. Primary export resolution**

1920 × 1080

2560 × 1440

3840 × 2160

Use these development decisions&#x20;

**My overall vision:** WAVEFORMING should feel less like a conventional audio visualiser and more like a programmable mathematical instrument that happens to understand music. It should preserve the visual personality you've established while becoming capable of producing genuinely unpredictable, complex and coherent IDM audiovisual compositions.