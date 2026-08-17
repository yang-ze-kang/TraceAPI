# Client Examples

End-to-end examples for calling TraceAPI from the command line and from Python.
The Python examples use [`requests`](https://requests.readthedocs.io/):

```bash
pip install requests
```

In every example, replace `http://127.0.0.1:8000` with your server address and
adjust paths to your data.

## Uploading a Local File

Send a volume from the client machine as a multipart upload.

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
    print("saved output.swc")
    ```

!!! tip "Use timeout=None"
    Tracing can take minutes. Pass `timeout=None` (or a generous timeout) so the
    client does not abort a long-running trace.

## Referencing a Server-Side Path

Subtree routes accept `tif_path`, a path resolved **on the server**. No file is
uploaded — only the path string is sent as a form field.

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

## Batch Seed Pairs (ZIP Response)

When you send more than one seed pair, the response is a ZIP containing one SWC
per pair. Detect it via the `Content-Type` header.

=== "curl"

    ```bash
    curl -X POST http://127.0.0.1:8000/trace_neutube_subtree \
      -F "tif_path=/path/to/volume.tif" \
      -F "s1=10,20,30;40,50,60" \
      -F "s2=11,20,30;42,50,60" \
      --output subtrees.zip
    ```

=== "Python"

    ```python
    import io
    import zipfile
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

    content_type = resp.headers.get("content-type", "")
    if "zip" in content_type:
        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            zf.extractall("subtrees")
        print("extracted", zf.namelist())
    else:
        Path("subtree.swc").write_bytes(resp.content)
    ```

## JSON Seed Arrays

`s1`/`s2` also accept JSON arrays (see [Input Formats](inputs.md)).

```python
import json
import requests

url = "http://127.0.0.1:8000/trace_vaa3d_app2_subtree"
data = {
    "tif_path": "/path/to/volume.tif",
    "s1": json.dumps([[10, 20, 30], [40, 50, 60]]),
    "s2": json.dumps([[11, 20, 30], [42, 50, 60]]),
}
resp = requests.post(url, data=data, timeout=None)
resp.raise_for_status()
```

## Handling Errors

Errors come back as JSON with a `detail` field (see [Errors](errors.md)).

```python
import requests

url = "http://127.0.0.1:8000/trace_vaa3d_app2"
with open("/path/to/volume.tif", "rb") as f:
    resp = requests.post(url, files={"file": f}, timeout=None)

if not resp.ok:
    try:
        detail = resp.json().get("detail")
    except ValueError:
        detail = resp.text
    raise SystemExit(f"Tracing failed ({resp.status_code}): {detail}")

with open("app2.swc", "wb") as out:
    out.write(resp.content)
```

## A Reusable Client

A small wrapper that auto-saves `.swc` or `.zip` based on the response type:

```python
from pathlib import Path
import requests


class TraceClient:
    def __init__(self, base_url="http://127.0.0.1:8000"):
        self.base_url = base_url.rstrip("/")

    def _post(self, route, *, files=None, data=None):
        resp = requests.post(
            f"{self.base_url}{route}", files=files, data=data, timeout=None
        )
        if not resp.ok:
            try:
                detail = resp.json().get("detail")
            except ValueError:
                detail = resp.text
            raise RuntimeError(f"{resp.status_code}: {detail}")
        return resp

    def _save(self, resp, stem):
        ext = ".zip" if "zip" in resp.headers.get("content-type", "") else ".swc"
        out = Path(f"{stem}{ext}")
        out.write_bytes(resp.content)
        return out

    def trace_neutube(self, tif, out="output"):
        with open(tif, "rb") as f:
            resp = self._post("/trace_neutube", files={"file": f})
        return self._save(resp, out)

    def app2_subtree(self, tif_path, s1, s2, out="subtree"):
        resp = self._post(
            "/trace_vaa3d_app2_subtree",
            data={"tif_path": tif_path, "s1": s1, "s2": s2},
        )
        return self._save(resp, out)


if __name__ == "__main__":
    client = TraceClient()
    print(client.app2_subtree(
        "/data2/public_data/CWMBS/image/SN21.tif",
        s1="242.8440,249.8640,7.9980",
        s2="243.5728,248.0015,7.9980",
        out="SN21_seed1",
    ))
```
