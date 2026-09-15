export class PanoramaState {
  constructor({ yawDegrees = 0, pitchDegrees = 0, fovDegrees = 70 } = {}) {
    this._yawDegrees = requireFinite(yawDegrees, "yaw");
    this._pitchDegrees = clamp(requireFinite(pitchDegrees, "pitch"), -85, 85);
    this._fovDegrees = requireFov(fovDegrees);
  }

  get yawDegrees() {
    return this._yawDegrees;
  }

  get pitchDegrees() {
    return this._pitchDegrees;
  }

  get fovDegrees() {
    return this._fovDegrees;
  }

  dragBy(deltaX, deltaY) {
    const x = requireFinite(deltaX, "drag delta");
    const y = requireFinite(deltaY, "drag delta");
    this._yawDegrees = normalizeDegrees(this._yawDegrees - x * 0.2);
    this._pitchDegrees = clamp(this._pitchDegrees - y * 0.2, -85, 85);
  }

  zoomBy(deltaY) {
    const delta = requireFinite(deltaY, "zoom delta");
    this._fovDegrees = clamp(this._fovDegrees + delta * 0.1, 30, 100);
  }
}

function requireFinite(value, label) {
  const number = Number(value);
  if (!Number.isFinite(number)) throw new TypeError(`${label} must be finite`);
  return number;
}

function requireFov(value) {
  const fov = requireFinite(value, "field of view");
  if (fov < 30 || fov > 100) {
    throw new RangeError("field of view must be between 30 and 100 degrees");
  }
  return fov;
}

function normalizeDegrees(value) {
  return ((value + 180) % 360 + 360) % 360 - 180;
}

function clamp(value, minimum, maximum) {
  return Math.min(maximum, Math.max(minimum, value));
}
