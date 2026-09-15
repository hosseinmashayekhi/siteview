import assert from "node:assert/strict";
import test from "node:test";

import { PanoramaState } from "../../../atlas/viewer/src/panorama-state.js";

test("panorama drag changes yaw and clamps pitch away from the poles", () => {
  const state = new PanoramaState({ yawDegrees: 0, pitchDegrees: 0, fovDegrees: 70 });

  state.dragBy(100, -1000);

  assert.equal(state.yawDegrees, -20);
  assert.equal(state.pitchDegrees, 85);
});

test("panorama zoom stays inside inspectable FOV limits", () => {
  const state = new PanoramaState({ fovDegrees: 70 });
  state.zoomBy(-1000);
  assert.equal(state.fovDegrees, 30);
  state.zoomBy(1000);
  assert.equal(state.fovDegrees, 100);
});

test("panorama state rejects non-finite input", () => {
  const state = new PanoramaState();
  assert.throws(() => state.dragBy(Number.NaN, 0), /finite/);
  assert.throws(() => new PanoramaState({ fovDegrees: 0 }), /between 30 and 100/);
});
