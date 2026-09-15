# Atlas third-party reconstruction engines

**Audit date:** 2026-09-15  
**Decision status:** provisional code baseline; real RTX 5090 benchmark pending

Atlas keeps every reconstruction engine external. No engine source, binary,
checkpoint, dataset, or generated artifact is copied into this repository.
Versions and commands must be captured for every run.

## Visual-detail baseline decision

The provisional Task 7 baseline is the actively maintained
[`gsplat`](https://github.com/nerfstudio-project/gsplat) project, driven through
its official `examples/simple_trainer.py default` command and initialized from
a COLMAP sparse reconstruction. `gsplat` is Apache-2.0 licensed. Its official
COLMAP example documents the training CLI, browser viewer, and reproducible
evaluation path, while its trainer emits a checkpoint, JSON metrics,
TensorBoard logs, and a standard Gaussian PLY when `--save_ply` is enabled.

This is not a permanent engine freeze. The exact gsplat, PyTorch, CUDA, and
COLMAP versions remain **NULL / pending** until the real `C:\3dcamera` laptop
probe and smoke run succeed. Task 8 must then prove that the result opens in the
Atlas viewer and meets the fixed detail benchmark before this candidate is
promoted.

Atlas uses external
[`COLMAP`](https://colmap.github.io/cli.html) for the splat track's camera poses
and sparse initialization. COLMAP is licensed under the new BSD license. The
adapter follows its documented CLI stages: feature extraction, matching,
mapping, and model conversion.

## Candidate audit

| Candidate | License | Maintenance evidence at audit | Windows / NVIDIA | Reproducible CLI and export | Atlas decision |
|---|---|---|---|---|---|
| gsplat official trainer | Apache-2.0 | Active commits through 2026-09-03; v1.6.0 work documents current PyTorch/CUDA compatibility | Official project supplies Windows wheels for selected version combinations and source-build guidance; RTX 5090 remains unverified | Official COLMAP trainer CLI; checkpoints, JSON evaluation metrics, TensorBoard, and Gaussian PLY | **Provisional baseline** behind `GsplatAdapter` |
| Nerfstudio Splatfacto | Apache-2.0 | Latest repository commit observed 2025-07-29; latest release observed v1.1.5 (2024-11-11); gsplat backend remains active | Official installation guide calls native Windows less tested and fragile; WSL2 is presented as an unofficial option | Excellent integrated `ns-process-data`, `ns-train splatfacto`, `ns-eval`, and `ns-export gaussian-splat` flow; direct equirectangular/head-mounted input documented | Retained research candidate; not selected because current maintenance and Windows reliability evidence is weaker |
| OpenSplat | AGPL-3.0 | Active commits through 2026-09-03 and v1.2.0 released 2026-08-20 | Native Windows, CUDA, and Docker paths documented | Stable executable; PLY/SPLAT/SPZ/RAD output plus camera JSON | Strong benchmark candidate, but AGPL deployment obligations require a deliberate product/license review |
| Graphdeco-INRIA reference implementation | Custom research-only license | Latest commits observed in 2024 | Windows viewer and CUDA path exist | Reference training and viewer commands | **Rejected for product baseline:** license explicitly limits use to research/evaluation and prohibits commercial use without consent |

The audit records observable project facts, not legal advice. Any distribution
or server deployment involving copyleft software still needs an owner-approved
license review.

## Standalone viewer dependency

The Task 10 viewer pins **Three.js r186 / npm 0.186.0**, which is MIT licensed.
This release supplies the official `GLTFLoader` for the geometry GLB and the
official `GaussianSplatPLYLoader` plus `GaussianSplat` object for the gsplat PLY
export. `GaussianSplat` runs through `WebGPURenderer` and supports its WebGL
fallback; navigation, evidence lookup, and renderer selection remain Atlas-owned
modules outside those loaders. The browser build has no CDN dependency and
copies the Three.js MIT license into its generated distribution.

## Atlas adapter contract

`atlas/adapters/splat.py` does the following without touching SiteView
localization:

1. accepts only deterministic Task 3 perspective views;
2. validates that every physical frame has the same virtual-camera layout;
3. stages only files declared by `views.json` and writes
   `atlas-projection-index.json` with image hashes and physical frame IDs;
4. supplies exact PINHOLE intrinsics to external COLMAP;
5. runs the official external gsplat trainer with a fixed seed, full-resolution
   input, a headless viewer setting, explicit training/evaluation/checkpoint
   steps, and PLY export;
6. hashes camera transforms, sparse points, configuration, checkpoint, metrics,
   command log, provenance index, and viewer PLY.

The fixed projection index is essential: a virtual camera is never allowed to
lose the ID of the real 360 frame from which it was generated. This link will
later support `Show Original 360` evidence lookup.

## External installation boundary

The adapter points to an external gsplat checkout through
`GsplatExecutables.from_checkout(...)`. Task 11 will place that checkout under
the laptop's tools/data area, record its commit, and invoke it from the single
`START-ATLAS.cmd` launcher. The setup will not choose a CUDA or PyTorch build
until it has read the actual NVIDIA driver, CUDA visibility, GPU model, and GPU
memory from the laptop.

## Primary sources

- [gsplat repository, license, current compatibility, and Windows notes](https://github.com/nerfstudio-project/gsplat)
- [gsplat official COLMAP trainer CLI](https://docs.gsplat.studio/main/examples/colmap.html)
- [COLMAP documented command-line pipeline](https://colmap.github.io/cli.html)
- [COLMAP repository and new BSD license](https://github.com/colmap/colmap)
- [Nerfstudio Splatfacto CLI and PLY export](https://docs.nerf.studio/nerfology/methods/splat.html)
- [Nerfstudio equirectangular and head-mounted capture flow](https://docs.nerf.studio/quickstart/custom_dataset.html#data-360-equirectangular)
- [Nerfstudio Windows installation caveats](https://docs.nerf.studio/quickstart/installation.html)
- [OpenSplat CLI, formats, Windows path, and AGPL license](https://github.com/WebODM/OpenSplat)
- [Graphdeco-INRIA license restrictions](https://github.com/graphdeco-inria/gaussian-splatting/blob/main/LICENSE.md)
- [Three.js r186 release](https://github.com/mrdoob/three.js/releases/tag/r186)
- [Three.js Gaussian PLY loader](https://github.com/mrdoob/three.js/blob/r186/examples/jsm/loaders/GaussianSplatPLYLoader.js)
- [Three.js Gaussian splat renderer and WebGL fallback](https://github.com/mrdoob/three.js/blob/r186/examples/jsm/objects/GaussianSplat.js)
- [Three.js MIT license](https://github.com/mrdoob/three.js/blob/r186/LICENSE)
