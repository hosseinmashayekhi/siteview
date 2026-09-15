import assert from "node:assert/strict";
import test from "node:test";

import { RepresentationController } from "../../../atlas/viewer/src/representation-controller.js";

function fakeLoader(name, calls) {
  return {
    async load(asset) {
      calls.push([name, asset.url]);
      return {
        visible: false,
        disposed: false,
        setVisible(value) {
          this.visible = value;
        },
        dispose() {
          this.disposed = true;
        },
      };
    },
  };
}

test("mode switching stays behind loaders and does not reload cached assets", async () => {
  const calls = [];
  const controller = new RepresentationController({
    mesh: fakeLoader("mesh-loader", calls),
    splat: fakeLoader("splat-loader", calls),
  });

  const mesh = await controller.activate({ mode: "mesh", url: "site.glb" });
  const splat = await controller.activate({ mode: "splat", url: "site.ply" });
  const meshAgain = await controller.activate({ mode: "mesh", url: "site.glb" });

  assert.deepEqual(calls, [
    ["mesh-loader", "site.glb"],
    ["splat-loader", "site.ply"],
  ]);
  assert.equal(mesh, meshAgain);
  assert.equal(mesh.visible, true);
  assert.equal(splat.visible, false);
  assert.equal(controller.activeMode, "mesh");
});

test("a failed renderer load leaves the current representation visible", async () => {
  const calls = [];
  const controller = new RepresentationController({
    mesh: fakeLoader("mesh", calls),
    splat: {
      async load() {
        throw new Error("bad splat");
      },
    },
  });
  const mesh = await controller.activate({ mode: "mesh", url: "site.glb" });

  await assert.rejects(
    controller.activate({ mode: "splat", url: "site.ply" }),
    /bad splat/,
  );

  assert.equal(mesh.visible, true);
  assert.equal(controller.activeMode, "mesh");
});

test("dispose releases every loaded representation", async () => {
  const controller = new RepresentationController({
    mesh: fakeLoader("mesh", []),
    splat: fakeLoader("splat", []),
  });
  const mesh = await controller.activate({ mode: "mesh", url: "site.glb" });
  const splat = await controller.activate({ mode: "splat", url: "site.ply" });

  controller.dispose();

  assert.equal(mesh.disposed, true);
  assert.equal(splat.disposed, true);
  assert.equal(controller.activeMode, null);
});

test("a slow stale load cannot override a newer mode choice", async () => {
  let finishSplat;
  let staleHandle;
  const controller = new RepresentationController({
    mesh: fakeLoader("mesh", []),
    splat: {
      load() {
        return new Promise((resolve) => {
          finishSplat = () => {
            staleHandle = {
              visible: false,
              disposed: false,
              setVisible(value) {
                this.visible = value;
              },
              dispose() {
                this.disposed = true;
              },
            };
            resolve(staleHandle);
          };
        });
      },
    },
  });
  const mesh = await controller.activate({ mode: "mesh", url: "site.glb" });
  const pendingSplat = controller.activate({ mode: "splat", url: "site.ply" });
  await controller.activate({ mode: "mesh", url: "site.glb" });

  finishSplat();
  await pendingSplat;

  assert.equal(controller.activeMode, "mesh");
  assert.equal(mesh.visible, true);
  assert.equal(staleHandle.visible, false);
  assert.equal(staleHandle.disposed, true);
});
