# TraceAPI

TraceAPI is a FastAPI service for 3D neuron tracing. It wraps bundled neuTube and Vaa3D APP2/smartTrace binaries, accepts uploaded TIFF volumes or server-side TIFF paths, and returns SWC reconstructions.

## Features

- neuTube tracing for uploaded or server-side volumes.
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
docs/              MkDocs documentation source
mkdocs.yml         MkDocs Material configuration
```

## Requirements

- Python 3.9+
- Vaa3D/Qt system libraries
- Python packages: `fastapi`, `uvicorn`, `python-multipart`, `numpy`, `scipy`, `tifffile`, `swclib`

Install common system dependencies:

```bash
sudo apt-get install -y xvfb libglu1-mesa \
  libqt5widgets5 libqt5gui5 libqt5xml5 libqt5network5 libqt5core5a libqt5concurrent5
```

Install Python dependencies:

```bash
pip install fastapi uvicorn python-multipart numpy scipy tifffile
pip install -e /path/to/swclib
```

## Run Locally

```bash
Xvfb :99 -screen 0 1920x1080x24 -ac &
export DISPLAY=:99
export LD_LIBRARY_PATH="$PWD/algorithms:$LD_LIBRARY_PATH"
python -m uvicorn app:app --host 0.0.0.0 --port 8000 --workers 4
```

## Quick Example

```bash
curl -X POST http://127.0.0.1:8000/trace_vaa3d_app2_subtree \
  -F "tif_path=/data2/public_data/CWMBS/image/SN21.tif" \
  -F "s1=242.8440,249.8640,7.9980" \
  -F "s2=243.5728,248.0015,7.9980" \
  --output SN21_seed1_app2.swc
```

See [API Reference](api.md) for all endpoints.

