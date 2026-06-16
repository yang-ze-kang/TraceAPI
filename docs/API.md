# TraceAPI API Reference

Base URL for local service examples:

```text
http://127.0.0.1:8000
```

The public GitHub Pages URL is documentation-only:

```text
https://yang-ze-kang.github.io/TraceAPI/
```

## Common Inputs

Supported image suffixes:

```text
.tif, .tiff, .png, .jpg, .jpeg
```

Tracing routes expect 3D image volumes. Subtree routes accept seed points as:

```text
s1=242.8440,249.8640,7.9980
s2=243.5728,248.0015,7.9980
```

Batch seed pairs can be semicolon-separated:

```text
s1=10,20,30;40,50,60
s2=11,20,30;42,50,60
```

or JSON:

```text
s1=[[10,20,30],[40,50,60]]
s2=[[11,20,30],[42,50,60]]
```

Single seed-pair routes return one `.swc`; multiple seed pairs return `subtrees.zip`.

## `POST /trace_neutube`

Run neuTube tracing on an uploaded volume.

### Form Fields

| Name | Required | Type | Description |
| --- | --- | --- | --- |
| `file` | yes | file | Input volume. |

### Response

`output.swc`

### Example

```bash
curl -X POST http://127.0.0.1:8000/trace_neutube \
  -F "file=@/path/to/volume.tif" \
  --output output.swc
```

## `POST /trace_neutube_subtree`

Run neuTube tracing, then extract directional subtrees from seed pairs.

### Form Fields

| Name | Required | Type | Description |
| --- | --- | --- | --- |
| `file` | one of `file`/`tif_path` | file | Uploaded input volume. |
| `tif_path` | one of `file`/`tif_path` | string | Server-side input path. |
| `s1` | yes | string | Start seed point(s). |
| `s2` | yes | string | Direction seed point(s). |

### Response

`subtree.swc` for one pair, or `subtrees.zip` for multiple pairs.

### Example

```bash
curl -X POST http://127.0.0.1:8000/trace_neutube_subtree \
  -F "tif_path=/data2/public_data/CWMBS/image/SN21.tif" \
  -F "s1=242.8440,249.8640,7.9980" \
  -F "s2=243.5728,248.0015,7.9980" \
  --output SN21_seed1_neuTube.swc
```

## `POST /trace_vaa3d_app2`

Run iterative Vaa3D APP2 tracing on an uploaded volume.

### Form Fields

| Name | Required | Type | Description |
| --- | --- | --- | --- |
| `file` | yes | file | Input volume. |

### Response

`output.swc`

### Example

```bash
curl -X POST http://127.0.0.1:8000/trace_vaa3d_app2 \
  -F "file=@/path/to/volume.tif" \
  --output app2.swc
```

## `POST /trace_vaa3d_app2_subtree`

Run Vaa3D APP2 from each `s1` marker, then apply the same `filter_swc_subtree` directional extraction used by neuTube subtree tracing.

### Form Fields

| Name | Required | Type | Description |
| --- | --- | --- | --- |
| `file` | one of `file`/`tif_path` | file | Uploaded input volume. |
| `tif_path` | one of `file`/`tif_path` | string | Server-side input path. |
| `s1` | yes | string | APP2 marker/start seed point(s). |
| `s2` | yes | string | Direction seed point(s). |

### Response

`subtree.swc` for one pair, or `subtrees.zip` for multiple pairs.

### Example

```bash
curl -X POST http://127.0.0.1:8000/trace_vaa3d_app2_subtree \
  -F "tif_path=/data2/public_data/CWMBS/image/SN21.tif" \
  -F "s1=242.8440,249.8640,7.9980" \
  -F "s2=243.5728,248.0015,7.9980" \
  --output SN21_seed1_app2.swc
```

## `POST /trace_vaa3d_smartTrace`

Run iterative Vaa3D smartTrace tracing on an uploaded volume.

### Form Fields

| Name | Required | Type | Description |
| --- | --- | --- | --- |
| `file` | yes | file | Input volume. |

### Response

`output.swc`

### Example

```bash
curl -X POST http://127.0.0.1:8000/trace_vaa3d_smartTrace \
  -F "file=@/path/to/volume.tif" \
  --output smarttrace.swc
```

## Subtree Extraction Notes

For each seed pair:

1. Find the closest SWC node to `s1`.
2. Reroot the traced tree at that node.
3. Resample with spacing equal to `distance(s1, s2)`.
4. Find the child branch closest to the target direction.
5. Remove other root branches and return the subtree.

