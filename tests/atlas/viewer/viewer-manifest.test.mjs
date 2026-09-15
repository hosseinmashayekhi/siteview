import assert from "node:assert/strict";
import test from "node:test";

import { parseViewerManifest } from "../../../atlas/viewer/src/viewer-manifest.js";

function validManifest() {
  return {
    schema_version: 1,
    run_id: "run-001",
    input_sha256: "a".repeat(64),
    coordinate_system: "atlas-world-v1",
    initial_position: [0, 1.7, 0],
    assets: [
      {
        mode: "mesh",
        format: "glb",
        url: "artifacts/site.glb",
        sha256: "b".repeat(64),
      },
      {
        mode: "splat",
        format: "gaussian-ply",
        url: "artifacts/site.ply",
        sha256: "c".repeat(64),
      },
    ],
    evidence_index_url: "evidence/evidence-index.json",
    original_frame_base_url: "evidence/frames/",
    run_manifest_url: "provenance/run.json",
    benchmark_report_url: "provenance/benchmark.json",
  };
}

test("viewer manifest exposes one immutable asset per renderer mode", () => {
  const manifest = parseViewerManifest(validManifest());

  assert.equal(manifest.assetsByMode.mesh.format, "glb");
  assert.equal(manifest.assetsByMode.splat.format, "gaussian-ply");
  assert.equal(manifest.run_id, "run-001");
  assert.equal(Object.isFrozen(manifest), true);
  assert.equal(Object.isFrozen(manifest.assetsByMode), true);
});

test("viewer manifest rejects duplicate modes and mode-format mismatch", () => {
  const duplicate = validManifest();
  duplicate.assets[1] = { ...duplicate.assets[0] };
  assert.throws(() => parseViewerManifest(duplicate), /duplicate viewer mode/);

  const mismatch = validManifest();
  mismatch.assets[0].format = "gaussian-ply";
  assert.throws(() => parseViewerManifest(mismatch), /format is not valid/);
});

test("viewer manifest rejects unknowns and unsafe resource URLs", () => {
  const unknownSchema = validManifest();
  unknownSchema.schema_version = 2;
  assert.throws(() => parseViewerManifest(unknownSchema), /unsupported viewer manifest/);

  const unsafe = validManifest();
  unsafe.evidence_index_url = "https://evil.test/evidence.json";
  assert.throws(() => parseViewerManifest(unsafe), /safe relative URL/);

  const badHash = validManifest();
  badHash.assets[0].sha256 = "guess";
  assert.throws(() => parseViewerManifest(badHash), /SHA-256/);
});
