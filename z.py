import trace

import numpy as np
import tifffile as tiff
from pathlib import Path

from vaa3d_utils import *

from app import run_cmd
from swclib.data.swc import Swc, merge_swcs
from swclib.image.swc2mask import swc_to_mask_sphere_cone

ALLOWED_EXT = {".tif", ".tiff", ".png", ".jpg", ".jpeg"}

BASE_DIR = Path(__file__).resolve().parent
RUNS_DIR = BASE_DIR / "runs"

NEUTUBE_BIN = BASE_DIR / "algorithms" / "neuTube"
VAA3D_BIN = BASE_DIR / "algorithms" / "Vaa3D-x.1.1.4_Ubuntu" / "Vaa3D-x"

def trace_vaa3d_smartTrace():
    local_input = Path("/gpfs-flash/hulab/yangzekang/neuron/TraceAPI/runs/4b1c5cff-2918-4d02-9a46-1cf8137ae884/vol.tiff")
    workdir = Path("workdir")
    workdir.mkdir(parents=True, exist_ok=True)
    local_log = workdir / "log.txt"

    # Read & normalize to uint8, then write a temp tiff for Vaa3D
    img = tiff.imread(local_input)
    img_u8 = to_uint8_0_255(img)

    tif_file = workdir / "vol_uint8.tiff"
    tiff.imwrite(tif_file, img_u8)

    D, H, W = img_u8.shape  # noqa: F841

    # Iterative tracing settings
    max_iters = 64                  # hard stop to avoid infinite loops
    min_nodes_to_accept = 3         # too tiny outputs are often noise; tune as needed

    swcs = []
    for it in range(max_iters):
        tiff.imwrite(tif_file, img_u8)

        # swc_file = workdir / f"output_{it:03d}.swc"
        swc_file = str(tif_file) + "_smartTracing.swc"

        cmd = [
            str(VAA3D_BIN),
            "-x", "smartTrace",
            "-f", "smartTrace",
            "-i", str(tif_file.resolve()),
        ]
        print(f"Running Vaa3D smartTrace, iteration {it}...")
        run_cmd(cmd, local_log, workdir)
        print(swc_file)
        postprocess_vaa3d_result(swc_file, maxy=H)
        print(swc_file)

        swc = Swc(swc_file)

        # Stop criteria: empty / no valid nodes / too few nodes
        if (len(swc.nodes) < min_nodes_to_accept):
            break
        swcs.append(swc)
        print(f"Iteration {it}: {len(swcs)}")

        # Mask this traced tree out of the volume, then continue
        mask = swc_to_mask_sphere_cone(
            swc_file,
            shape=(D, H, W),
            foreground_value=1,
            r_scale=3.0
        )
        img_u8[mask>0] = np.uint8(0)

    swc_merged = merge_swcs(swcs)
    merged_swc = workdir / "output.swc"
    swc_merged.save_to_swc(merged_swc)
    breakpoint()

trace_vaa3d_smartTrace()