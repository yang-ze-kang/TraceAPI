"""Input, image-only seed fallback and SWC export for the official tracer."""
from collections import deque
import csv
import json
from pathlib import Path

import numpy as np
from scipy import ndimage as ndi
from skimage.filters import threshold_otsu
from skimage.morphology import remove_small_objects, skeletonize
import tifffile


def read_manifest(path, data_root=None):
    """Consume only image column. Never open annotations or annotation masks."""
    path = Path(path).resolve()
    roots = [Path(data_root).resolve()] if data_root else [path.parent, path.parent.parent]
    samples, seen = [], set()
    with path.open(encoding='utf-8-sig', newline='') as stream:
        for line, row in enumerate(csv.reader(stream), 1):
            if not row or not row[0].strip() or row[0].lstrip().startswith('#'):
                continue
            name = row[0].strip()
            if name.lower() in ('image', 'image_path'):
                continue
            item = Path(name).expanduser()
            candidates = [item] if item.is_absolute() else [root / item for root in roots]
            existing = {p.resolve() for p in candidates if p.is_file()}
            if not existing:
                raise FileNotFoundError(f'{path}:{line}: image not found: {name}; tried {candidates}')
            if len(existing) > 1:
                raise ValueError(f'{path}:{line}: ambiguous image path; specify --data-root')
            image = existing.pop()
            key = image.stem
            if key in seen:
                raise ValueError(f'{path}:{line}: duplicate output name {key!r}')
            seen.add(key)
            samples.append((key, image))
    if not samples:
        raise ValueError(f'No images in {path}')
    return samples


def read_volume(path):
    volume = tifffile.imread(path)
    if volume.ndim != 3 or min(volume.shape) < 3:
        raise ValueError(f'{path}: expected scalar Z,Y,X volume with dimensions >=3; got {volume.shape}')
    if not np.isfinite(volume).all():
        raise ValueError(f'{path}: non-finite intensities')
    return volume


def image_seeds(image, spacing=3, threshold=None, max_seeds=0):
    """Image-only fallback, NOT the unpublished V-Net centerline detector."""
    smooth = ndi.gaussian_filter(image, sigma=0.6)
    median = float(np.median(smooth))
    mad = float(np.median(np.abs(smooth - median)))
    cutoff = float(threshold) if threshold is not None else max(
        float(threshold_otsu(smooth)), median + 4 * 1.4826 * mad)
    foreground = remove_small_objects(smooth > cutoff, min_size=8)
    centerline = skeletonize(foreground, method='lee') > 0
    centerline[[0, -1], :, :] = False
    centerline[:, [0, -1], :] = False
    centerline[:, :, [0, -1]] = False
    positions = np.argwhere(centerline)
    if not len(positions):
        return np.empty((0, 4)), cutoff
    values = smooth[tuple(positions.T)]
    order = np.argsort(-values, kind='stable')
    occupied, keep = set(), []
    for i in order:
        point = tuple(int(x) for x in positions[i])
        if point in occupied:
            continue
        keep.append(i)
        z, y, x = point
        for dz in range(-spacing + 1, spacing):
            for dy in range(-spacing + 1, spacing):
                for dx in range(-spacing + 1, spacing):
                    if dz*dz + dy*dy + dx*dx < spacing*spacing:
                        occupied.add((z+dz, y+dy, x+dx))
        if max_seeds and len(keep) >= max_seeds:
            break
    positions = positions[keep]
    # Proxy confidence for joint decision, not a V-Net probability.
    high = max(float(values.max()), cutoff + 1e-6)
    scores = 128 + 127 * np.clip((values[keep] - cutoff) / (high - cutoff), 0, 1)
    return np.column_stack((positions[:, 1], positions[:, 2], positions[:, 0], scores)), cutoff


def map_seeds(path, shape, max_seeds=0):
    """Paper II-B: probability >0.5 and 3x3x3 local maximum, no thinning.

    Preserve probabilities (scaled by 255 for the upstream joint decision).
    Binary masks are supported, but have unit confidence on all foreground
    plateaus and cannot recover the original centerline probabilities.
    """
    seed_map = read_volume(path).astype(np.float32)
    if seed_map.shape != shape:
        raise ValueError(f'{path}: seed map shape {seed_map.shape} != image {shape}')
    if seed_map.min() < 0 or seed_map.max() > 255:
        raise ValueError('Seed maps must contain probabilities in [0,1] or scores in [0,255]')
    if seed_map.max() <= 1:
        seed_map *= 255
    maxima = (seed_map > 127.5) & (seed_map == ndi.maximum_filter(seed_map, size=3))
    maxima[[0, -1], :, :] = False
    maxima[:, [0, -1], :] = False
    maxima[:, :, [0, -1]] = False
    points = np.argwhere(maxima)
    values = seed_map[tuple(points.T)]
    # Same ordering as upstream local_max + flipud(argsort).
    order = np.argsort(values)[::-1]
    if max_seeds:
        order = order[:max_seeds]
    points, values = points[order], values[order]
    return np.column_stack((points[:, 1], points[:, 2], points[:, 0], values))


def find_aux(directory, key, suffix):
    directory = Path(directory)
    names = [f'{key}{suffix}', key]
    if suffix == '_seg':
        names += [f'{key}_mask', f'{key}.tif_mask', f'{key}.tiff_mask']
    matches = [directory / (name + ext) for name in names for ext in ('.tif', '.tiff')
               if (directory / (name + ext)).is_file()]
    if len(matches) > 1:
        raise ValueError(f'Ambiguous {suffix} maps for {key}: {matches}')
    if matches:
        return matches[0]
    raise FileNotFoundError(f'No {suffix} TIFF for {key} in {directory}')


def graph_to_swc(nodes, padding=10, origin=0, largest_tree=False):
    """BFS spanning forest with valid parent IDs and standard SWC types."""
    visited, components = set(), []
    starts = [i for i, node in enumerate(nodes) if node.node_type == 1]
    starts.extend(i for i, node in enumerate(nodes) if node.node_type != 1)
    for start in starts:
        if start in visited:
            continue
        queue = deque([(start, -1)])
        visited.add(start)
        rows = []
        while queue:
            index, parent = queue.popleft()
            node = nodes[index]
            ident = len(rows) + 1
            y, x, z = np.asarray(node.position) - padding + origin
            rows.append([ident, 1 if node.node_type == 1 else 3, x, y, z,
                         max(float(node.radius), 0.01), parent])
            for neighbor in node.nbr:
                neighbor = int(neighbor)
                if not 0 <= neighbor < len(nodes):
                    raise ValueError(f'Invalid graph neighbor {neighbor}')
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append((neighbor, ident))
        components.append(np.asarray(rows, dtype=float))
    if largest_tree and components:
        components = [max(components, key=len)]
    offset = 0
    for component in components:
        component[:, 0] += offset
        component[component[:, 6] != -1, 6] += offset
        offset += len(component)
    return np.vstack(components) if components else np.empty((0, 7))


def validate_swc(swc, shape, origin):
    if swc.shape[1:] != (7,) or not np.isfinite(swc).all():
        raise ValueError('Invalid SWC shape or non-finite values')
    ids = set()
    for row in swc:
        ident, parent = int(row[0]), int(row[6])
        if ident in ids or ident < 1 or (parent != -1 and parent not in ids):
            raise ValueError('SWC contains duplicate IDs, missing parents, or a cycle')
        ids.add(ident)
    if len(swc) and (np.any(swc[:, 2:5] < origin) or
                     np.any(swc[:, 2:5] > np.asarray(shape[::-1]) - 1 + origin) or
                     np.any(swc[:, 5] <= 0)):
        raise ValueError('SWC coordinates or radii out of bounds')


def save_swc(path, swc, metadata):
    temporary = path.with_suffix('.swc.tmp')
    with temporary.open('w') as stream:
        stream.write('# SPE-DNR official pretrained tracer; ' + json.dumps(metadata) + '\n')
        stream.write('# id type x y z radius parent\n')
        np.savetxt(stream, swc, fmt='%d %d %.5f %.5f %.5f %.5f %d')
    temporary.replace(path)
