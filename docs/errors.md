# Errors

All errors are returned as standard FastAPI/Starlette JSON with a `detail`
field:

```json
{ "detail": "Provide exactly one of file or tif_path" }
```

The tables below list every error the service raises, grouped by status code,
with the condition that triggers it.

## 400 — Bad Request

Client input problems. The request never reaches the tracer.

| `detail` | Condition |
| --- | --- |
| `Unsupported file type: <suffix>` | File suffix not in the allowed set. |
| `Provide exactly one of file or tif_path` | Subtree route received both or neither input. |
| `tif_path not found: <path>` | `tif_path` does not exist or is not a regular file. |
| `Expected 3D volume, got shape=<shape>` | Image read as a non-3D array. |
| `<name> cannot be empty` | `s1`/`s2` was an empty string. |
| `<name> must contain exactly 3 numbers` | A seed point did not have 3 components. |
| `<name> contains non-numeric values` | A seed component failed to parse as a float. |
| `<name>[<i>] must contain 3 numbers` | A JSON seed item was not a 3-number array. |
| `At least one seed pair is required` | No seed points were parsed. |
| `s1 and s2 must contain the same number of points` | Mismatched seed counts. |
| `s1 and s2 must be different points` | A pair had zero distance between `s1` and `s2`. |

## 422 — Unprocessable Entity

The tracer ran, but no usable reconstruction could be produced.

| `detail` | Condition |
| --- | --- |
| `<label> failed for auto and candidate seeds.` | APP2 iterative tracing produced no accepted SWC (auto + seed fallback). |
| `APP2 failed for seed pair <i>` | APP2 subtree route could not trace from a given `s1` marker. |
| `Resampled SWC has no root` | Resampling collapsed the tree to nothing. |
| `Resampled SWC has no valid target node` | No node near `s2` after resampling. |

!!! note "No node near s1"
    When subtree extraction finds no traced node near `s1`, it does **not**
    raise `422`. It returns a canonical empty (0-node) SWC so a single bad seed
    never fails a batch. The file is a valid SWC that parses to zero nodes —
    check the node count to detect this case.

!!! note "smartTrace failure mode"
    `/trace_vaa3d_smartTrace` does not raise `422` when nothing is traced. It
    merges whatever SWCs were accepted (possibly an empty SWC) and returns the
    file. If the result is empty, the final `500 output.swc not generated or
    empty` check applies instead.

## 500 — Internal Server Error

Server/environment problems or a failed external command.

| `detail` | Condition |
| --- | --- |
| `<name> not found: <path>` | A tracer binary is missing. |
| `<name> not executable: <path>` | A tracer binary lacks the execute bit. |
| `Failed to save upload: <error>` | Writing the uploaded file failed. |
| `Command failed. Tail log:\n<...>` | A tracer exited with a non-zero status; the last ~5000 chars of the run log are included. |
| `output.swc not generated or empty` | The expected output file is missing or zero bytes. |
| `subtree.swc not generated or empty` | A subtree output is missing or zero bytes. |
| `<name> not generated or empty` | A file destined for the ZIP was missing or empty. |

## Timeouts

Each tracer invocation runs under a timeout. The iterative loops also enforce a
total time budget (`timeout_sec`). When a tracing iteration exceeds its budget
the loop stops early and returns whatever has been accepted so far rather than
erroring — see [Algorithms](algorithms.md). A single command that exceeds its
own subprocess timeout is killed; the loop treats that iteration as producing no
output.
