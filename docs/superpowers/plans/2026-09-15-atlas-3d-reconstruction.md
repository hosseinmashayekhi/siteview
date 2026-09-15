# Atlas 3D Reconstruction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Build a standalone Windows/NVIDIA pipeline that converts moving 2:1 360 video into an inspection-oriented 3D environment with Mesh and Gaussian-Splat outputs, unrestricted free-walk, and links back to original 360 evidence.

**Architecture:** Atlas stays isolated from the working Android SiteView pipeline. Python owns validation, deterministic frame preparation, reconstruction adapters, provenance and benchmarking. OpenMVS is the geometry baseline; a maintained open-source Gaussian Splatting implementation is the visual-detail baseline. A standalone web viewer consumes Atlas artifacts only.

**Tech Stack:** Python 3.11+, pytest, Pydantic, Typer, ffmpeg/ffprobe, NumPy/OpenCV, OpenMVS external CLI, COLMAP where required, NVIDIA CUDA, Three.js.

**Spec:** `docs/superpowers/specs/2026-09-15-atlas-3d-reconstruction-design.md`

## Global Constraints

- Existing SiteView capture/localization remains unchanged during Atlas R&D.
- Atlas receives copied/exported media only.
- Processing is initially offline on a Windows NVIDIA workstation/laptop.
- Primary input contract: moving-camera 2:1 equirectangular video.
- Original 360 imagery remains source-of-truth evidence.
- Generated videos, frames, meshes, splats and checkpoints never enter Git.
- Every run records input hashes, commands, tool versions, output hashes, timing and available GPU metadata.
- New reconstruction engines cannot replace the baseline without passing the frozen benchmark gate.
- Laptop execution root is `C:\3dcamera`, with the Git checkout and generated data in separate sibling trees.
- Final operation is one-click and server-queue driven; heavy computation stays on the RTX laptop.

## Roadmap

### Task 1 — Core package and manifest contract
Create `pyproject.toml`, `atlas/cli.py`, `atlas/manifest/models.py`, and Atlas-only tests. Define typed DatasetManifest, VideoProbe, ArtifactRecord and RunManifest contracts. Use TDD: invalid projection/hash manifests must fail before implementation; valid manifests must round-trip without losing provenance. Add `atlas inspect-manifest PATH`.

**Acceptance:** `python -m pytest tests/atlas/test_manifest.py tests/atlas/test_cli.py -v` passes.

### Task 2 — 360 input inspection
Create `atlas/ingest/probe.py`. Wrap ffprobe with argv arrays (no shell interpolation). Parse resolution/FPS/duration and validate 2:1 equirectangular ratio with 1% tolerance. Add `atlas probe VIDEO`.

**Tests first:** accept 7680x3840 and 3840x1920; reject 1920x1080 and missing video stream; parse `30000/1001` correctly.

### Task 3 — Deterministic frame/projection preparation
Create `atlas/frames/extract.py` and `atlas/frames/project.py`. Extract deterministic source frames with stable filenames and a metadata sidecar. Implement vectorized equirectangular-to-perspective projection with persisted yaw/pitch/FOV for every virtual camera.

**Tests first:** synthetic longitude/latitude grid must map center rays correctly at yaw 0/90/180/-90 and pitch +/-45.

### Task 4 — Frozen public 360 datasets
Create `datasets/atlas/smoke.json`, `datasets/atlas/benchmark.json`, `datasets/atlas/README.md`, and `scripts/atlas/download-dataset.py`. Select only legally downloadable moving indoor 360/equirectangular material; static panoramas do not qualify. Store source/license/SHA-256/expected metadata, not video binaries. Downloader streams to `.partial`, hashes while downloading, and atomically renames only after verification.

**Acceptance:** smoke clip downloads, checksum verifies, and passes `atlas probe`.

### Task 5 — External reconstruction adapter contract
Create `atlas/adapters/base.py`. Standardize `prepare`, `commands`, `run`, `collect`; log argv/cwd/return code/stdout/stderr/elapsed time. Tests use fake executables so CI does not require OpenMVS/CUDA.

### Task 6 — OpenMVS geometry baseline
Create `atlas/adapters/openmvs.py`. Detect external tool versions and build a reproducible geometry pipeline. Never vendor OpenMVS binaries. Prefer spherical-capable input; if direct spherical behavior is unreliable on the frozen dataset, use Task 3 deterministic perspective projections while preserving physical-frame grouping.

**Required artifacts:** camera poses, point cloud where available, textured mesh, logs, artifact hashes.

### Task 7 — Gaussian Splatting detail baseline
Create `atlas/adapters/splat.py` and `docs/atlas/THIRD_PARTY.md`. Before freezing an engine, verify maintenance status, license, Windows/NVIDIA feasibility, CLI reproducibility and viewer export. Feed the same prepared capture used by the geometry track.

**Required artifacts:** splat representation, camera transforms, training logs/metrics, viewer-compatible export.

### Task 8 — Benchmark and anti-scope-drift gate
Create `atlas/benchmark/report.py` and `atlas/benchmark/gate.py`. Produce `benchmark.json` and `benchmark.md` with success, time, GPU metadata when measurable, registered-frame ratio, artifact counts/sizes/hashes, trajectory continuity, detail-region assessment, viewer-openability and provenance completeness.

A candidate is promoted only when it reproducibly completes the frozen benchmark, opens in the Atlas viewer, does not regress required detail regions without a documented compensating advantage, and has complete provenance. Missing metrics are null, never guessed.

### Task 9 — Original 360 evidence index
Create `atlas/evidence/index.py`. Given reconstructed camera positions, return the nearest original capture frame and timestamp deterministically. Export `evidence-index.json` for the viewer.

### Task 10 — Standalone free-walk viewer
Create `atlas/viewer/` with Three.js. Separate navigation state from renderers. Provide Mesh/Splat mode, WASD + mouse look, adjustable speed, unrestricted movement, provenance panel, and `Show Original 360` using the evidence index. Splat rendering stays behind a loader boundary so renderer choice cannot contaminate navigation/evidence APIs.

### Task 11 — Windows/NVIDIA worker, server queue, and runbook
Create `scripts/atlas/setup-windows.ps1`, `scripts/atlas/run-benchmark.ps1`, `scripts/atlas/start-worker.ps1`, a single-click `START-ATLAS` launcher, `docs/atlas/WINDOWS_GPU_SETUP.md`, and `docs/atlas/RUNBOOK.md`; update `.gitignore`. Setup checks Python, ffmpeg/ffprobe, NVIDIA driver, nvidia-smi, CUDA visibility and configured external-engine paths. It reports exact remediation rather than silently installing opaque binaries.

One benchmark command executes: dataset verify -> probe -> prepare -> reconstruct -> benchmark -> viewer manifest.

Create `atlas/worker` and an Atlas-only `atlas/coordinator` contract/reference service. The laptop initiates outbound HTTPS polling, claims one job with a token and expiring lease, heartbeats ownership, downloads with byte-range resume to `.part`, verifies size/hash, invokes the exact local benchmark pipeline, checkpoints every durable stage, uploads artifacts resumably, verifies hashes, and completes idempotently. Unit tests use a fake coordinator and interrupted transfers; production SiteView localization remains untouched. The actual production server/auth adapter is frozen only against a verified server contract.

**Acceptance:** opening the one launcher is sufficient for normal operation. A queued test capture travels server -> laptop -> verified local pipeline -> server result without per-job commands, survives worker/network restart, and never puts media, artifacts, tokens, or signed URLs in Git.

### Task 12 — Real X5 validation
When the X5 is available, freeze one real head-mounted walk as a private validation dataset outside public Git. Run the exact same input contract and benchmark. Do not change the production SiteView integration until this passes.

**Capture target:** natural walking, arbitrary turns, useful loops/revisits, close passes by important construction details, no rigid station/grid requirement.

## Test discipline

Every production behavior follows RED -> GREEN -> REFACTOR. No production Python/JS behavior is added before its failing test is observed. External GPU engines are tested at two levels: deterministic unit tests with fake executables and explicit workstation smoke/benchmark runs with real binaries.

## Repository hygiene

Ignore at minimum: downloaded dataset media, extracted frames, run directories, `*.ply`, `*.obj`, `*.glb`, generated textures, splat outputs/checkpoints and logs containing local machine paths. No API keys, SDK secrets, private server credentials or private X5 footage are committed.

## Milestones

**M1 Harness:** Tasks 1–4. A real public moving 360 clip can be downloaded, verified, inspected and deterministically prepared.

**M2 Reconstruction:** Tasks 5–8. The same frozen clip produces reproducible Mesh/Splat benchmark artifacts and a promotion decision.

**M3 Inspection and transport:** Tasks 9–11. A manager can free-walk the result and jump to nearest original 360 evidence; a one-click RTX laptop worker can receive and return an Atlas job through the server queue.

**M4 X5:** Task 12. Real X5 capture passes the same workflow without changing the Atlas core contract.

## Definition of Done
A clean Windows/NVIDIA machine can clone this branch, follow one setup path, download and verify the approved public benchmark, execute the baseline from one command, generate versioned manifests/reports, open the result in a standalone free-walk viewer, inspect nearest original 360 evidence, and later repeat the same workflow with X5 media. Normal production operation starts from one launcher and automatically receives, verifies, processes, resumes, and returns server-queued jobs.
