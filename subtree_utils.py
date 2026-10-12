from __future__ import annotations

import json
import math
import zipfile
from pathlib import Path

import numpy as np
from fastapi import HTTPException
from fastapi.responses import FileResponse
from swclib.data.swc import Swc
from swclib.data.swc_forest import SwcForest
from swclib.geometry.Transformations import angle_between_vectors


SUBTREE_RESAMPLE_DISTANCE = 2.0
NEUTUBE_MAX_ROOT_SNAP_DISTANCE = 4.0
APP2_MAX_ROOT_SNAP_DISTANCE = 8.0


def parse_seed_point(value: str, name: str) -> tuple[float, float, float]:
    """Parse a seed point from 'x,y,z', 'x y z', or '[x,y,z]'."""
    cleaned = value.strip()
    for ch in "[]()":
        cleaned = cleaned.replace(ch, " ")
    cleaned = cleaned.replace(",", " ")
    parts = [p for p in cleaned.split() if p]
    if len(parts) != 3:
        raise HTTPException(status_code=400, detail=f"{name} must contain exactly 3 numbers")
    try:
        return float(parts[0]), float(parts[1]), float(parts[2])
    except ValueError:
        raise HTTPException(status_code=400, detail=f"{name} contains non-numeric values")


def parse_seed_points(value: str, name: str) -> list[tuple[float, float, float]]:
    """Parse one or more seed points from JSON or ';'-separated triples."""
    cleaned = value.strip()
    if not cleaned:
        raise HTTPException(status_code=400, detail=f"{name} cannot be empty")

    if cleaned.startswith("["):
        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError:
            data = None
        if data is not None:
            if (
                isinstance(data, list)
                and len(data) == 3
                and all(isinstance(v, (int, float)) for v in data)
            ):
                return [(float(data[0]), float(data[1]), float(data[2]))]
            if isinstance(data, list):
                points = []
                for idx, item in enumerate(data):
                    if not (
                        isinstance(item, list)
                        and len(item) == 3
                        and all(isinstance(v, (int, float)) for v in item)
                    ):
                        raise HTTPException(status_code=400, detail=f"{name}[{idx}] must contain 3 numbers")
                    points.append((float(item[0]), float(item[1]), float(item[2])))
                if points:
                    return points

    return [
        parse_seed_point(part, f"{name}[{idx}]")
        for idx, part in enumerate(cleaned.replace("|", ";").split(";"))
        if part.strip()
    ]


def normalize_seed_pairs(
    s1: tuple[float, float, float] | list[tuple[float, float, float]],
    s2: tuple[float, float, float] | list[tuple[float, float, float]],
) -> list[tuple[tuple[float, float, float], tuple[float, float, float]]]:
    s1_points = [s1] if isinstance(s1, tuple) else s1
    s2_points = [s2] if isinstance(s2, tuple) else s2
    if len(s1_points) == 0:
        raise HTTPException(status_code=400, detail="At least one seed pair is required")
    if len(s1_points) != len(s2_points):
        raise HTTPException(status_code=400, detail="s1 and s2 must contain the same number of points")
    return list(zip(s1_points, s2_points))


def filter_one_swc_subtree(
    forest: SwcForest,
    out_path: Path,
    s1: tuple[float, float, float],
    s2: tuple[float, float, float],
    *,
    max_root_snap_distance: float = NEUTUBE_MAX_ROOT_SNAP_DISTANCE,
) -> Path:
    if math.dist(s1, s2) <= 0:
        raise HTTPException(status_code=400, detail="s1 and s2 must be different points")

    start_node, start_distance = forest.get_nearest_node(s1)
    if start_node is None or start_distance > max_root_snap_distance:
        # Do not create a long artificial edge from the supplied seed to an
        # unrelated traced component. A canonical empty SWC lets batched
        # requests continue while keeping the miss detectable by evaluation.
        Swc().save_to_swc(str(out_path))
        return out_path

    rerooted_root = start_node.get_rerooted_tree(nid_start=1)
    for axis, value in enumerate(s1):
        rerooted_root[axis] = float(value)

    root_coord = tuple(float(value) for value in s1)
    target_vec = np.asarray([b - a for a, b in zip(root_coord, s2)], dtype=float)

    if len(rerooted_root.children) > 0 and float(np.dot(target_vec, target_vec)) > 0:
        def branch_angle(child) -> float:
            child_vec = np.asarray((
                float(child[0]) - root_coord[0],
                float(child[1]) - root_coord[1],
                float(child[2]) - root_coord[2],
            ), dtype=float)
            if float(np.dot(child_vec, child_vec)) <= 0:
                return float("inf")
            angle = float(angle_between_vectors(child_vec, target_vec))
            # arccos can return NaN from float error pushing |cos| slightly > 1;
            # treat as the worst angle so it is never selected by min().
            return float("inf") if math.isnan(angle) else angle

        branch_root = min(
            rerooted_root.children,
            key=branch_angle,
        )
        for child in tuple(rerooted_root.children):
            if child is not branch_root:
                child.parent = None

    anchored_path = out_path.with_name(f"{out_path.stem}_anchored.swc")
    rerooted_root.get_subtree(nid_start=1).save_to_file(anchored_path)
    resampled_subtree = Swc(anchored_path).resample(
        min_distance=SUBTREE_RESAMPLE_DISTANCE,
        in_place=False,
    )
    resampled_subtree.save_to_swc(
        str(out_path),
        write_header=False,
        float_fmt=".13e",
        reindex=True,
        radius=1,
    )
    return out_path


def filter_swc_subtree(
    swc_path: Path,
    out_path: Path,
    s1: tuple[float, float, float] | list[tuple[float, float, float]],
    s2: tuple[float, float, float] | list[tuple[float, float, float]],
    *,
    max_root_snap_distance: float = NEUTUBE_MAX_ROOT_SNAP_DISTANCE,
) -> list[Path]:
    seed_pairs = normalize_seed_pairs(s1, s2)
    # First make the auto-traced tree spatially dense enough that nearest-node
    # selection is not determined by the backend's arbitrary node spacing.
    resampled_swc = Swc(swc_path).resample(
        min_distance=SUBTREE_RESAMPLE_DISTANCE,
        in_place=False,
    )
    forest = SwcForest(resampled_swc)
    suffix = out_path.suffix or ".swc"
    output_paths = []
    for idx, (seed1, seed2) in enumerate(seed_pairs):
        cur_out = out_path if len(seed_pairs) == 1 else out_path.with_name(f"{out_path.stem}_{idx:03d}{suffix}")
        output_paths.append(
            filter_one_swc_subtree(
                forest,
                cur_out,
                seed1,
                seed2,
                max_root_snap_distance=max_root_snap_distance,
            )
        )
    return output_paths


def zip_swc_files(paths: list[Path], zip_path: Path) -> FileResponse:
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in paths:
            if not path.exists() or path.stat().st_size == 0:
                raise HTTPException(status_code=500, detail=f"{path.name} not generated or empty")
            zf.write(path, arcname=path.name)
    return FileResponse(
        path=str(zip_path),
        media_type="application/zip",
        filename=zip_path.name,
    )
