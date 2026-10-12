# Bundled SPE-DNR inference backend

This directory contains the inference code, network definition, and official
pretrained weights used by TraceAPI. All are ordinary local files; no symlinks,
sibling checkouts, downloads, or external model paths are needed at runtime.
The subprocess uses the same Python environment as the API.

Upstream: https://github.com/chwx08/SPE-DNR, revision `4be3285`.
Paper: Chen et al., TMI 2022, DOI `10.1109/TMI.2021.3130934`.
The upstream README is preserved as `README.upstream.md`.

Weight: `checkpoint/classification_checkpoints/weight.pkl` (official epoch 5).
SHA256: `e8bd5a57955e967282a13b8003e0436001373c75d8eae5a423ede5427729dec7`.

Local adaptations retain the official CNN and spherical-patch tracing, fix
zero/one-based indexing in traced-region and reverse-branch connections, use
tifffile and modern PyTorch loading, and export valid BFS SWC forests.
VNet maps follow the paper's >0.5 probability and 3x3x3 local-maximum seed rule.
The VNet itself is not trained or run here: callers supply its predicted map.
Binary masks are accepted but are not equivalent to centerline probabilities.
Optional soma masks stop tracing; heuristic soma merging is not implemented.

From the TraceAPI directory:

```bash
python -m pip install -r requirements.txt
python algorithms/SPE-DNR/infer.py \
  --image /path/to/image.tif --mask /path/to/vnet_prediction.tif \
  --output runs/prediction
python -m unittest discover -s algorithms/SPE-DNR/tests -v
```

`--list` plus `--mask-dir` also supports batch inference. The bundled entry
requires explicit input paths and has no default dependency on a local dataset.
See the project README for HTTP request examples and subtree semantics.
