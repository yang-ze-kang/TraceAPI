# TraceAPI

TraceAPI is a FastAPI service for 3D neuron tracing. It wraps bundled neuTube and Vaa3D APP2/smartTrace binaries, accepts TIFF volumes or server-side TIFF paths, and returns SWC reconstructions.

Project homepage/API docs: <https://yang-ze-kang.github.io/TraceAPI/>

## Features

- `neuTube` tracing for uploaded volumes.
- Vaa3D APP2 and smartTrace tracing.
- Directional subtree extraction from ordered seed pairs `s1 -> s2`.
- Batch seed-pair support: one SWC for a single pair, ZIP for multiple pairs.
- Temporary run outputs under `runs/`, cleaned periodically by the service.

## Repository Layout

```text
app.py             FastAPI routes
app_helpers.py     upload, workdir, subprocess, and volume-prep helpers
subtree_utils.py   seed parsing and swclib-based subtree extraction
vaa3d_utils.py     Vaa3D/SWC utility functions
algorithms/        bundled neuTube, Vaa3D, Qt libraries, and plugins
docs/API.md        endpoint reference
index.html         GitHub Pages landing/API page
```

## Requirements

- Python 3.9+
- System libraries for Vaa3D/Qt, for example:

```bash
sudo apt-get install -y xvfb libglu1-mesa \
  libqt5widgets5 libqt5gui5 libqt5xml5 libqt5network5 libqt5core5a libqt5concurrent5
```

- Python packages:

```bash
pip install fastapi uvicorn python-multipart numpy scipy tifffile
```

Install `swclib` in the runtime environment, for example from a local checkout:

```bash
pip install -e /path/to/swclib
```

## Run Locally

```bash
Xvfb :99 -screen 0 1920x1080x24 -ac &
export DISPLAY=:99
export LD_LIBRARY_PATH="$PWD/algorithms:$LD_LIBRARY_PATH"
python -m uvicorn app:app --host 0.0.0.0 --port 8000 --workers 4
```

## Quick Examples

Trace with neuTube:

```bash
curl -X POST http://127.0.0.1:8000/trace_neutube \
  -F "file=@/path/to/volume.tif" \
  --output output.swc
```

Trace and extract an APP2 subtree from a server-side TIFF:

```bash
curl -X POST http://127.0.0.1:8000/trace_vaa3d_app2_subtree \
  -F "tif_path=/data2/public_data/CWMBS/image/SN21.tif" \
  -F "s1=242.8440,249.8640,7.9980" \
  -F "s2=243.5728,248.0015,7.9980" \
  --output SN21_seed1_app2.swc
```

Batch seed pairs:

```bash
curl -X POST http://127.0.0.1:8000/trace_neutube_subtree \
  -F "tif_path=/path/to/volume.tif" \
  -F "s1=10,20,30;40,50,60" \
  -F "s2=11,20,30;42,50,60" \
  --output subtrees.zip
```

See [docs/API.md](docs/API.md) for the complete endpoint reference.

## GitHub Pages

This repository includes a static `index.html`. To publish it:

1. Push the repository to GitHub.
2. Open **Settings > Pages**.
3. Select the deployment branch and root directory.
4. The documentation will be available at `https://yang-ze-kang.github.io/TraceAPI/`.

