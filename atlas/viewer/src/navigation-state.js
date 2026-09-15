const MOVEMENT_KEYS = new Set([
  "KeyW",
  "KeyA",
  "KeyS",
  "KeyD",
  "KeyQ",
  "KeyE",
]);

export class NavigationState {
  constructor({ speed = 2, maxDeltaSeconds = 1 } = {}) {
    this._pressed = new Set();
    this._maxDeltaSeconds = requirePositiveFinite(
      maxDeltaSeconds,
      "maximum frame delta",
    );
    this.setSpeed(speed);
  }

  get speed() {
    return this._speed;
  }

  setSpeed(value) {
    this._speed = requirePositiveFinite(value, "speed");
  }

  keyDown(code) {
    if (MOVEMENT_KEYS.has(code)) this._pressed.add(code);
  }

  keyUp(code) {
    this._pressed.delete(code);
  }

  clear() {
    this._pressed.clear();
  }

  movementFor(deltaSeconds) {
    if (!Number.isFinite(deltaSeconds) || deltaSeconds < 0) {
      throw new TypeError("delta must be finite and non-negative");
    }
    const forward = Number(this._pressed.has("KeyW")) - Number(this._pressed.has("KeyS"));
    const right = Number(this._pressed.has("KeyD")) - Number(this._pressed.has("KeyA"));
    const up = Number(this._pressed.has("KeyE")) - Number(this._pressed.has("KeyQ"));
    const length = Math.hypot(forward, right, up);
    if (length === 0) return { forward: 0, right: 0, up: 0 };

    const distance = this._speed * Math.min(deltaSeconds, this._maxDeltaSeconds);
    return {
      forward: (forward / length) * distance,
      right: (right / length) * distance,
      up: (up / length) * distance,
    };
  }
}

function requirePositiveFinite(value, label) {
  const number = Number(value);
  if (!Number.isFinite(number) || number <= 0) {
    throw new TypeError(`${label} must be finite and greater than zero`);
  }
  return number;
}
