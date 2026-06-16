from __future__ import annotations

import os
import signal
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import numpy as np
import tifffile as tiff
from fastapi import HTTPException, UploadFile
from fastapi.responses import FileResponse

from vaa3d_utils import to_uint8_0_255


def ensure_executable(path: Path, name: str = "binary") -> None:
    if not path.exists():
        raise HTTPException(status_code=500, detail=f"{name} not found: {path}")
    if not os.access(path, os.X_OK):
        raise HTTPException(status_code=500, detail=f"{name} not executable: {path}")


def cleanup_runs_worker(runs_dir: Path, interval_hours: int = 0.5, max_age_hours: int = 1) -> None:
    """Periodically delete old run directories under runs_dir."""
    while True:
        now = time.time()
        if runs_dir.exists():
            for d in runs_dir.iterdir():
                if not d.is_dir():
                    continue
                age_hours = (now - d.stat().st_mtime) / 3600
                if age_hours > max_age_hours:
                    print(f"[cleanup] removing {d} (age={age_hours:.2f}h)")
                    shutil.rmtree(d, ignore_errors=True)
        time.sleep(int(interval_hours * 3600))


def make_workdir(runs_dir: Path, max_retries: int = 1000) -> Path:
    base_name = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]

    for i in range(max_retries):
        name = base_name if i == 0 else f"{base_name}_{i}"
        workdir = runs_dir / name
        try:
            workdir.mkdir(parents=True, exist_ok=False)
            return workdir
        except FileExistsError:
            continue

    raise RuntimeError(f"Failed to create unique workdir after {max_retries} retries.")


async def save_upload_to(upload: UploadFile, dst: Path) -> None:
    """Save UploadFile to dst, then close upload."""
    try:
        with dst.open("wb") as f:
            shutil.copyfileobj(upload.file, f)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save upload: {e}")
    finally:
        await upload.close()


def check_suffix(filename: str, allowed_ext: set[str]) -> None:
    suffix = Path(filename).suffix.lower()
    if suffix not in allowed_ext:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {suffix}")


async def prepare_tif_input(
    *,
    file: Optional[UploadFile],
    tif_path: Optional[str],
    workdir: Path,
    allowed_ext: set[str],
) -> Path:
    if (file is None) == (not tif_path):
        raise HTTPException(status_code=400, detail="Provide exactly one of file or tif_path")

    if file is not None:
        check_suffix(file.filename or "", allowed_ext)
        local_input = workdir / "vol.tiff"
        await save_upload_to(file, local_input)
        return local_input

    src = Path(str(tif_path)).expanduser()
    check_suffix(src.name, allowed_ext)
    if not src.exists() or not src.is_file():
        raise HTTPException(status_code=400, detail=f"tif_path not found: {src}")

    local_input = workdir / f"vol{src.suffix.lower()}"
    shutil.copyfile(src, local_input)
    return local_input


def run_cmd(cmd: List[str], log_path: Path, workdir: Path, timeout_sec: int = 3600) -> bool:
    """Run a command, writing stdout+stderr to log_path."""
    proc = None
    try:
        with log_path.open("wb") as logf:
            print("[run]", " ".join(cmd))
            proc = subprocess.Popen(
                cmd,
                stdout=logf,
                stderr=subprocess.STDOUT,
                cwd=str(workdir),
                start_new_session=True,
            )
            try:
                proc.wait(timeout=timeout_sec)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait()
                return False

            if proc.returncode != 0:
                try:
                    text = log_path.read_text(errors="ignore")[-5000:]
                except Exception:
                    text = "(failed to read log)"
                raise HTTPException(status_code=500, detail=f"Command failed. Tail log:\n{text}")
    except subprocess.TimeoutExpired:
        return False
    except BaseException:
        if proc is not None and proc.poll() is None:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait()
        raise
    return True


def file_response_or_500(path: Path, filename: str = "output.swc") -> FileResponse:
    if not path.exists() or path.stat().st_size == 0:
        raise HTTPException(status_code=500, detail=f"{filename} not generated or empty")
    return FileResponse(
        path=str(path),
        media_type="application/octet-stream",
        filename=filename,
    )


async def prepare_trace_volume(
    file: UploadFile,
    *,
    vaa3d_bin: Path,
    runs_dir: Path,
    allowed_ext: set[str],
) -> tuple[Path, Path, Path, np.ndarray, int]:
    """Common preprocessing for tracing routes."""
    check_suffix(file.filename, allowed_ext)
    ensure_executable(vaa3d_bin, name="Vaa3D")

    workdir = make_workdir(runs_dir)
    local_input = workdir / "vol.tiff"
    local_log = workdir / "log.txt"
    await save_upload_to(file, local_input)

    img = tiff.imread(local_input)
    img_u8 = to_uint8_0_255(img)
    if img_u8.ndim != 3:
        raise HTTPException(status_code=400, detail=f"Expected 3D volume, got shape={img_u8.shape}")

    _, H, _ = img_u8.shape
    tif_file = workdir / "vol_uint8.tiff"
    tiff.imwrite(tif_file, img_u8)
    return workdir, local_input, local_log, img_u8, H


async def prepare_trace_volume_input(
    *,
    file: Optional[UploadFile],
    tif_path: Optional[str],
    vaa3d_bin: Path,
    runs_dir: Path,
    allowed_ext: set[str],
) -> tuple[Path, Path, Path, np.ndarray, int]:
    """Common preprocessing for tracing routes that accept file or tif_path."""
    ensure_executable(vaa3d_bin, name="Vaa3D")

    workdir = make_workdir(runs_dir)
    local_log = workdir / "log.txt"
    local_input = await prepare_tif_input(
        file=file,
        tif_path=tif_path,
        workdir=workdir,
        allowed_ext=allowed_ext,
    )

    img = tiff.imread(local_input)
    img_u8 = to_uint8_0_255(img)
    if img_u8.ndim != 3:
        raise HTTPException(status_code=400, detail=f"Expected 3D volume, got shape={img_u8.shape}")

    _, H, _ = img_u8.shape
    tif_file = workdir / "vol_uint8.tiff"
    tiff.imwrite(tif_file, img_u8)
    return workdir, local_input, local_log, img_u8, H
