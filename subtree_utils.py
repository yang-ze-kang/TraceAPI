from __future__ import annotations

import json
import zipfile
from pathlib import Path

from fastapi import HTTPException
from fastapi.responses import FileResponse
from swclib.data.swc import Swc
from swclib.data.swc_forest import SwcForest


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
) -> Path:
    swc_name = Path(forest.name() or "input.swc").name
    sample_distance = sum((a - b) ** 2 for a, b in zip(s1, s2)) ** 0.5
    if sample_distance <= 0:
        raise HTTPException(status_code=400, detail="s1 and s2 must be different points")

    start_node, _ = forest.get_nearest_node(s1)
    if start_node is None:
        raise HTTPException(status_code=422, detail=f"No valid SWC nodes found in {swc_name}")

    rerooted_root = start_node.get_rerooted_tree(nid_start=1)
    rerooted_path = out_path.with_name(f"{out_path.stem}_rerooted.swc")
    resampled_path = out_path.with_name(f"{out_path.stem}_rerooted_resampled.swc")
    rerooted_root.get_subtree(nid_start=1).save_to_file(rerooted_path)

    rerooted_swc = Swc(rerooted_path)
    resampled_swc = rerooted_swc.resample(min_distance=sample_distance, in_place=False)
    resampled_swc.save_to_swc(
        str(resampled_path),
        write_header=False,
        reindex=True,
        radius=1,
    )

    resampled_forest = SwcForest(resampled_path)
    roots = resampled_forest.get_roots()
    if len(roots) == 0:
        raise HTTPException(status_code=422, detail="Resampled SWC has no root")

    rerooted_root = roots[0]
    target_node, _ = resampled_forest.get_nearest_node(s2)
    if target_node is None:
        raise HTTPException(status_code=422, detail="Resampled SWC has no valid target node")

    if len(rerooted_root.children) > 0:
        branch_root = min(
            rerooted_root.children,
            key=lambda child: child.distance(target_node),
        )
        for child in tuple(rerooted_root.children):
            if child is not branch_root:
                child.parent = None

    subtree = rerooted_root.get_subtree(nid_start=1)
    subtree.save_to_file(out_path)
    return out_path


def filter_swc_subtree(
    swc_path: Path,
    out_path: Path,
    s1: tuple[float, float, float] | list[tuple[float, float, float]],
    s2: tuple[float, float, float] | list[tuple[float, float, float]],
) -> list[Path]:
    seed_pairs = normalize_seed_pairs(s1, s2)
    forest = SwcForest(swc_path)
    suffix = out_path.suffix or ".swc"
    output_paths = []
    for idx, (seed1, seed2) in enumerate(seed_pairs):
        cur_out = out_path if len(seed_pairs) == 1 else out_path.with_name(f"{out_path.stem}_{idx:03d}{suffix}")
        output_paths.append(filter_one_swc_subtree(forest, cur_out, seed1, seed2))
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
