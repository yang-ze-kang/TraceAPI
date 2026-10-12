from __future__ import annotations

import math
import sys
from pathlib import Path


TRACEAPI_ROOT = Path(__file__).resolve().parents[1]
if str(TRACEAPI_ROOT) not in sys.path:
    sys.path.insert(0, str(TRACEAPI_ROOT))

from subtree_utils import APP2_MAX_ROOT_SNAP_DISTANCE, filter_swc_subtree
from swclib.data.swc import Swc


def _write_sparse_line(path: Path) -> None:
    path.write_text(
        "1 2 0 0 0 1 -1\n"
        "2 2 10 0 0 1 1\n"
    )


def _root_xyz(swc: Swc) -> tuple[float, float, float]:
    root_ids = swc.get_roots(return_coords=False)
    assert len(root_ids) == 1
    root = swc.nodes[root_ids[0]]
    return float(root["x"]), float(root["y"]), float(root["z"])


def test_resamples_before_nearest_node_and_anchors_exact_seed(tmp_path: Path) -> None:
    source = tmp_path / "source.swc"
    output = tmp_path / "output.swc"
    _write_sparse_line(source)

    seed = (4.1, 0.0, 0.0)
    filter_swc_subtree(source, output, seed, (6.1, 0.0, 0.0))

    result = Swc(output)
    assert _root_xyz(result) == seed
    for child_id, parent_id in result.edges:
        if parent_id == -1:
            continue
        child = result.nodes[child_id]
        parent = result.nodes[parent_id]
        child_xyz = (child["x"], child["y"], child["z"])
        parent_xyz = (parent["x"], parent["y"], parent["z"])
        assert math.dist(child_xyz, parent_xyz) <= 2.0 + 1e-6


def test_returns_empty_swc_when_nearest_trace_is_too_far(tmp_path: Path) -> None:
    source = tmp_path / "source.swc"
    output = tmp_path / "output.swc"
    _write_sparse_line(source)

    filter_swc_subtree(source, output, (20.0, 0.0, 0.0), (22.0, 0.0, 0.0))

    assert len(Swc(output).nodes) == 0


def test_app2_threshold_keeps_seeded_trace_after_root_pruning(tmp_path: Path) -> None:
    source = tmp_path / "app2_full.swc"
    output = tmp_path / "output.swc"
    source.write_text(
        "1 0 245.5350 243.5454 8.0 2.0 -1\n"
        "2 0 250.3890 234.8478 8.0 2.8 1\n"
        "3 0 254.8900 225.9939 8.0 2.0 2\n"
        "4 0 255.0000 216.0000 8.0 1.0 3\n"
    )
    seed = (242.844, 249.864, 7.998)

    filter_swc_subtree(
        source,
        output,
        seed,
        (243.5728, 248.0015, 7.998),
        max_root_snap_distance=APP2_MAX_ROOT_SNAP_DISTANCE,
    )

    result = Swc(output)
    assert len(result.nodes) > 0
    assert _root_xyz(result) == seed
