export class EvidenceStore {
  constructor(payload, expectedCoordinateSystem = null) {
    if (!payload || payload.schema_version !== 1) {
      throw new TypeError("unsupported evidence index schema");
    }
    if (
      expectedCoordinateSystem !== null &&
      payload.coordinate_system !== expectedCoordinateSystem
    ) {
      throw new TypeError("evidence coordinate system does not match viewer");
    }
    if (!Array.isArray(payload.captures) || payload.captures.length === 0) {
      throw new TypeError("evidence index requires at least one capture");
    }

    const ids = new Set();
    this.coordinateSystem = requireText(payload.coordinate_system, "coordinate system");
    this.sourceVideo = requireText(payload.source_video, "source video");
    this.captures = payload.captures.map((capture) => {
      const physicalFrameId = requireText(
        capture.physical_frame_id,
        "physical frame ID",
      );
      if (ids.has(physicalFrameId)) {
        throw new TypeError(`duplicate evidence capture: ${physicalFrameId}`);
      }
      ids.add(physicalFrameId);
      const timestamp = Number(capture.timestamp_seconds);
      if (!Number.isFinite(timestamp) || timestamp < 0) {
        throw new TypeError("capture timestamp must be finite and non-negative");
      }
      return Object.freeze({
        physical_frame_id: physicalFrameId,
        timestamp_seconds: timestamp,
        source_frame: requireSafeFileName(capture.source_frame),
        position: finitePosition(capture.position),
      });
    });
    Object.freeze(this.captures);
  }

  nearest(position) {
    const query = finitePosition(position);
    let best = null;
    let bestDistanceSquared = Infinity;
    for (const capture of this.captures) {
      const distanceSquared = squaredDistance(query, capture.position);
      if (
        best === null ||
        distanceSquared < bestDistanceSquared ||
        (distanceSquared === bestDistanceSquared && compareTie(capture, best) < 0)
      ) {
        best = capture;
        bestDistanceSquared = distanceSquared;
      }
    }
    return Object.freeze({
      ...best,
      distance: Math.sqrt(bestDistanceSquared),
    });
  }
}

export function resolveLocalUrl(basePath, fileName, documentUrl) {
  const safeBase = requireSafeRelativeUrl(basePath);
  const safeName = requireSafeFileName(fileName);
  const normalizedBase = safeBase.endsWith("/") ? safeBase : `${safeBase}/`;
  return new URL(`${normalizedBase}${encodeURIComponent(safeName)}`, documentUrl).href;
}

export function requireSafeRelativeUrl(value) {
  if (typeof value !== "string" || value.length === 0) {
    throw new TypeError("resource must use a safe relative URL");
  }
  let decoded;
  try {
    decoded = decodeURIComponent(value);
  } catch {
    throw new TypeError("resource must use a safe relative URL");
  }
  const parts = decoded.split("/");
  if (
    decoded.startsWith("/") ||
    decoded.includes("\\") ||
    decoded.includes("?") ||
    decoded.includes("#") ||
    /^[A-Za-z][A-Za-z0-9+.-]*:/.test(decoded) ||
    parts.some((part) => part === "." || part === "..")
  ) {
    throw new TypeError("resource must use a safe relative URL");
  }
  return value;
}

function requireSafeFileName(value) {
  if (
    typeof value !== "string" ||
    value.length === 0 ||
    value === "." ||
    value === ".." ||
    value.includes("/") ||
    value.includes("\\")
  ) {
    throw new TypeError("source frame must use a safe file name");
  }
  return value;
}

function finitePosition(value) {
  if (
    !Array.isArray(value) &&
    !(ArrayBuffer.isView(value) && typeof value.length === "number")
  ) {
    throw new TypeError("position must contain three finite coordinates");
  }
  if (value.length !== 3) {
    throw new TypeError("position must contain three finite coordinates");
  }
  const result = Array.from(value, Number);
  if (!result.every(Number.isFinite)) {
    throw new TypeError("position must contain three finite coordinates");
  }
  return Object.freeze(result);
}

function squaredDistance(left, right) {
  return (
    (left[0] - right[0]) ** 2 +
    (left[1] - right[1]) ** 2 +
    (left[2] - right[2]) ** 2
  );
}

function compareTie(left, right) {
  if (left.timestamp_seconds !== right.timestamp_seconds) {
    return left.timestamp_seconds - right.timestamp_seconds;
  }
  if (left.physical_frame_id < right.physical_frame_id) return -1;
  if (left.physical_frame_id > right.physical_frame_id) return 1;
  return 0;
}

function requireText(value, label) {
  if (typeof value !== "string" || value.trim().length === 0) {
    throw new TypeError(`${label} must be non-empty text`);
  }
  return value;
}
