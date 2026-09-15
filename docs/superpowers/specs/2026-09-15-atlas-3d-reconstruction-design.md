# Atlas 3D Reconstruction — Design Specification

**Date:** 2026-09-15  
**Status:** Approved architecture; implementation gated by this written spec review  
**Repository:** `hosseinmashayekhi/siteview`

## 1. Mission

Atlas adds a completely independent 3D site-scan pipeline beside the existing SiteView capture/localization workflow.

Target experience:

`Insta360 X5 head-mounted capture -> offline reconstruction -> high-detail 3D site -> unrestricted free-walk viewer`

The manager must be able to leave the original capture trajectory, walk freely through reconstructed space, inspect nearby construction details, and fall back to original 360 evidence when reconstruction detail is uncertain.

## 2. Non-negotiable guardrails

1. **Do not modify or replace the working SiteView localization/capture pipeline during Atlas R&D.**
2. Atlas consumes copied/exported capture media through a separate interface.
3. No Atlas experiment is promoted into SiteView until it passes the benchmark gate in this document.
4. Do not switch reconstruction engines merely because a new model is interesting. A candidate must beat the current baseline on the fixed benchmark.
5. Preserve original 360 frames as source-of-truth evidence; reconstructed pixels/geometry are not treated as factual evidence when the source image is available.
6. Initial processing is offline on an NVIDIA GPU workstation/laptop. Mobile processing is explicitly out of scope.
7. The initial viewer is desktop/web and must support unrestricted navigation inside reconstructed geometry.
8. Public test data must be genuine indoor 360/equirectangular moving-camera material, as close as practical to an X5 head-mounted walk.
9. The production laptop path is `C:\3dcamera`; source lives in `siteview`, while media and generated artifacts live in the sibling `data` tree.
10. Normal operation is one-click and queue-driven. The laptop must not require a command sequence for every capture.
11. The laptop worker initiates outbound connections; Atlas must not require an inbound public port on the user's laptop.

## 3. Scope

### Phase A — Reproducible benchmark harness

Build an Atlas CLI and manifest format that can ingest a local 2:1 equirectangular MP4, validate it, extract deterministic keyframes, record hardware/runtime metadata, run reconstruction adapters, and produce a machine-readable benchmark report.

### Phase B — Geometry baseline

Use a spherical-capable photogrammetry path with OpenMVS as the dense/mesh baseline. The adapter boundary must keep third-party binaries outside Atlas source and record exact tool versions/commands.

Expected artifacts:
- camera poses
- sparse/dense point cloud where available
- textured mesh
- processing logs
- reconstruction manifest

### Phase C — Photorealistic detail baseline

Add a Gaussian Splatting adapter using a maintained open-source implementation that accepts the prepared 360 dataset (directly or through deterministic perspective projection). This path is for visual fidelity, not authoritative geometry.

Expected artifacts:
- trained splat representation
- camera transforms
- viewer-compatible export
- training metrics/logs

### Phase D — Viewer comparison

Create a standalone Atlas viewer with two modes:
- `Mesh`: geometry-first free walk
- `Splat`: appearance-first free walk

Viewer requirements:
- WASD/joystick-style unrestricted navigation
- mouse look
- adjustable movement speed
- switch Mesh/Splat without changing the original SiteView viewer
- show nearest original 360 capture/frame for evidence inspection
- expose reconstruction provenance and capture timestamp

### Phase E — One-click laptop worker and server handoff

Add an Atlas-only coordinator/worker boundary. The server owns the authoritative
queue; a long-running laptop worker claims jobs and performs all heavy
reconstruction on the local NVIDIA GPU.

Required behavior:
- one launcher performs setup checks, starts the worker, and keeps polling;
- claim tokens, a 300-second lease, and a 60-second heartbeat prevent two
  workers from owning the same live attempt;
- downloads use byte ranges and a `.part` file, then verify declared size and
  SHA-256 before processing;
- stage checkpoints make restart/resume deterministic;
- uploads are resumable and verified before the server marks a job complete;
- job/run IDs, input hash, pipeline version, commands, and artifact hashes make
  retries idempotent and auditable;
- credentials and signed transfer URLs never enter Git or run manifests;
- failed, cancelled, or lease-lost work stops safely and reports its last
  durable stage.

Initial implementation uses a fake/local coordinator in tests. A production
server adapter cannot be frozen until the actual server API and authentication
contract are available, but the worker state machine must not depend on a
particular server framework or object-storage vendor.

### Phase F — X5 validation

When the Insta360 X5 is available, repeat the exact benchmark with real X5 footage. No algorithmic integration into the production SiteView path occurs before this phase passes.

## 4. Capture assumptions

The operator may walk naturally and does not follow a rigid scanning path. However, reconstruction requires visual overlap and parallax.

Recommended production capture behavior:
- walk rather than stand and rotate in one location
- keep a generally steady walking pace
- revisit/loop through connected spaces when practical
- pass important details at close range if those details must be inspectable later
- avoid relying on surfaces never observed by the camera
- allow arbitrary turns and route shape; no fixed grid or Matterport-style station pattern is required

Atlas must never claim to recover unseen detail. Holes or low-confidence regions should remain identifiable rather than being silently hallucinated.

## 5. Architecture

```text
                    EXISTING SITEVIEW — UNCHANGED
X5 / capture  --------------------------------------------> current 360 + localization
      |
      | exported/copy media only
      v
+---------------------------- ATLAS -----------------------------+
| ingest -> validate -> keyframes/projections -> reconstruction  |
|                                         |                     |
|                         +---------------+---------------+     |
|                         |                               |     |
|                    Mesh adapter                    Splat adapter|
|                         |                               |     |
|                         +---------------+---------------+     |
|                                         v                     |
|                                  Atlas artifact manifest       |
|                                         |                     |
|                                         v                     |
|                                standalone 3D web viewer         |
+---------------------------------------------------------------+
```

Production transport is a separate control plane:

```text
Atlas server queue --signed/resumable transfer--> C:\3dcamera laptop worker
Atlas server queue <--heartbeat/status/results--- C:\3dcamera laptop worker
```

The transfer worker calls the same local pipeline used by the frozen benchmark;
it does not introduce a second reconstruction implementation.

### Module boundaries

- `atlas/manifest`: typed dataset/run/artifact schemas.
- `atlas/ingest`: ffprobe-based video inspection and deterministic input validation.
- `atlas/frames`: keyframe extraction and optional equirectangular-to-perspective projection.
- `atlas/adapters`: wrappers around external reconstruction engines; no engine code forked into the core package.
- `atlas/benchmark`: timing, VRAM/runtime metadata, artifact validation, score/report generation.
- `atlas/viewer`: standalone web viewer and provenance/evidence bridge.
- `scripts/atlas`: Windows-friendly setup/run entry points.
- `atlas/worker`: lease, heartbeat, resumable transfer, checkpoints, and local
  pipeline supervision behind a coordinator adapter.
- `atlas/coordinator`: Atlas-only server queue contract/reference service; no
  dependency on production SiteView localization internals.
- `tests/atlas`: unit and integration tests that do not require production SiteView state.
- `datasets/atlas`: manifests/download scripts only; large media and generated models stay out of Git.

## 6. Dataset strategy while X5 is unavailable

Use a fixed three-tier dataset ladder:

1. **Smoke dataset:** a short redistributable indoor 2:1 equirectangular clip for fast CI/local checks.
2. **Benchmark dataset:** a longer moving indoor 360 sequence with multiple surfaces, corners, occlusions, and revisits.
3. **X5 validation dataset:** user-captured X5 footage added later and kept outside public Git unless explicitly approved.

Each dataset gets a checked-in manifest containing source URL/reference, license, SHA-256, expected projection, duration/FPS/resolution, and benchmark purpose. Download scripts must verify the checksum. We do not commit third-party video binaries to the repository unless the license explicitly permits redistribution and doing so is useful.

## 7. Benchmark gate — prevents scope drift

Every reconstruction candidate is evaluated on the same frozen clip(s) and report schema.

Required measurements:
- pipeline success/failure
- total wall-clock processing time
- peak GPU memory where measurable
- number/percentage of registered keyframes
- output point/splat/triangle count
- output artifact size
- camera trajectory continuity
- visible holes/tears in required inspection regions
- near-detail inspection screenshots at fixed viewpoints
- free-walk ability away from the recorded camera path
- source-frame/evidence lookup correctness

### Promotion rule

A new engine/parameter set is promoted only when:
1. it completes the fixed benchmark reproducibly;
2. free-walk output opens in the Atlas viewer;
3. it does not regress required detail regions versus the current baseline without a documented compensating advantage;
4. all commands, versions, input hashes and output hashes are captured in the run manifest.

## 8. Quality target

Atlas optimizes first for **inspection usefulness**, not pretty demo imagery.

Priority order:
1. preserve visible construction detail;
2. coherent navigable space;
3. trustworthy linkage to original imagery;
4. geometric completeness;
5. processing speed.

Gaussian Splatting may win the visual-detail track while OpenMVS/Textured Mesh wins the geometry track. A hybrid viewer is acceptable and expected if each representation materially improves its track.

## 9. Security / repository hygiene

- No API keys, camera SDK secrets, private server credentials, or private X5 footage in Git.
- Generated frames, point clouds, meshes, splats and model checkpoints are ignored by default.
- External tools are installed/downloaded by versioned setup scripts or documented package steps, not copied as opaque binaries into source control.
- Every third-party dependency must have its license recorded before product integration.

## 10. Definition of done for the R&D milestone

The Atlas R&D milestone is complete when a clean Windows/NVIDIA machine can:

1. clone the Atlas branch;
2. run one setup path;
3. download/verify the approved public benchmark dataset;
4. execute the baseline reconstruction from one command;
5. generate a versioned run manifest and benchmark report;
6. open the result in the standalone free-walk viewer;
7. switch to/source the nearest original 360 evidence;
8. repeat the same workflow later with X5 media without changing the core pipeline contract.
9. start one Atlas launcher, receive a queued server capture, resume verified
   transfer/processing after interruption, and return verified results without
   per-job commands.

Only after this milestone and X5 validation do we connect Atlas to production
SiteView endpoints. The standalone Atlas coordinator/worker may be developed
and tested earlier without modifying the working localization path.
