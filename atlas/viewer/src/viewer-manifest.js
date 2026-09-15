import { requireSafeRelativeUrl } from "./evidence-store.js";

const VALID_FORMATS = Object.freeze({
  mesh: new Set(["glb"]),
  splat: new Set(["gaussian-ply", "splat", "spz"]),
});

export function parseViewerManifest(payload) {
  if (!payload || payload.schema_version !== 1) {
    throw new TypeError("unsupported viewer manifest schema");
  }
  if (!Array.isArray(payload.assets) || payload.assets.length === 0) {
    throw new TypeError("viewer manifest requires at least one asset");
  }

  const assetsByMode = Object.create(null);
  for (const rawAsset of payload.assets) {
    const mode = rawAsset?.mode;
    if (!Object.hasOwn(VALID_FORMATS, mode)) {
      throw new TypeError(`unknown viewer mode: ${mode ?? "NULL"}`);
    }
    if (Object.hasOwn(assetsByMode, mode)) {
      throw new TypeError(`duplicate viewer mode: ${mode}`);
    }
    if (!VALID_FORMATS[mode].has(rawAsset.format)) {
      throw new TypeError(`format is not valid for ${mode} mode`);
    }
    const asset = Object.freeze({
      mode,
      format: rawAsset.format,
      url: requireSafeRelativeUrl(rawAsset.url),
      sha256: requireSha256(rawAsset.sha256),
    });
    assetsByMode[mode] = asset;
  }

  return Object.freeze({
    schema_version: 1,
    run_id: requireText(payload.run_id, "run ID"),
    input_sha256: requireSha256(payload.input_sha256),
    coordinate_system: requireText(payload.coordinate_system, "coordinate system"),
    initial_position: finitePosition(payload.initial_position),
    assetsByMode: Object.freeze(assetsByMode),
    evidence_index_url: requireSafeRelativeUrl(payload.evidence_index_url),
    original_frame_base_url: requireSafeRelativeUrl(payload.original_frame_base_url),
    run_manifest_url: requireSafeRelativeUrl(payload.run_manifest_url),
    benchmark_report_url: requireSafeRelativeUrl(payload.benchmark_report_url),
  });
}

function requireSha256(value) {
  if (typeof value !== "string" || !/^[0-9a-f]{64}$/.test(value)) {
    throw new TypeError("value must be a lowercase SHA-256 digest");
  }
  return value;
}

function requireText(value, label) {
  if (typeof value !== "string" || value.trim().length === 0) {
    throw new TypeError(`${label} must be non-empty text`);
  }
  return value;
}

function finitePosition(value) {
  if (!Array.isArray(value) || value.length !== 3) {
    throw new TypeError("position must contain three finite coordinates");
  }
  const result = value.map(Number);
  if (!result.every(Number.isFinite)) {
    throw new TypeError("position must contain three finite coordinates");
  }
  return Object.freeze(result);
}
