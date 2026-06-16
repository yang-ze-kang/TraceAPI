# TraceAPI

TraceAPI is a FastAPI service for 3D neuron tracing. It wraps bundled neuTube and Vaa3D APP2/smartTrace binaries, accepts TIFF volumes or server-side TIFF paths, and returns SWC reconstructions.

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

## API Summary

| Endpoint | Input | Output |
| --- | --- | --- |
| `POST /trace_neutube` | uploaded `file` | `output.swc` |
| `POST /trace_neutube_subtree` | `file` or `tif_path`, plus `s1`, `s2` | `subtree.swc` or `subtrees.zip` |
| `POST /trace_vaa3d_app2` | uploaded `file` | `output.swc` |
| `POST /trace_vaa3d_app2_subtree` | `file` or `tif_path`, plus `s1`, `s2` | `subtree.swc` or `subtrees.zip` |
| `POST /trace_vaa3d_smartTrace` | uploaded `file` | `output.swc` |

Seed points use `x,y,z`. Multiple seed pairs can be sent with semicolons:

```text
s1=10,20,30;40,50,60
s2=11,20,30;42,50,60
```

## curl Examples

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

## Python Examples

Install the client dependency:

```bash
pip install requests
```

Trace an uploaded TIFF with neuTube:

```python
from pathlib import Path
import requests

url = "http://127.0.0.1:8000/trace_neutube"
with open("/path/to/volume.tif", "rb") as f:
    resp = requests.post(url, files={"file": f}, timeout=None)
resp.raise_for_status()
Path("output.swc").write_bytes(resp.content)
```

Trace an APP2 subtree from a server-side TIFF path:

```python
from pathlib import Path
import requests

url = "http://127.0.0.1:8000/trace_vaa3d_app2_subtree"
data = {
    "tif_path": "/data2/public_data/CWMBS/image/SN21.tif",
    "s1": "242.8440,249.8640,7.9980",
    "s2": "243.5728,248.0015,7.9980",
}
resp = requests.post(url, data=data, timeout=None)
resp.raise_for_status()
Path("SN21_seed1_app2.swc").write_bytes(resp.content)
```

Trace multiple neuTube subtrees and save the returned ZIP:

```python
from pathlib import Path
import requests

url = "http://127.0.0.1:8000/trace_neutube_subtree"
data = {
    "tif_path": "/path/to/volume.tif",
    "s1": "10,20,30;40,50,60",
    "s2": "11,20,30;42,50,60",
}
resp = requests.post(url, data=data, timeout=None)
resp.raise_for_status()
Path("subtrees.zip").write_bytes(resp.content)
```

Trace an uploaded TIFF with smartTrace:

```python
from pathlib import Path
import requests

url = "http://127.0.0.1:8000/trace_vaa3d_smartTrace"
with open("/path/to/volume.tif", "rb") as f:
    resp = requests.post(url, files={"file": f}, timeout=None)
resp.raise_for_status()
Path("smarttrace.swc").write_bytes(resp.content)
```

## Notes

- `tif_path` is resolved on the API server, not on the client machine.
- Subtree routes return `.swc` for one seed pair and `.zip` for multiple seed pairs.
- Vaa3D routes need `DISPLAY` and `LD_LIBRARY_PATH` configured before the server starts.
- Generated intermediate files are written under `runs/`.
