# Atlas standalone viewer

The Atlas viewer is separate from the production SiteView/Localization viewer.
It consumes copied reconstruction artifacts and never changes capture or
localization state.

## Inspection modes

- **Mesh** loads the OpenMVS GLB through Three.js `GLTFLoader`.
- **Splat** loads the visual-detail output through Three.js
  `GaussianSplatPLYLoader`, `SPLATLoader`, or `SPZLoader`.
- **Original 360** finds the nearest registered physical capture in
  `evidence-index.json` and opens the real equirectangular source frame in a
  spherical panorama view. It is explicitly labeled as the source of truth.

Navigation state is independent from both representation loaders. WASD moves
on the viewing plane, Q/E moves vertically, mouse movement controls look
direction through pointer lock, and the speed slider changes movement speed.
There is no camera-path constraint.

## Viewer bundle contract

`viewer-manifest.json` contains only safe relative URLs. It identifies the run,
input SHA-256, coordinate system, initial position, artifact hashes, evidence
index, original-frame directory, run manifest, and benchmark report. Absolute
URLs, signed URLs, query strings, fragments, path traversal, and Windows paths
are rejected. The Python producer and browser consumer validate the same
contract.

A result directory supplied by the pipeline has this logical shape:

```text
viewer/
  index.html
  app.js
  styles.css
  viewer-manifest.json
  artifacts/
    site.glb
    site.ply
  evidence/
    evidence-index.json
    frames/
      physical_000000.png
  provenance/
    run.json
    benchmark.json
```

The source build pins Three.js and esbuild in `package-lock.json`, has no CDN
dependency, applies a same-origin Content Security Policy, and includes the
Three.js MIT license in the generated bundle.

Task 11 will call this build and serve the completed result through the single
Atlas launcher. Normal operation will not require running npm commands by hand.

## Validation boundary

Unit tests and a production bundle build run without a reconstruction artifact.
`viewer.opened`, free-walk inspection, fixed detail viewpoints, and real
Original 360 lookup remain `NULL` until the frozen artifact is exercised on the
target laptop/browser. Task 8 correctly blocks promotion while those results are
unknown.
