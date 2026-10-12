# API Reference

Base URL for local service examples:

```text
http://127.0.0.1:8000
```

The GitHub Pages URL is documentation-only — the live service runs wherever you
deploy it:

```text
https://yang-ze-kang.github.io/TraceAPI/
```

## Endpoint Summary

| Method & Path | Input | Success response |
| --- | --- | --- |
| `POST /trace_kimimaro` | prediction/mask `file` or `tif_path` | `output.swc` |
| `POST /trace_kimimaro_subtree` | prediction/mask `file` or `tif_path`, `s1`, `s2` | `subtree.swc` or `subtrees.zip` |
| `POST /trace_neutube` | `file` | `output.swc` |
| `POST /trace_neutube_subtree` | `file` or `tif_path`, `s1`, `s2` | `subtree.swc` or `subtrees.zip` |
| `POST /trace_vaa3d_app2` | `file` | `output.swc` |
| `POST /trace_vaa3d_app2_subtree` | `file` or `tif_path`, `s1`, `s2` | `subtree.swc` or `subtrees.zip` |
| `POST /trace_vaa3d_smartTrace` | `file` | `output.swc` |

All requests are `multipart/form-data`. All successful tracing responses are
SWC files (`application/octet-stream`); multi-pair subtree responses are ZIP
archives (`application/zip`).

See [Input Formats](inputs.md) for seed/volume rules and [Errors](errors.md)
for status codes. For request/response snippets in `curl` and Python, see
[Client Examples](examples.md).

## `POST /trace_kimimaro` and `POST /trace_kimimaro_subtree`

Skeletonize a scalar 3D prediction/mask TIFF with Kimimaro. The subtree route
traces once, then extracts branches in the directions given by `s1 -> s2`.

| Name | Required | Type | Description |
| --- | --- | --- | --- |
| `file` | one of `file`/`tif_path` | file | Uploaded TIFF in Z,Y,X order. |
| `tif_path` | one of `file`/`tif_path` | string | Server-side TIFF path. |
| `foreground_thres` | no | float | Fraction of input maximum, default `0.5`, range `(0,1]`. |
| `kimimaro_anisotropy` | no | string | Positive X,Y,Z voxel spacings, default `0.35,0.35,1.0`. |
| `s1` | subtree only | string | Start seed point(s), in voxel X,Y,Z. |
| `s2` | subtree only | string | Direction seed point(s), in voxel X,Y,Z. |

**Returns:** `output.swc` for the full route; `subtree.swc` for one seed pair,
or `subtrees.zip` for multiple pairs. Coordinates are zero-based voxel X,Y,Z.
Empty foreground or a subtree root more than 4 voxels from the skeleton yields
a header-only SWC. Invalid TIFFs, anisotropy, or seed pairs return HTTP 400;
invalid numeric thresholds return HTTP 422. Subprocess timeouts return HTTP 504
(3000 s for the full route, 600 s for subtrees).

```bash
curl -X POST http://127.0.0.1:8000/trace_kimimaro \
  -F 'file=@/path/to/prediction.tif' --output kimimaro.swc

curl -X POST http://127.0.0.1:8000/trace_kimimaro_subtree \
  -F 'tif_path=/path/to/prediction.tif' \
  -F 's1=10,20,30;40,50,60' -F 's2=12,20,30;42,50,60' \
  --output subtrees.zip
```

## `POST /trace_neutube`

Run neuTube tracing on an uploaded volume and return the full reconstruction.

| Name | Required | Type | Description |
| --- | --- | --- | --- |
| `file` | yes | file | 3D input volume (multipart upload). |

**Returns:** `output.swc`.

=== "curl"

    ```bash
    curl -X POST http://127.0.0.1:8000/trace_neutube \
      -F "file=@/path/to/volume.tif" \
      --output output.swc
    ```

=== "Python"

    ```python
    from pathlib import Path
    import requests

    url = "http://127.0.0.1:8000/trace_neutube"
    with open("/path/to/volume.tif", "rb") as f:
        resp = requests.post(url, files={"file": f}, timeout=None)
    resp.raise_for_status()
    Path("output.swc").write_bytes(resp.content)
    ```

## `POST /trace_neutube_subtree`

Run neuTube tracing, then extract directional subtrees from one or more seed
pairs.

| Name | Required | Type | Description |
| --- | --- | --- | --- |
| `file` | one of `file`/`tif_path` | file | Uploaded input volume. |
| `tif_path` | one of `file`/`tif_path` | string | Server-side input path. |
| `s1` | yes | string | Start seed point(s). |
| `s2` | yes | string | Direction seed point(s). |

**Returns:** `subtree.swc` for one pair, or `subtrees.zip` for multiple pairs.

=== "curl"

    ```bash
    curl -X POST http://127.0.0.1:8000/trace_neutube_subtree \
      -F "tif_path=/data2/public_data/CWMBS/image/SN21.tif" \
      -F "s1=242.8440,249.8640,7.9980" \
      -F "s2=243.5728,248.0015,7.9980" \
      --output SN21_seed1_neuTube.swc
    ```

=== "Python"

    ```python
    from pathlib import Path
    import requests

    url = "http://127.0.0.1:8000/trace_neutube_subtree"
    data = {
        "tif_path": "/data2/public_data/CWMBS/image/SN21.tif",
        "s1": "242.8440,249.8640,7.9980",
        "s2": "243.5728,248.0015,7.9980",
    }
    resp = requests.post(url, data=data, timeout=None)
    resp.raise_for_status()
    Path("SN21_seed1_neuTube.swc").write_bytes(resp.content)
    ```

## `POST /trace_vaa3d_app2`

Run iterative Vaa3D APP2 tracing on an uploaded volume. The service repeatedly
traces, accepts and masks out each branch, and falls back to candidate seeds
when automatic tracing finds nothing. See [Algorithms](algorithms.md).

| Name | Required | Type | Description |
| --- | --- | --- | --- |
| `file` | yes | file | 3D input volume (multipart upload). |

**Returns:** merged `output.swc`. Returns `422` if no branch is accepted.

=== "curl"

    ```bash
    curl -X POST http://127.0.0.1:8000/trace_vaa3d_app2 \
      -F "file=@/path/to/volume.tif" \
      --output app2.swc
    ```

=== "Python"

    ```python
    from pathlib import Path
    import requests

    url = "http://127.0.0.1:8000/trace_vaa3d_app2"
    with open("/path/to/volume.tif", "rb") as f:
        resp = requests.post(url, files={"file": f}, timeout=None)
    resp.raise_for_status()
    Path("app2.swc").write_bytes(resp.content)
    ```

## `POST /trace_vaa3d_app2_subtree`

Run Vaa3D APP2 from each `s1` marker, then apply the same directional
extraction used by neuTube subtree tracing. Unlike the full APP2 route, this
runs APP2 once per seed pair (no iterative masking loop).

| Name | Required | Type | Description |
| --- | --- | --- | --- |
| `file` | one of `file`/`tif_path` | file | Uploaded input volume. |
| `tif_path` | one of `file`/`tif_path` | string | Server-side input path. |
| `s1` | yes | string | APP2 marker/start seed point(s). |
| `s2` | yes | string | Direction seed point(s). |

**Returns:** `subtree.swc` for one pair, or `subtrees.zip` for multiple pairs.
Returns `422 APP2 failed for seed pair <i>` if tracing fails for any pair.

=== "curl"

    ```bash
    curl -X POST http://127.0.0.1:8000/trace_vaa3d_app2_subtree \
      -F "tif_path=/data2/public_data/CWMBS/image/SN21.tif" \
      -F "s1=242.8440,249.8640,7.9980" \
      -F "s2=243.5728,248.0015,7.9980" \
      --output SN21_seed1_app2.swc
    ```

=== "Python"

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

## `POST /trace_vaa3d_smartTrace`

Run iterative Vaa3D smartTrace tracing on an uploaded volume, with a one-time
foreground denoise fallback when a pass finds nothing. See
[Algorithms](algorithms.md).

| Name | Required | Type | Description |
| --- | --- | --- | --- |
| `file` | yes | file | 3D input volume (multipart upload). |

**Returns:** merged `output.swc`. May return an empty merge if nothing is
traced; an empty/zero-byte result then triggers `500`.

=== "curl"

    ```bash
    curl -X POST http://127.0.0.1:8000/trace_vaa3d_smartTrace \
      -F "file=@/path/to/volume.tif" \
      --output smarttrace.swc
    ```

=== "Python"

    ```python
    from pathlib import Path
    import requests

    url = "http://127.0.0.1:8000/trace_vaa3d_smartTrace"
    with open("/path/to/volume.tif", "rb") as f:
        resp = requests.post(url, files={"file": f}, timeout=None)
    resp.raise_for_status()
    Path("smarttrace.swc").write_bytes(resp.content)
    ```
