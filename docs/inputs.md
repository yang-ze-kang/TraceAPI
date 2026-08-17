# Input Formats

This page documents exactly what the service accepts for image volumes and seed
points, based on the parsing and preprocessing code in `app_helpers.py`,
`vaa3d_utils.py`, and `subtree_utils.py`.

## Image Volumes

### Accepted file types

The service validates the file suffix (case-insensitive) against:

```text
.tif  .tiff  .png  .jpg  .jpeg
```

An unsupported suffix returns `400 Unsupported file type: <suffix>`.

!!! note "3D volumes only"
    Although image suffixes such as `.png`/`.jpg` are accepted by the suffix
    check, every tracing route requires a **3D** array. After reading the image
    the service asserts `img.ndim == 3`; otherwise it returns
    `400 Expected 3D volume, got shape=<shape>`. In practice this means a
    multi-page TIFF stack `(Z, Y, X)`.

### Two ways to supply a volume

| Source | Field | Used by |
| --- | --- | --- |
| Multipart upload | `file` | all routes |
| Server-side path | `tif_path` | subtree routes only |

- `file` is a standard multipart upload (`-F "file=@..."`).
- `tif_path` is an absolute path **on the API server**. It is expanded with
  `~` support, validated to exist and be a regular file, then copied into the
  run's working directory. It is never resolved on the client machine.

The plain tracing routes (`/trace_neutube`, `/trace_vaa3d_app2`,
`/trace_vaa3d_smartTrace`) accept **only** `file`. The subtree routes accept
**exactly one** of `file` or `tif_path` — providing both or neither returns
`400 Provide exactly one of file or tif_path`.

### Preprocessing

Every uploaded or referenced volume goes through the same normalization before
tracing:

1. Read with `tifffile.imread`.
2. Min-max normalize to `uint8` in `[0, 255]` (`to_uint8_0_255`). A flat
   volume (`max <= min`) becomes all zeros.
3. Assert the array is 3D.
4. Write the normalized `uint8` stack to `vol_uint8.tiff` inside the run
   directory, which is the actual input handed to the tracer.

## Seed Points

Subtree routes require two form fields, `s1` and `s2`, parsed by
`parse_seed_points`. Each describes one or more 3D points in `x, y, z` order.

### Single point

A single point may be written with commas, spaces, or wrapped in brackets or
parentheses — all of these are equivalent:

```text
242.8440,249.8640,7.9980
242.8440 249.8640 7.9980
[242.8440, 249.8640, 7.9980]
(242.8440 249.8640 7.9980)
```

Each point must contain **exactly three** numeric values, otherwise the request
fails with `400 s1[...] must contain exactly 3 numbers` or
`400 s1[...] contains non-numeric values`.

### Multiple points (seed pairs)

To process several seed pairs in one request, send multiple points in both `s1`
and `s2`. Points are separated by `;` (a `|` is also accepted as a separator):

```text
s1=10,20,30;40,50,60
s2=11,20,30;42,50,60
```

This defines two ordered pairs: `(10,20,30) -> (11,20,30)` and
`(40,50,60) -> (42,50,60)`.

### JSON arrays

`s1`/`s2` may instead be JSON. A single point is a flat array of three numbers;
multiple points are a list of triples:

```text
s1=[10,20,30]
s1=[[10,20,30],[40,50,60]]
```

### Pairing rules

`s1` and `s2` are zipped index-by-index into ordered pairs. The following
constraints are enforced (`normalize_seed_pairs`):

| Condition | Result |
| --- | --- |
| `s1` and `s2` have different point counts | `400 s1 and s2 must contain the same number of points` |
| no points supplied | `400 At least one seed pair is required` |
| a pair has `s1 == s2` (zero distance) | `400 s1 and s2 must be different points` |

### Output shape by pair count

| Seed pairs | Response |
| --- | --- |
| exactly 1 | a single `subtree.swc` |
| 2 or more | `subtrees.zip` containing one SWC per pair |

See [Algorithms](algorithms.md) for how each `s1 -> s2` pair is turned into a
directional subtree.
