import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";

import { SceneHandle } from "./scene-handle.js";

export class MeshRepresentationLoader {
  constructor(scene) {
    this._scene = scene;
    this._loader = new GLTFLoader();
  }

  async load(asset) {
    if (asset.format !== "glb") {
      throw new TypeError(`unsupported mesh format: ${asset.format}`);
    }
    const gltf = await this._loader.loadAsync(asset.url);
    gltf.scene.visible = false;
    this._scene.add(gltf.scene);
    return new SceneHandle(this._scene, gltf.scene);
  }
}
