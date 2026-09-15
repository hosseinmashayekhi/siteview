export class RepresentationController {
  constructor(loaders) {
    if (!loaders || typeof loaders !== "object") {
      throw new TypeError("representation loaders are required");
    }
    this._loaders = { ...loaders };
    this._loaded = new Map();
    this._activeMode = null;
    this._activationSerial = 0;
  }

  get activeMode() {
    return this._activeMode;
  }

  async activate(asset) {
    const activationSerial = ++this._activationSerial;
    const loader = this._loaders[asset?.mode];
    if (!loader || typeof loader.load !== "function") {
      throw new TypeError(`no renderer loader for mode: ${asset?.mode ?? "NULL"}`);
    }

    const key = assetKey(asset);
    const cached = this._loaded.get(asset.mode);
    let nextHandle;
    let newlyLoaded = false;
    if (cached?.key === key) {
      nextHandle = cached.handle;
    } else {
      nextHandle = await loader.load(asset);
      requireHandle(nextHandle);
      newlyLoaded = true;
    }

    if (activationSerial !== this._activationSerial) {
      if (newlyLoaded) nextHandle.dispose();
      return nextHandle;
    }

    const active = this._activeMode === null ? null : this._loaded.get(this._activeMode);
    active?.handle.setVisible(false);

    if (cached && cached.key !== key) cached.handle.dispose();
    this._loaded.set(asset.mode, { key, handle: nextHandle });
    nextHandle.setVisible(true);
    this._activeMode = asset.mode;
    return nextHandle;
  }

  dispose() {
    this._activationSerial += 1;
    for (const { handle } of this._loaded.values()) handle.dispose();
    this._loaded.clear();
    this._activeMode = null;
  }
}

function assetKey(asset) {
  if (!asset || typeof asset.url !== "string" || asset.url.length === 0) {
    throw new TypeError("representation asset requires a URL");
  }
  return `${asset.mode}\u0000${asset.format ?? ""}\u0000${asset.url}\u0000${asset.sha256 ?? ""}`;
}

function requireHandle(handle) {
  if (
    !handle ||
    typeof handle.setVisible !== "function" ||
    typeof handle.dispose !== "function"
  ) {
    throw new TypeError("renderer loader returned an invalid handle");
  }
}
