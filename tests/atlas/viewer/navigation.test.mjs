import assert from "node:assert/strict";
import test from "node:test";

import { NavigationState } from "../../../atlas/viewer/src/navigation-state.js";

test("WASD and vertical keys produce normalized unrestricted movement", () => {
  const state = new NavigationState({ speed: 4 });
  state.keyDown("KeyW");
  state.keyDown("KeyD");
  state.keyDown("KeyE");

  const movement = state.movementFor(0.5);
  const expected = 2 / Math.sqrt(3);

  assert.ok(Math.abs(movement.forward - expected) < 1e-12);
  assert.ok(Math.abs(movement.right - expected) < 1e-12);
  assert.ok(Math.abs(movement.up - expected) < 1e-12);
});

test("opposite keys cancel and releasing a key changes movement", () => {
  const state = new NavigationState({ speed: 2 });
  state.keyDown("KeyW");
  state.keyDown("KeyS");
  assert.deepEqual(state.movementFor(1), { forward: 0, right: 0, up: 0 });

  state.keyUp("KeyS");
  assert.deepEqual(state.movementFor(0.25), { forward: 0.5, right: 0, up: 0 });
  state.clear();
  assert.deepEqual(state.movementFor(1), { forward: 0, right: 0, up: 0 });
});

test("speed is adjustable and unsafe frame deltas are capped", () => {
  const state = new NavigationState({ speed: 1, maxDeltaSeconds: 0.1 });
  state.setSpeed(6);
  state.keyDown("KeyW");

  const movement = state.movementFor(5);
  assert.ok(Math.abs(movement.forward - 0.6) < 1e-12);
  assert.equal(movement.right, 0);
  assert.equal(movement.up, 0);
  assert.throws(() => state.setSpeed(0), /speed must be finite and greater than zero/);
  assert.throws(() => state.movementFor(Number.NaN), /delta must be finite/);
});
