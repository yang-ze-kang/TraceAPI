import numpy as np
import subprocess
import tifffile as tiff
from pathlib import Path
from typing import Iterable, List, Optional

from fastapi import HTTPException



def to_uint8_0_255(arr: np.ndarray) -> np.ndarray:
    """
    Convert input array to uint8 in [0, 255].
    """
    arr = np.asarray(arr)

    # General min-max normalization
    arr_f = arr.astype(np.float32, copy=False)
    mn = float(np.min(arr_f))
    mx = float(np.max(arr_f))
    if mx <= mn:
        return np.zeros(arr.shape, dtype=np.uint8)

    out = (arr_f - mn) * (255.0 / (mx - mn))
    out = np.clip(out, 0.0, 255.0).astype(np.uint8)
    return out

def postprocess_vaa3d_result(swc_path, maxy=300):
    res = []
    with open(swc_path, "r") as f:
        for line in f:
            if line.startswith("#") or not line.strip():
                res.append(line)
                continue
            nid, ntype, x, y ,z, r, pid = line.strip().split()
            res.append([
                nid,"0",
                "{:.6f}".format(float(x)),
                "{:.6f}".format(maxy - float(y)),
                "{:.6f}".format(float(z)),
                "{:.6f}".format(float(r)),
                pid
            ])
    with open(swc_path, "w") as f:
        for line in res:
            if isinstance(line, str):
                f.write(line)
            else:
                f.write(" ".join(line) + "\n")