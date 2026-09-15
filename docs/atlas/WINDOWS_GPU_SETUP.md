# Atlas Windows/NVIDIA Setup

Atlas source code is versioned in Git. All downloaded captures and generated
artifacts are kept outside the repository on the RTX laptop.

## Fixed laptop layout

```text
C:\3dcamera\
  siteview\                 Git checkout: atlas/3d-reconstruction
  data\
    datasets\               downloaded public and private inputs
    runs\                   isolated, resumable run workspaces
    frames\                 extracted physical and virtual frames
    mesh\                   generated geometry artifacts
    splats\                 generated visual-detail artifacts
    reports\                environment and benchmark reports
    workspace.json          local path contract
```

During development, double-click the repository-root entry point:

```text
START-ATLAS.cmd
```

It invokes `scripts\atlas\setup-windows.ps1`, creates the local Python
environment, initializes the directories, and
writes `C:\3dcamera\data\reports\environment.json`. It does not silently
install ffmpeg, Docker, NVIDIA drivers, CUDA toolkits, OpenMVS, or a splatting
engine. Missing tools are recorded with exact remediation, and unverified GPU
facts remain `null`.

`cuda_version_reported_by_nvidia_smi` is only the compatibility value reported
by the installed driver. It is not proof that a chosen CUDA container or a
reconstruction engine works on the GPU. `docker_gpu_verified` therefore stays
`null` until a real container probe is run on the laptop.

## One-click target

The same `START-ATLAS.cmd` launcher becomes the long-running entry point in the
completed Task 11. The laptop worker will initiate outbound HTTPS connections to the Atlas server queue,
claim jobs, download captures resumably, process them locally, upload verified
artifacts, and continue polling. Per-capture PowerShell commands are not part of
the production operating model.
