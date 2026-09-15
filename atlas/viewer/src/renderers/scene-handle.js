export class SceneHandle {
  constructor(scene, object, extraDisposables = []) {
    this._scene = scene;
    this._object = object;
    this._extraDisposables = extraDisposables;
    this._disposed = false;
  }

  setVisible(value) {
    if (this._disposed) return;
    this._object.visible = Boolean(value);
  }

  dispose() {
    if (this._disposed) return;
    this._disposed = true;
    this._scene.remove(this._object);
    const disposed = new Set();
    this._object.traverse((child) => {
      disposeOnce(child.geometry, disposed);
      const materials = Array.isArray(child.material)
        ? child.material
        : [child.material];
      for (const material of materials) disposeMaterial(material, disposed);
    });
    for (const disposable of this._extraDisposables) {
      disposeOnce(disposable, disposed);
    }
  }
}

function disposeMaterial(material, disposed) {
  if (!material || disposed.has(material)) return;
  for (const value of Object.values(material)) {
    if (value?.isTexture) disposeOnce(value, disposed);
  }
  disposeOnce(material, disposed);
}

function disposeOnce(value, disposed) {
  if (!value || disposed.has(value) || typeof value.dispose !== "function") return;
  disposed.add(value);
  value.dispose();
}
