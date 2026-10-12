# Algorithms

This page describes what happens inside each tracing route: image preprocessing,
the iterative tracing loops, and directional subtree extraction. The behavior
described here comes from `app.py`, `vaa3d_utils.py`, and `subtree_utils.py`.

## Coordinate Conventions

Images are read as `(Z, Y, X)` (`D, H, W`) arrays. Seed points are given as
`x, y, z`.

Vaa3D writes SWC coordinates with a flipped Y axis relative to the input stack.
After every Vaa3D trace, `postprocess_vaa3d_result` rewrites each node's `y` to
`H - 1 - y` and forces the node type to `0`, bringing the SWC back into the
image coordinate frame. neuTube output is not flipped.

Markers handed to Vaa3D APP2 are written with the same flip
(`write_marker_file`): `x+1`, `H - y`, `z+1`, each clamped into the volume
bounds.

## Preprocessing

The Vaa3D routes normalize the input before tracing:

1. Read the volume with `tifffile`.
2. Min-max scale to `uint8` `[0, 255]` (`to_uint8_0_255`).
3. Require a 3D array.
4. Write `vol_uint8.tiff` into the run directory as the tracer input.

## Kimimaro (`/trace_kimimaro`, `/trace_kimimaro_subtree`)

The backend follows `neuron-trace/postprocess/trace_kimimaro.py`, called by
`skeleton.py` for the Kimimaro method:

1. Read a nonnegative, finite 3D Z,Y,X TIFF without intensity normalization.
2. Binarize at `foreground_thres * max(volume)` (default `0.5`). All-zero input
   produces an empty SWC instead of treating zero background as foreground.
3. Skeletonize with the original TEASAR settings (`scale=1.5`, `const=10`,
   `pdrf_scale=100000`, `pdrf_exponent=2`, `max_paths=10000`), dust threshold
   100, fixed branches/borders, and one worker.
4. Reverse X,Y,Z anisotropy (default `0.35,0.35,1.0`) for the Z,Y,X array.
   Convert the resulting physical Z,Y,X positions back to voxel X,Y,Z SWC
   coordinates; preserve physical radii and do not flip Y.
5. For subtrees, apply the shared directional filter to the full reconstruction
   for each seed pair, with a 4-voxel root-snap limit and 2-voxel resampling.
   Subtree radii are 1, as in the other subtree endpoints.

Each request uses a subprocess with a 3000 s whole-volume or 600 s subtree
timeout. Multiple pairs reuse the same skeleton and return a ZIP archive.

## neuTube (`/trace_neutube`, `/trace_neutube_subtree`)

neuTube is invoked once per request:

```text
neuTube --command <input> --trace -o <output.swc> --level 0
```

There is no iterative masking loop for neuTube. The traced SWC is returned
directly (plain route) or fed into subtree extraction (subtree route).

## Vaa3D APP2 — full volume (`/trace_vaa3d_app2`)

APP2 is run iteratively to recover multiple neurites
(`run_trace_iterative_with_seed_fallback`):

- **Settings:** `max_iters=32`, `timeout_sec=3000`, `min_nodes_to_accept=3`,
  `max_seed_tries_per_iter=8`.
- Each iteration runs APP2 on the current (progressively masked) volume.
- **Auto mode:** APP2 runs with no marker. If it yields nodes, they are kept.
- **Seed-fallback mode:** if auto tracing yields zero nodes while meaningful
  foreground remains (`>20` non-zero voxels), the loop switches to seeded
  tracing. A candidate seed pool is built from distance-transform / intensity
  local maxima (`build_neutube_like_seed_pool`), and up to
  `max_seed_tries_per_iter` seeds are tried per iteration until one produces a
  trace.
- **Acceptance:** an iteration's SWC is kept only if it has at least
  `min_nodes_to_accept` nodes and total length `>= 3.0`.
- **Masking:** the traced tree is rasterized to a sphere/cone mask
  (`swc_to_mask_sphere_cone`, `r_scale=3.0`) and erased from the volume so the
  next iteration finds different structure. Covered candidate seeds are dropped.
- The loop ends when an iteration produces no nodes, `max_iters` is reached, or
  the time budget expires.

All accepted SWCs are merged (`merge_swcs`) into `output.swc`. If nothing was
accepted, the route returns `422`.

### APP2 parameters

The APP2 plugin is called as:

```text
Vaa3D-x -x vn2 -f app2 -i <vol_uint8.tiff> -o <out.swc> -p \
  <marker|None> 0 10 0 1 0 0 5 1 0 0
```

| Position | Value | Meaning |
| --- | --- | --- |
| 1 | `<marker>` / `None` | input marker file |
| 2 | `0` | channel |
| 3 | `10` | background threshold |
| 4 | `0` | `b_256cube` |
| 5 | `1` | `b_radiusFrom2D` |
| 6 | `0` | `is_gsdt` |
| 7 | `0` | `is_gap` |
| 8 | `5` | length threshold |
| 9 | `1` | `is_resample` |
| 10 | `0` | `is_brightfield` |
| 11 | `0` | `is_high_intensity` |

## Vaa3D APP2 — subtree (`/trace_vaa3d_app2_subtree`)

This route does **not** use the iterative loop. For each seed pair it:

1. Writes a marker file at `s1`.
2. Runs APP2 once from that marker (`timeout_sec=600`).
3. Extracts the directional subtree (see below).

If APP2 fails for any pair the request returns `422 APP2 failed for seed pair
<i>`.

## Vaa3D smartTrace (`/trace_vaa3d_smartTrace`)

smartTrace runs iteratively with a denoise fallback
(`run_trace_iterative_with_noise_mask`):

- **Settings:** `max_iters=16`, `timeout_sec=3000`, `min_nodes_to_accept=3`.
- Each iteration runs smartTrace, which writes `<input>_smartTracing.swc`; that
  file is renamed to the iteration output.
- **Denoise fallback:** if an iteration yields zero nodes while foreground
  remains (`>10` non-zero voxels), tiny/compact connected components are removed
  once (`denoise_foreground_components_inplace`) and the iteration retries.
- **Acceptance / masking:** same node-count and length rules and the same
  sphere/cone masking as APP2.
- Unlike APP2, if nothing is accepted this route still returns a (possibly
  empty) merged `output.swc` rather than raising `422`.

## Directional Subtree Extraction

For each ordered pair `s1 -> s2`, `filter_one_swc_subtree` turns a full
reconstruction into the single branch leaving `s1` toward `s2`:

1. Compute `sample_distance = ||s1 - s2||`; reject if zero.
2. Find the SWC node nearest `s1`. If none exists, return a canonical empty
   (0-node) SWC for this pair instead of failing.
3. Reroot the tree at that node (`get_rerooted_tree`).
4. Resample the rerooted tree with spacing equal to `sample_distance`
   (`resample`), saved without header and reindexed.
5. Among the root's children, keep only the child branch whose direction best
   aligns with the target direction — the smallest angle (`angle_between_vectors`)
   between the child's `root -> child` vector and the `root -> s2` vector.
   Detach the other branches.
6. Save the resulting subtree.

The target direction is measured from the branch point (the resampled root, the
node nearest `s1`), not from `s1` itself, so both vectors share an origin.
Degenerate (zero-length) child vectors and any `NaN` angle from floating-point
error are treated as the worst case and never selected.

A single pair yields `subtree.swc`; multiple pairs are zipped into
`subtrees.zip` (`zip_swc_files`), which rejects any missing or empty member with
`500`.

## Run Directories & Cleanup

Each request gets a timestamped working directory under `runs/` (`make_workdir`)
holding the normalized volume, intermediate SWCs, markers, and `log.txt`. A
background thread (`cleanup_runs_worker`) started at app startup deletes run
directories older than 1 hour, checking every 30 minutes.
