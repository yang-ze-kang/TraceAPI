"""Kimimaro integration matching neuron-trace/postprocess/trace_kimimaro.py."""
from __future__ import annotations

import argparse
import math
from pathlib import Path
import sys
from typing import Optional

import numpy as np
import tifffile
from fastapi import HTTPException, UploadFile
from starlette.concurrency import run_in_threadpool

from app_helpers import make_workdir, prepare_tif_input, run_cmd
from subtree_utils import parse_seed_point


KIMIMARO_ANISOTROPY = (0.35, 0.35, 1.0)  # x, y, z
KIMIMARO_MAX_ROOT_SNAP_DISTANCE = 4.0
TIFF_EXTENSIONS = {".tif", ".tiff"}


def parse_anisotropy(value: str) -> tuple[float, float, float]:
    spacing_xyz = parse_seed_point(value, "kimimaro_anisotropy")
    if any(not math.isfinite(v) or v <= 0 for v in spacing_xyz):
        raise HTTPException(
            status_code=400,
            detail="kimimaro_anisotropy must contain three finite positive x,y,z spacings",
        )
    return spacing_xyz


def read_volume(path: Path) -> np.ndarray:
    try:
        volume = tifffile.imread(path)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid TIFF: {exc}") from exc
    if volume.ndim != 3 or volume.size == 0 or volume.dtype.kind not in "buif":
        raise HTTPException(
            status_code=400, detail=f"Expected scalar 3D Z,Y,X TIFF, got {volume.shape}",
        )
    if not np.isfinite(volume).all() or np.any(volume < 0):
        raise HTTPException(status_code=400, detail="Intensities must be finite and nonnegative")
    return volume


def volume_shape(path: Path) -> tuple[int, int, int]:
    return tuple(read_volume(path).shape)


async def prepare_kimimaro_input(
    *, file: Optional[UploadFile], tif_path: Optional[str], runs_dir: Path,
) -> tuple[Path, Path, tuple[int, int, int]]:
    workdir = make_workdir(runs_dir)
    image = await prepare_tif_input(
        file=file, tif_path=tif_path, workdir=workdir,
        allowed_ext=TIFF_EXTENSIONS,
    )
    shape_zyx = await run_in_threadpool(volume_shape, image)
    return workdir, image, shape_zyx


def trace_kimimaro(
    image: Path,
    output: Path,
    foreground_thres: float = 0.5,
    kimimaro_anisotropy: tuple[float, float, float] = KIMIMARO_ANISOTROPY,
) -> None:
    """Threshold in original intensity units; export zero-based voxel x,y,z."""
    volume = read_volume(image)
    maximum = float(volume.max())
    # In particular, 0 >= 0 must not turn an empty prediction into foreground.
    if maximum == 0:
        output.write_text("# none\n")
        return

    import kimimaro

    labels = (volume >= foreground_thres * maximum).astype(np.uint8)
    skeletons = kimimaro.skeletonize(
        labels,
        teasar_params={
            "scale": 1.5,
            "const": 10,
            "pdrf_scale": 100000,
            "pdrf_exponent": 2,
            "soma_acceptance_threshold": 3500,
            "soma_detection_threshold": 750,
            "soma_invalidation_const": 300,
            "soma_invalidation_scale": 2,
            "max_paths": 10000,
        },
        dust_threshold=100,
        anisotropy=kimimaro_anisotropy[::-1],  # array axes are z, y, x
        fix_branching=True,
        fix_borders=True,
        fill_holes=False,
        fix_avocados=False,
        progress=False,
        parallel=1,
        parallel_chunk_size=100,
    )
    # Binarization produces one label; its skeleton includes disconnected trees.
    skeleton = skeletons.get(1)
    swc = skeleton.to_swc() if skeleton is not None else "# none"
    spacing_x, spacing_y, spacing_z = kimimaro_anisotropy
    with output.open("w") as stream:
        for row in swc.splitlines():
            fields = row.split()
            if row.lstrip().startswith("#") or not fields:
                stream.write(row + "\n")
                continue
            node_id, node_type, z, y, x, radius, parent_id = fields
            # Preserve the source implementation's physical radius convention.
            stream.write(
                f"{node_id} {node_type} {float(x) / spacing_x} "
                f"{float(y) / spacing_y} {float(z) / spacing_z} {radius} {parent_id}\n"
            )


def run_kimimaro(
    *, workdir: Path, image: Path, foreground_thres: float = 0.5,
    kimimaro_anisotropy: tuple[float, float, float] = KIMIMARO_ANISOTROPY,
    timeout_sec: int = 3000,
) -> Path:
    output = workdir / "output_full.swc"
    command = [
        sys.executable, str(Path(__file__).resolve()),
        "--image", str(image), "--output", str(output),
        "--foreground-thres", str(foreground_thres),
        "--anisotropy", *(str(v) for v in kimimaro_anisotropy),
    ]
    if not run_cmd(command, workdir / "kimimaro.log", workdir, timeout_sec):
        raise HTTPException(status_code=504, detail=f"Kimimaro exceeded {timeout_sec}s")
    if not output.is_file() or output.stat().st_size == 0:
        raise HTTPException(status_code=500, detail="Kimimaro did not generate a valid SWC")
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--foreground-thres", type=float, default=0.5)
    parser.add_argument("--anisotropy", type=float, nargs=3, default=KIMIMARO_ANISOTROPY)
    args = parser.parse_args()
    trace_kimimaro(args.image, args.output, args.foreground_thres, tuple(args.anisotropy))
