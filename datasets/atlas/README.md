# Atlas frozen public datasets

Atlas keeps only manifests, URLs, checksums, expected metadata, and attribution in
Git. Videos, extracted frames, reconstructions, textures, and checkpoints belong
under `C:\3dcamera\data`, never in this repository.

## Frozen inputs

Both tiers currently use the same real moving capture so smoke failures remain
comparable with the full benchmark:

- `smoke.json` selects Wikimedia's 480p VP9 derivative (20,335,470 bytes).
- `benchmark.json` selects the original 3840x1920 VP9 file (200,815,472 bytes).

The sequence moves through a passenger-train interior and includes narrow
passages, doors, walls, reflections, people, occlusions, near surfaces, visual
overlap, and translational parallax. It is licensed CC BY 3.0; the manifest keeps
the source page, license URL, author credit, exact byte length, SHA-256, and
observed ffprobe values.

`revisits` is deliberately `null`: a reliable loop has not been established from
published metadata. Atlas records unknown evidence as null instead of inventing
a value. This sequence is a public engineering baseline, not a replacement for
the later private X5 construction-site validation capture.

## Automated use

The Windows worker will invoke the downloader through `START-ATLAS.cmd`. This
manual form exists for diagnostics and CI:

```powershell
python scripts/atlas/download-dataset.py datasets/atlas/smoke.json `
  --output-dir C:\3dcamera\data\datasets
```

The downloader writes only to `<filename>.partial`, streams the SHA-256, checks
the declared size, then atomically publishes the final name. A corrupt download
is deleted and an existing mismatched file is never overwritten.

## Selection audit

Static panoramas and stationary 360 videos were rejected. Other reviewed inputs
remain candidates rather than frozen baselines:

- AIST Living Lab 1 has an excellent indoor loop, but no explicit license for
  the linked dataset was found.
- OmniPhotos is CC BY 4.0 and has deliberate circular motion, but its released
  scenes inspected for Atlas were outdoor.
- Hilti-Trimble-Oxford is construction-specific, but its multi-gigabyte ROS bags
  and non-commercial license are unsuitable for this portable public baseline.
- Helvipad has clearly licensed indoor equirectangular sequences and useful depth
  data, but is distributed as a large frame corpus rather than a directly
  probeable video; it remains a future benchmark extension.

Dataset candidates can replace this baseline only through the Task 8 benchmark
gate, with reproducible viewer-compatible outputs and complete provenance.
