import {
  MathUtils,
  Mesh,
  MeshBasicMaterial,
  PerspectiveCamera,
  Scene,
  SphereGeometry,
  SRGBColorSpace,
  TextureLoader,
  Vector3,
  WebGPURenderer,
} from "three/webgpu";

import { PanoramaState } from "./panorama-state.js";

export class PanoramaViewer {
  constructor(canvas) {
    this._canvas = canvas;
    this._scene = new Scene();
    this._camera = new PerspectiveCamera(70, 1, 0.05, 100);
    this._target = new Vector3();
    this._state = new PanoramaState();
    this._texture = null;
    this._loadSerial = 0;
    this._drag = null;

    this._renderer = new WebGPURenderer({
      canvas,
      antialias: true,
      forceWebGL: true,
    });
    this._ready = this._renderer.init();

    const geometry = new SphereGeometry(10, 80, 48);
    geometry.scale(-1, 1, 1);
    this._material = new MeshBasicMaterial({ color: 0xffffff });
    this._sphere = new Mesh(geometry, this._material);
    this._scene.add(this._sphere);

    canvas.addEventListener("pointerdown", (event) => this._pointerDown(event));
    canvas.addEventListener("pointermove", (event) => this._pointerMove(event));
    canvas.addEventListener("pointerup", (event) => this._pointerUp(event));
    canvas.addEventListener("pointercancel", (event) => this._pointerUp(event));
    canvas.addEventListener(
      "wheel",
      (event) => {
        event.preventDefault();
        this._state.zoomBy(event.deltaY);
        this._render();
      },
      { passive: false },
    );
  }

  async show(url) {
    const serial = ++this._loadSerial;
    await this._ready;
    const texture = await new TextureLoader().loadAsync(url);
    if (serial !== this._loadSerial) {
      texture.dispose();
      return;
    }
    texture.colorSpace = SRGBColorSpace;
    this._texture?.dispose();
    this._texture = texture;
    this._material.map = texture;
    this._material.needsUpdate = true;
    this._state = new PanoramaState();
    await this._render();
  }

  clear() {
    this._loadSerial += 1;
    this._texture?.dispose();
    this._texture = null;
    this._material.map = null;
    this._material.needsUpdate = true;
  }

  _pointerDown(event) {
    this._drag = { x: event.clientX, y: event.clientY, id: event.pointerId };
    this._canvas.setPointerCapture(event.pointerId);
  }

  _pointerMove(event) {
    if (!this._drag || event.pointerId !== this._drag.id) return;
    this._state.dragBy(event.clientX - this._drag.x, event.clientY - this._drag.y);
    this._drag.x = event.clientX;
    this._drag.y = event.clientY;
    this._render();
  }

  _pointerUp(event) {
    if (!this._drag || event.pointerId !== this._drag.id) return;
    this._drag = null;
    if (this._canvas.hasPointerCapture(event.pointerId)) {
      this._canvas.releasePointerCapture(event.pointerId);
    }
  }

  async _render() {
    await this._ready;
    const width = Math.max(1, this._canvas.clientWidth);
    const height = Math.max(1, this._canvas.clientHeight);
    this._renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    this._renderer.setSize(width, height, false);
    this._camera.aspect = width / height;
    this._camera.fov = this._state.fovDegrees;
    this._camera.updateProjectionMatrix();

    const latitude = MathUtils.degToRad(this._state.pitchDegrees);
    const longitude = MathUtils.degToRad(this._state.yawDegrees);
    this._target.set(
      Math.sin(longitude) * Math.cos(latitude),
      Math.sin(latitude),
      Math.cos(longitude) * Math.cos(latitude),
    );
    this._camera.lookAt(this._target);
    await this._renderer.renderAsync(this._scene, this._camera);
  }
}
