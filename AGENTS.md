# Repository Guidelines

## Project Structure & Module Organization
This repository exposes a FastAPI service for neuron tracing. `app.py` defines the API routes, upload handling, temporary run directories, and calls into tracing executables. `vaa3d_utils.py` contains image normalization, SWC post-processing, iterative tracing helpers, and mask utilities. `algorithms/` stores bundled Vaa3D, neuTube, Qt libraries, and plugins; treat these as vendor binaries. `command.sh` is a runnable notebook of local setup, server, and curl examples. `runs/`, `__pycache__/`, and `*.pyc` are ignored transient outputs. Root-level `*.swc` files are sample or generated tracing outputs.

## Build, Test, and Development Commands
Create and activate a Python environment with the required runtime packages (`fastapi`, `uvicorn`, `numpy`, `scipy`, `tifffile`, `swclib`, plus system libraries noted in `command.sh`).

```bash
export LD_LIBRARY_PATH="$PWD/algorithms:$LD_LIBRARY_PATH"
python -m uvicorn app:app --host 0.0.0.0 --port 8000 --workers 4
```

Use Xvfb when running Vaa3D headlessly:

```bash
Xvfb :99 -screen 0 1920x1080x24 -ac &
export DISPLAY=:99
```

Smoke-test an endpoint with a local TIFF:

```bash
curl -X POST http://127.0.0.1:8000/trace_neutube \
  -F "file=@/path/to/volume.tif" --output output.swc
```

## Coding Style & Naming Conventions
Use Python 3 style with 4-space indentation, type hints for helper boundaries, and `pathlib.Path` for filesystem paths. Keep route names and endpoint paths aligned, for example `trace_vaa3d_app2` for `/trace_vaa3d_app2`. Prefer small helpers for repeated subprocess, upload, and SWC-processing logic. Avoid committing machine-specific absolute paths except in clearly marked examples.

## Testing Guidelines
There is no formal test suite yet. Before submitting changes, run the FastAPI service and smoke-test each affected route with a small 3D TIFF. Confirm the returned SWC exists and is non-empty. For utility changes, add lightweight tests under a future `tests/` directory using `test_*.py` names, and keep fixtures small enough for quick local runs.

## Commit & Pull Request Guidelines
Recent history uses short date/operator-style messages such as `260616-zyt` and merge commits. Keep new commit messages concise and specific, for example `fix app2 timeout handling` or `add trace smoke test`. Pull requests should describe changed endpoints or algorithms, list manual test commands and outputs, note any required system libraries, and call out changes to bundled binaries or generated SWC files.

## Security & Configuration Tips
Do not commit large generated data from `runs/` or private input volumes. Keep executable paths relative to `BASE_DIR` where possible. Validate uploaded file suffixes and preserve subprocess timeouts when adding tracing backends.
