import { GaussianSplatPLYLoader } from "three/addons/loaders/GaussianSplatPLYLoader.js";
import { SPLATLoader } from "three/addons/loaders/SPLATLoader.js";
import { SPZLoader } from "three/addons/loaders/SPZLoader.js";
import { GaussianSplat } from "three/addons/objects/GaussianSplat.js";

import { SceneHandle } from "./scene-handle.js";

const LOADERS = Object.freeze({
  "gaussian-ply": GaussianSplatPLYLoader,
  splat: SPLATLoader,
  spz: SPZLoader,
});

export class SplatRepresentationLoader {
  constructor(scene) {
    this._scene = scene;
  }

  async load(asset) {
    const Loader = LOADERS[asset.format];
    if (!Loader) throw new TypeError(`unsupported splat format: ${asset.format}`);
    const geometry = await new Loader().loadAsync(asset.url);
    const splat = new GaussianSplat(geometry);
    splat.visible = false;
    this._scene.add(splat);
    return new SceneHandle(this._scene, splat, [geometry]);
  }
}
