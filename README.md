# TraceAPI

TraceAPI is a FastAPI service for 3D neuron tracing. It wraps bundled neuTube and Vaa3D APP2/smartTrace binaries, accepts TIFF volumes or server-side TIFF paths, and returns SWC reconstructions.

## Features

- `neuTube` tracing for uploaded volumes.
- Vaa3D APP2 and smartTrace tracing.
- Kimimaro skeletonization of prediction/mask TIFFs, including directional subtrees.
- Directional subtree extraction from ordered seed pairs `s1 -> s2`.
- Batch seed-pair support: one SWC for a single pair, ZIP for multiple pairs.
- Temporary run outputs under `runs/`, cleaned periodically by the service.

## Repository Layout

```text
app.py             FastAPI routes
app_helpers.py     upload, workdir, subprocess, and volume-prep helpers
kimimaro_utils.py  Kimimaro skeletonization, coordinate conversion, and subprocess runner
subtree_utils.py   seed parsing and swclib-based subtree extraction
vaa3d_utils.py     Vaa3D/SWC utility functions
algorithms/        bundled neuTube, Vaa3D, Qt libraries, and plugins
algorithms/SPE-DNR/  bundled inference code, network, and official weights
requirements.txt   API, Kimimaro, and SPE-DNR Python dependencies
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
pip install -r requirements.txt
```

`swclib`, `kimimaro`, and the SPE-DNR Python dependencies are included in this requirements
file. Use the same Python environment for installation and the API server.

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
| `POST /trace_kimimaro` | prediction/mask `file` or `tif_path` | `output.swc` |
| `POST /trace_kimimaro_subtree` | prediction/mask `file` or `tif_path`, plus `s1`, `s2` | `subtree.swc` or `subtrees.zip` |
| `POST /trace_neutube` | uploaded `file` | `output.swc` |
| `POST /trace_neutube_subtree` | `file` or `tif_path`, plus `s1`, `s2` | `subtree.swc` or `subtrees.zip` |
| `POST /trace_vaa3d_app2` | uploaded `file` | `output.swc` |
| `POST /trace_vaa3d_app2_subtree` | `file` or `tif_path`, plus `s1`, `s2` | `subtree.swc` or `subtrees.zip` |
| `POST /trace_vaa3d_smartTrace` | uploaded `file` | `output.swc` |
| `POST /trace_spe_dnr` | original `file` or `tif_path`, VNet `mask_file` or `mask_path` | `output.swc` |
| `POST /trace_spe_dnr_subtree` | same image + VNet mask, plus `s1`, `s2` | `subtree.swc` or `subtrees.zip` |

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

### SPE-DNR with VNet predictions

SPE-DNR inference code, network definition, and official pretrained weights are
bundled in `algorithms/SPE-DNR/` within this project. The weights are stored at
`algorithms/SPE-DNR/checkpoint/classification_checkpoints/weight.pkl`.
Install the root `requirements.txt` into the API's Python environment.
This backend uses PyTorch and does not require Vaa3D, Qt, or DISPLAY.
Restart the API process after updating the code to expose the new endpoints.

Optional server configuration (set before starting the API):

```bash
export SPE_DNR_DEVICE=cpu                      # defaults to auto (CUDA if available)
```

The backend always uses the bundled code/weights and the API's own Python
interpreter. The former external directory/interpreter overrides are no longer
used. Copying this project preserves the backend; model downloads and sibling
project checkouts are not required. Input image/mask paths still refer to the
data supplied by the caller, and file uploads remain supported.

Supply **both the original TIFF and the corresponding VNet predicted map**.
Each input accepts exactly one upload or server path. TIFF arrays must be scalar
3D Z,Y,X, same shape and aligned, with finite nonnegative values. Original
intensities and map probabilities are preserved; no Vaa3D axis flip or image
normalization is applied. Output SWCs and `s1`, `s2` use **0-based x,y,z voxels**.
Seed coordinates are continuous and accepted in `[0, W) × [0, H) × [0, D)`.
For example, `255.496` is valid in a 256-voxel dimension. Boundary seeds retain
their original values when anchoring subtrees; they are not clipped to 255.

The map uses the paper's seed rule: probability **>0.5**, local maximum in a
3×3×3 neighborhood, followed by confidence-ordered tracing and joint decisions.
Float probabilities [0,1], scores [0,255], and binary 0/1 or 0/255 TIFFs are
accepted. For agreement with the paper, use VNet **centerline probabilities**.
A generic foreground binary segmentation loses the centerline confidence and
creates seeds throughout foreground plateaus; it is supported but not equivalent
to the paper's input. No image-based seed fallback is used by these endpoints.

Whole-volume tracing with uploads:

```bash
curl -X POST http://127.0.0.1:8000/trace_spe_dnr \
  -F 'file=@/path/to/original.tif' \
  -F 'mask_file=@/path/to/vnet_prediction.tif' \
  --output output.swc
```

Directional subtree with server paths:

```bash
curl -X POST http://127.0.0.1:8000/trace_spe_dnr_subtree \
  -F 'tif_path=/path/to/original.tif' \
  -F 'mask_path=/path/to/vnet_prediction.tif' \
  -F 's1=10,20,30' -F 's2=12,20,30' \
  --output subtree.swc
```

For multiple pairs, pass `s1=10,20,30;40,50,60` and
`s2=12,20,30;42,50,60`, and save the response as `subtrees.zip`.
The backend reconstructs once per request using VNet seeds, then applies the
shared subtree filter: snap to the nearest traced component within 8 voxels,
reroot at `s1`, select the branch closest to `s1 → s2`, and resample at 2 voxels.
Here `s1`/`s2` select the output subtree; unlike APP2's marker-based tracing they
do not replace the VNet seeds. Existing subtree filtering sets output radii to 1.
Empty predictions or root-snap misses return a header-only SWC, including in ZIPs.

Both routes optionally accept `soma_file` or `soma_path` for an independently
predicted soma mask; nonzero voxels stop tracing. By default soma stopping is
disabled. Do not pass a ground-truth test mask as a VNet or soma prediction.
This integration does not implement the original demo's heuristic soma merging.

Invalid/missing image or mask, mismatched shapes, invalid seed coordinates, or
mismatched seed-pair counts return HTTP 400. Tracing runs in a separate process;
the timeout is 3000 s for whole volumes and 600 s for subtrees, returning HTTP 504
and terminating the process group. Logs are under each request's `runs/` directory.
Requests do not share a loaded model; each subprocess loads the official weights.

Validation: all 28 API and bundled backend regression tests under `tests/`
and `algorithms/SPE-DNR/tests/` passed. A relocated service copy containing the
bundled backend also passed the HTTP tests with invalid external backend path
overrides, confirming that it loads its own code and weights. A local HTTP
smoke test using official weights and a 41×64×64 crop verified probability-map
uploads (164 nodes), a single subtree (9 nodes), two subtrees in ZIP, and a binary
mask (179 nodes). These are execution checks, not reconstruction-accuracy metrics.

## Kimimaro

These routes reproduce the Kimimaro method used by `neuron-trace/skeleton.py`.
Provide a scalar 3D TIFF in Z,Y,X order through exactly one of `file` or
`tif_path`. The input can be a probability map, binary mask, or intensity volume.
It is thresholded at `foreground_thres * max(input)` without min-max normalization.

Both routes accept optional form fields `foreground_thres` (default `0.5`,
must be in `(0,1]`) and `kimimaro_anisotropy` (default `0.35,0.35,1.0`, positive
X,Y,Z voxel spacings). TEASAR settings match the original implementation, with
`dust_threshold=100` and `parallel=1`. Output coordinates are zero-based voxel
X,Y,Z with no Y flip. Whole-volume radii retain Kimimaro's physical units, as in
the original implementation; the shared subtree filter writes radius 1.

```bash
curl -X POST http://127.0.0.1:8000/trace_kimimaro \
  -F 'file=@/path/to/prediction.tif' \
  --output kimimaro.swc

curl -X POST http://127.0.0.1:8000/trace_kimimaro_subtree \
  -F 'tif_path=/path/to/prediction.tif' \
  -F 's1=10,20,30' -F 's2=12,20,30' \
  --output kimimaro_subtree.swc
```

Subtrees use the shared `s1 -> s2` directional filter after one whole-volume
reconstruction per request. The root must be within 4 voxels of the traced
skeleton; otherwise the result is a header-only SWC. Multiple seed pairs use
the existing semicolon/JSON syntax and return `subtrees.zip`. All-zero images
and components removed by the dust threshold also return header-only SWCs.
Subprocess timeouts are 3000 s for whole volumes and 600 s for subtrees (HTTP
504); logs are saved as `kimimaro.log` in the request's run directory.

Validation command: `python -B -m pytest -q tests/test_kimimaro.py`.
The tests include real Kimimaro tracing with synthetic TIFFs, directional and
batched subtree responses, coordinate conversion, invalid inputs, and empty masks.

### Existing backend notes

- `tif_path` is resolved on the API server, not on the client machine.
- Subtree routes return `.swc` for one seed pair and `.zip` for multiple seed pairs.
- Vaa3D routes need `DISPLAY` and `LD_LIBRARY_PATH` configured before the server starts.
- Generated intermediate files are written under `runs/`.
