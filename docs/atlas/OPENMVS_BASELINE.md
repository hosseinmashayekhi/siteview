# OpenMVS geometry baseline

Status: code-complete with fake executables; real RTX 5090 validation pending.

OpenMVS remains an external dependency. Atlas neither vendors nor forks its
source or binaries. `ATLAS_OPENMVS_BIN` will point the Windows worker to an
explicit external binary directory after the laptop environment is probed.

## Why native spherical is the baseline

The upstream OpenMVS usage guide, inspected on 2026-09-15, documents a native
end-to-end equirectangular video pipeline. `ExtractKeyframes` accepts
`--camera-type 1`, and the later MVS stages receive an internal cube-map
projection. The documented flow is:

1. `ExtractKeyframes`
2. `CreateStructure`
3. `DensifyPointCloud`
4. `ReconstructMesh`
5. `RefineMesh`
6. `TextureMesh`
7. `TransformScene` for a self-contained GLB viewer artifact

Atlas makes argv, paths, and important spherical settings explicit. The initial
frozen choices are six internal cube faces, overlap threshold `0.85`, SIFT key
frame matching, refinement enabled, and verbosity level 3. These are recorded
choices, not claims that they are optimal.

Upstream references:

- <https://github.com/cdcseacave/openMVS/wiki/Usage>
- <https://github.com/cdcseacave/openMVS>

The upstream repository currently identifies OpenMVS as AGPL-3.0. This baseline
is technical evidence, not a production licensing approval; deployment terms
must be reviewed before the engine is shipped or offered as a network service.

## Required artifacts

The adapter refuses to report success unless it can hash all of the following:

- native camera-pose/SfM scene;
- OpenMVS scene;
- dense point cloud;
- refined mesh;
- textured mesh and at least one texture image;
- GLB viewer mesh;
- per-command stdout, stderr, exit code, cwd, argv, and elapsed time.

Executable version banners are probed individually. No OpenMVS, CUDA, Visual
Studio runtime, driver, or image tag version is frozen until the real laptop
probe and benchmark succeed.

## Perspective fallback gate

Native spherical processing is tested first on the frozen public benchmark. It
is rejected only if repeatable benchmark evidence shows failed registration,
broken trajectory, material holes, lost inspection detail, or unusable viewer
output. The fallback then consumes Task 3 deterministic perspective views. Each
virtual-view filename and sidecar retains its physical frame ID so evidence can
still resolve back to the original 360 capture.

Changing to COLMAP, OpenMVG, or another geometry frontend is a candidate change
and must pass the Task 8 anti-scope-drift gate before replacing this baseline.
