"""SPE-DNR subprocess integration; preserve image and VNet map intensities."""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import sys
from typing import Optional

import numpy as np
import tifffile
from fastapi import HTTPException, UploadFile
from starlette.concurrency import run_in_threadpool

from app_helpers import make_workdir, prepare_tif_input, run_cmd


TIFF_EXTENSIONS = {'.tif', '.tiff'}
SPE_DNR_MAX_ROOT_SNAP_DISTANCE = 8.0


def validate_volume(path: Path, name: str, shape=None, probability=False) -> tuple[int, int, int]:
    try:
        volume = tifffile.imread(path)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f'{name}: invalid TIFF ({exc})') from exc
    if volume.ndim != 3 or min(volume.shape) < 3:
        raise HTTPException(status_code=400, detail=f'{name}: expected scalar 3D Z,Y,X TIFF, got {volume.shape}')
    if not np.isfinite(volume).all() or np.any(volume < 0):
        raise HTTPException(status_code=400, detail=f'{name}: intensities must be finite and nonnegative')
    if shape is not None and tuple(volume.shape) != tuple(shape):
        raise HTTPException(status_code=400, detail=f'{name}: shape {volume.shape} does not match image {shape}')
    if probability and np.max(volume) > 255:
        raise HTTPException(status_code=400, detail=f'{name}: expected VNet probabilities in [0,1] or scores in [0,255]')
    return tuple(volume.shape)


async def prepare_spe_dnr_inputs(
    *, file: Optional[UploadFile], tif_path: Optional[str],
    mask_file: Optional[UploadFile], mask_path: Optional[str],
    soma_file: Optional[UploadFile], soma_path: Optional[str], runs_dir: Path,
) -> tuple[Path, Path, Path, Optional[Path], tuple[int, int, int]]:
    if (mask_file is None) == (not mask_path):
        raise HTTPException(status_code=400, detail='Provide exactly one of mask_file or mask_path (VNet prediction)')
    if soma_file is not None and soma_path:
        raise HTTPException(status_code=400, detail='Provide only one of soma_file or soma_path')
    workdir = make_workdir(runs_dir)
    image = await prepare_tif_input(file=file, tif_path=tif_path, workdir=workdir, allowed_ext=TIFF_EXTENSIONS)
    mask_dir = workdir / 'vnet_mask'
    mask_dir.mkdir()
    mask = await prepare_tif_input(file=mask_file, tif_path=mask_path, workdir=mask_dir, allowed_ext=TIFF_EXTENSIONS)
    shape = await run_in_threadpool(validate_volume, image, 'image')
    await run_in_threadpool(validate_volume, mask, 'VNet mask', shape, True)
    soma = None
    if soma_file is not None or soma_path:
        soma_dir = workdir / 'soma_mask'
        soma_dir.mkdir()
        soma = await prepare_tif_input(file=soma_file, tif_path=soma_path, workdir=soma_dir, allowed_ext=TIFF_EXTENSIONS)
        await run_in_threadpool(validate_volume, soma, 'soma mask', shape)
    return workdir, image, mask, soma, shape


def validate_seed_pairs(seed_pairs, shape: tuple[int, int, int]) -> None:
    """Seeds are continuous SWC positions, not integer array indices.

    CWMBS boundary annotations can lie between size-1 and size. These points
    only anchor/filter the reconstructed tree; they never index image arrays.
    Preserve their coordinates and accept the half-open extent [0, size).
    """
    bounds = shape[::-1]
    for index, (s1, s2) in enumerate(seed_pairs):
        for name, point in [('s1', s1), ('s2', s2)]:
            if any(not math.isfinite(v) or v < 0 or v >= size for v, size in zip(point, bounds)):
                raise HTTPException(status_code=400, detail=(
                    f'{name}[{index}]={point} must contain finite continuous x,y,z '
                    f'with 0 <= coordinate < image size {bounds}'
                ))
        if math.dist(s1, s2) == 0:
            raise HTTPException(status_code=400, detail=f's1[{index}] and s2[{index}] must be different points')


def run_spe_dnr(
    *, project_dir: Path, workdir: Path, image: Path, mask: Path,
    soma: Optional[Path] = None, timeout_sec: int = 600,
) -> Path:
    entry = project_dir / 'infer.py'
    if not entry.is_file():
        raise HTTPException(status_code=500, detail=f'Bundled SPE-DNR entry point not found: {entry}')
    weights = project_dir / 'checkpoint' / 'classification_checkpoints' / 'weight.pkl'
    if not weights.is_file():
        raise HTTPException(status_code=500, detail=f'Bundled SPE-DNR weights not found: {weights}')
    output_dir = workdir / 'prediction'
    command = [sys.executable, str(entry), '--weights', str(weights),
               '--image', str(image), '--mask', str(mask), '--seed-mode', 'vnet',
               '--output', str(output_dir), '--coordinate-origin', '0',
               '--device', os.environ.get('SPE_DNR_DEVICE', 'auto')]
    if soma is not None:
        command += ['--soma-mask', str(soma)]
    # Existing subprocess helper kills the entire process group on timeout.
    if not run_cmd(command, workdir / 'spe_dnr.log', workdir, timeout_sec):
        raise HTTPException(status_code=504, detail=f'SPE-DNR exceeded {timeout_sec}s')
    output = output_dir / f'{image.stem}.swc'
    metadata = output_dir / f'{image.stem}.json'
    if not output.is_file() or not metadata.is_file():
        raise HTTPException(status_code=500, detail='SPE-DNR did not generate output and metadata')
    record = json.loads(metadata.read_text())
    if record.get('status') not in ('ok', 'empty'):
        raise HTTPException(status_code=500, detail='SPE-DNR failed; see run log')
    return output
