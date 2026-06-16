from __future__ import annotations
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional
from fastapi import FastAPI, File, Form, HTTPException, UploadFile

from app_helpers import (
    check_suffix,
    cleanup_runs_worker,
    ensure_executable,
    file_response_or_500,
    make_workdir,
    prepare_tif_input,
    prepare_trace_volume,
    prepare_trace_volume_input,
    run_cmd,
    save_upload_to,
)
from swclib.data.swc import Swc
from subtree_utils import filter_swc_subtree, normalize_seed_pairs, parse_seed_points, zip_swc_files
from vaa3d_utils import (
    TraceTimeoutError,
    postprocess_vaa3d_result,
    run_trace_iterative_with_noise_mask,
    run_trace_iterative_with_seed_fallback,
    write_marker_file
)



# -----------------------------
# Config
# -----------------------------
ALLOWED_EXT = {".tif", ".tiff", ".png", ".jpg", ".jpeg"}

BASE_DIR = Path(__file__).resolve().parent
RUNS_DIR = BASE_DIR / "runs"

NEUTUBE_BIN = BASE_DIR / "algorithms" / "neuTube"
VAA3D_BIN = BASE_DIR / "algorithms" / "Vaa3D-x.1.1.4_Ubuntu" / "Vaa3D-x"
# VAA3D_BIN = Path("/data1/yangzekang/neuron/Vaa3D-x.1.1.4_Ubuntu/Vaa3D-x")


@asynccontextmanager
async def lifespan(app: FastAPI):
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    t = threading.Thread(target=cleanup_runs_worker, args=(RUNS_DIR,), daemon=True)
    t.start()
    yield


app = FastAPI(lifespan=lifespan)


# -----------------------------
# Routes
# -----------------------------
@app.post("/trace_neutube")
async def trace_neutube(file: UploadFile = File(...)):
    check_suffix(file.filename, ALLOWED_EXT)

    ensure_executable(NEUTUBE_BIN, name="neuTube")

    workdir = make_workdir(RUNS_DIR)
    local_input = workdir / "vol.tiff"
    local_output = workdir / "output.swc"
    local_log = workdir / "log.txt"

    await save_upload_to(file, local_input)

    cmd = [
        str(NEUTUBE_BIN),
        "--command",
        str(local_input),
        "--trace",
        "-o",
        str(local_output),
        "--level",
        "0",
    ]
    run_cmd(cmd, local_log, workdir)

    return file_response_or_500(local_output, filename="output.swc")

@app.post("/trace_neutube_subtree")
async def trace_neutube_subtree(
    file: Optional[UploadFile] = File(None),
    tif_path: Optional[str] = Form(None),
    s1: str = Form(...),
    s2: str = Form(...),
):
    ensure_executable(NEUTUBE_BIN, name="neuTube")

    seed1 = parse_seed_points(s1, "s1")
    seed2 = parse_seed_points(s2, "s2")

    workdir = make_workdir(RUNS_DIR)
    local_input = await prepare_tif_input(
        file=file,
        tif_path=tif_path,
        workdir=workdir,
        allowed_ext=ALLOWED_EXT,
    )
    full_output = workdir / "output_full.swc"
    subtree_output = workdir / "subtree.swc"
    local_log = workdir / "log.txt"

    cmd = [
        str(NEUTUBE_BIN),
        "--command",
        str(local_input),
        "--trace",
        "-o",
        str(full_output),
        "--level",
        "0",
    ]
    run_cmd(cmd, local_log, workdir)

    if not full_output.exists() or full_output.stat().st_size == 0:
        raise HTTPException(status_code=500, detail="neuTube did not generate a valid SWC")

    subtree_outputs = filter_swc_subtree(full_output, subtree_output, seed1, seed2)
    if len(subtree_outputs) == 1:
        return file_response_or_500(subtree_outputs[0], filename="subtree.swc")

    zip_path = workdir / "subtrees.zip"
    return zip_swc_files(subtree_outputs, zip_path)


@app.post("/trace_vaa3d_app2")
async def trace_vaa3d_app2(file: UploadFile = File(...)):
    workdir, _, local_log, img_u8, H = await prepare_trace_volume(
        file,
        vaa3d_bin=VAA3D_BIN,
        runs_dir=RUNS_DIR,
        allowed_ext=ALLOWED_EXT,
    )
    tif_file = workdir / "vol_uint8.tiff"

    # Iterative tracing settings
    max_iters = 32                  # hard stop to avoid infinite loops
    timeout_sec = 3000              # total time budget for the iterative loop
    min_nodes_to_accept = 3         # too tiny outputs are often noise; tune as needed
    max_seed_tries_per_iter = 8

    def _run_app2(out_swc: Path, marker_file: Optional[Path] = None, timeout_sec: int = 3600) -> bool:
        marker_arg = str(marker_file) if marker_file is not None else "None"
        cmd = [
            str(VAA3D_BIN),
            "-x", "vn2",
            "-f", "app2",
            "-i", str(tif_file),
            "-o", str(out_swc),
            "-p",
            marker_arg,        # inmarker_file
            "0",               # channel
            "10",              # bkg_thresh
            "0",               # b_256cube
            "1",               # b_radiusFrom2D
            "0",               # is_gsdt
            "0",               # is_gap
            "5",               # length_thresh
            "1",               # is_resample
            "0",               # is_brightfield
            "0",               # is_high_intensity
        ]
        try:
            run_cmd(cmd, local_log, workdir, timeout_sec)
            if not out_swc.exists() or out_swc.stat().st_size == 0:
                return False
        except TraceTimeoutError:
            raise
        except:
            return False
        postprocess_vaa3d_result(out_swc, maxy=H)
        return True

    merged_swc = run_trace_iterative_with_seed_fallback(
        img_u8=img_u8,
        tif_file=tif_file,
        workdir=workdir,
        max_iters=max_iters,
        timeout_sec=timeout_sec,
        min_nodes_to_accept=min_nodes_to_accept,
        max_seed_tries_per_iter=max_seed_tries_per_iter,
        run_once=_run_app2,
        seed_prefix="app2_seed",
        error_label="APP2",
    )

    return file_response_or_500(merged_swc, filename="output.swc")


@app.post("/trace_vaa3d_app2_subtree")
async def trace_vaa3d_app2_subtree(
    file: Optional[UploadFile] = File(None),
    tif_path: Optional[str] = Form(None),
    s1: str = Form(...),
    s2: str = Form(...),
):
    workdir, _, local_log, img_u8, H = await prepare_trace_volume_input(
        file=file,
        tif_path=tif_path,
        vaa3d_bin=VAA3D_BIN,
        runs_dir=RUNS_DIR,
        allowed_ext=ALLOWED_EXT,
    )
    tif_file = workdir / "vol_uint8.tiff"
    seed_pairs = normalize_seed_pairs(
        parse_seed_points(s1, "s1"),
        parse_seed_points(s2, "s2"),
    )

    # Iterative tracing settings
    timeout_sec = 600

    def _run_app2(out_swc: Path, marker_file: Optional[Path] = None, timeout_sec: int = 3600) -> bool:
        marker_arg = str(marker_file) if marker_file is not None else "None"
        cmd = [
            str(VAA3D_BIN),
            "-x", "vn2",
            "-f", "app2",
            "-i", str(tif_file),
            "-o", str(out_swc),
            "-p",
            marker_arg,        # inmarker_file
            "0",               # channel
            "10",              # bkg_thresh
            "0",               # b_256cube
            "1",               # b_radiusFrom2D
            "0",               # is_gsdt
            "0",               # is_gap
            "5",               # length_thresh
            "1",               # is_resample
            "0",               # is_brightfield
            "0",               # is_high_intensity
        ]
        try:
            run_cmd(cmd, local_log, workdir, timeout_sec)
            if not out_swc.exists() or out_swc.stat().st_size == 0:
                return False
        except TraceTimeoutError:
            raise
        except:
            return False
        postprocess_vaa3d_result(out_swc, maxy=H)
        return True

    D, H, W = img_u8.shape
    subtree_outputs = []
    for idx, (seed1, seed2) in enumerate(seed_pairs):
        marker_file = workdir / f"app2_seed_{idx:03d}.marker"
        full_output = workdir / f"app2_seed_{idx:03d}_full.swc"
        subtree_output = workdir / (
            "subtree.swc" if len(seed_pairs) == 1 else f"subtree_{idx:03d}.swc"
        )

        write_marker_file(marker_file, seed1, D, H, W)
        ok = _run_app2(full_output, marker_file=marker_file, timeout_sec=timeout_sec)
        if not ok or not full_output.exists() or full_output.stat().st_size == 0:
            raise HTTPException(status_code=422, detail=f"APP2 failed for seed pair {idx}")

        subtree_outputs.extend(filter_swc_subtree(full_output, subtree_output, seed1, seed2))

    if len(subtree_outputs) == 1:
        return file_response_or_500(subtree_outputs[0], filename="subtree.swc")

    zip_path = workdir / "subtrees.zip"
    return zip_swc_files(subtree_outputs, zip_path)


@app.post("/trace_vaa3d_smartTrace")
async def trace_vaa3d_smartTrace(file: UploadFile = File(...)):
    workdir, _, local_log, img_u8, H = await prepare_trace_volume(
        file,
        vaa3d_bin=VAA3D_BIN,
        runs_dir=RUNS_DIR,
        allowed_ext=ALLOWED_EXT,
    )
    tif_file = workdir / "vol_uint8.tiff"

    # Iterative tracing settings
    max_iters = 16                  # hard stop to avoid infinite loops
    timeout_sec = 3000              # total time budget for the iterative loop
    min_nodes_to_accept = 3         # too tiny outputs are often noise; tune as needed
    cmd_swc_file = Path(str(tif_file) + "_smartTracing.swc")

    def _run_smarttrace(out_swc: Path, marker_file: Optional[Path] = None, timeout_sec: int = 2400) -> bool:
        cmd = [
            str(VAA3D_BIN),
            "-x", "smartTrace",
            "-f", "smartTrace",
            "-i", str(tif_file),
        ]
        try:
            ok = run_cmd(cmd, local_log, workdir, timeout_sec)
            if not ok:
                swc = Swc()
                swc.save_to_swc(cmd_swc_file)
                return False
            if not cmd_swc_file.exists() or cmd_swc_file.stat().st_size == 0:
                return False
        except TraceTimeoutError:
            raise
        except:
            return False
        cmd_swc_file.rename(out_swc)
        postprocess_vaa3d_result(out_swc, maxy=H)
        return True

    merged_swc = run_trace_iterative_with_noise_mask(
        img_u8=img_u8,
        tif_file=tif_file,
        workdir=workdir,
        max_iters=max_iters,
        timeout_sec=timeout_sec,
        min_nodes_to_accept=min_nodes_to_accept,
        run_once=_run_smarttrace,
        error_label="smartTrace",
    )

    return file_response_or_500(merged_swc, filename="output.swc")


# @app.post("/trace_kimimacro")
# async def trace_kimimacro(file: UploadFile = File(...)):
#     raise HTTPException(status_code=501, detail="Not implemented")
