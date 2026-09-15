import assert from "node:assert/strict";
import test from "node:test";

import {
  EvidenceStore,
  resolveLocalUrl,
} from "../../../atlas/viewer/src/evidence-store.js";

const payload = {
  schema_version: 1,
  source_video: "walk.mp4",
  coordinate_system: "atlas-world-v1",
  captures: [
    {
      physical_frame_id: "physical-b",
      timestamp_seconds: 0.5,
      source_frame: "physical_000001.png",
      position: [-1, 0, 0],
      contributing_view_ids: ["view-b"],
    },
    {
      physical_frame_id: "physical-a",
      timestamp_seconds: 0.5,
      source_frame: "physical_000000.png",
      position: [0, 1, 0],
      contributing_view_ids: ["view-a"],
    },
    {
      physical_frame_id: "physical-z",
      timestamp_seconds: 1,
      source_frame: "physical_000002.png",
      position: [1, 0, 0],
      contributing_view_ids: ["view-z"],
    },
  ],
};

test("nearest evidence is deterministic and preserves source truth", () => {
  const store = new EvidenceStore(payload);
  const match = store.nearest([0, 0, 0]);

  assert.equal(match.physical_frame_id, "physical-a");
  assert.equal(match.timestamp_seconds, 0.5);
  assert.equal(match.source_frame, "physical_000000.png");
  assert.equal(match.distance, 1);
});

test("malformed or non-finite evidence is rejected instead of guessed", () => {
  assert.throws(
    () => new EvidenceStore({ ...payload, coordinate_system: "other" }, "atlas-world-v1"),
    /coordinate system does not match/,
  );
  assert.throws(() => new EvidenceStore({ ...payload, captures: [] }), /at least one capture/);
  assert.throws(() => new EvidenceStore(payload).nearest([Infinity, 0, 0]), /three finite/);
});

test("local URL resolution encodes frame names and blocks traversal or origins", () => {
  assert.equal(
    resolveLocalUrl("evidence/frames/", "frame 1.png", "https://atlas.local/viewer/index.html"),
    "https://atlas.local/viewer/evidence/frames/frame%201.png",
  );
  assert.throws(
    () => resolveLocalUrl("../private/", "frame.png", "https://atlas.local/viewer/"),
    /safe relative URL/,
  );
  assert.throws(
    () => resolveLocalUrl("https://evil.test/", "frame.png", "https://atlas.local/viewer/"),
    /safe relative URL/,
  );
  assert.throws(
    () => resolveLocalUrl("evidence/", "../frame.png", "https://atlas.local/viewer/"),
    /safe file name/,
  );
});
