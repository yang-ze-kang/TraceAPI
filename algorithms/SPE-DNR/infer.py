#!/usr/bin/env python3
"""Batch inference using the official SPE-DNR network and pretrained weights."""
import argparse
import contextlib
import hashlib
import json
from pathlib import Path
import sys
import time
import traceback

import numpy as np
import torch
from functions.CNNTracker_v2D_radii import Tracker
from functions.utlis import generate_sphere
from model.centerline_net import CenterlineNet_Discrimintor_2D_Radii_32
from pipeline import (read_manifest, read_volume, image_seeds, map_seeds,
                      find_aux, graph_to_swc, validate_swc, save_swc)

HERE = Path(__file__).resolve().parent


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    inputs = p.add_mutually_exclusive_group(required=True)
    inputs.add_argument('--list', type=Path, help='CSV: image,swc,mask; only image is read')
    inputs.add_argument('--image', type=Path, help='Single original 3D TIFF image')
    p.add_argument('--data-root', type=Path, help='Root for relative paths; default: list directory then parent')
    p.add_argument('--output', type=Path, default=HERE / 'outputs' / 'predictions')
    p.add_argument('--weights', type=Path, default=HERE / 'checkpoint/classification_checkpoints/weight.pkl')
    p.add_argument('--device', default='auto', help='auto, cpu, cuda, cuda:0, ...')
    p.add_argument('--threads', type=int, default=1, help='PyTorch CPU threads; small CNN benefits from 1')
    p.add_argument('--limit', type=int, default=0, help='First N samples; 0 means all')
    p.add_argument('--offset', type=int, default=0)
    p.add_argument('--resume', action='store_true', help='Skip completed outputs with identical configuration and inputs')
    p.add_argument('--check-inputs', action='store_true', help='Resolve input images without running inference')
    masks = p.add_mutually_exclusive_group()
    masks.add_argument('--mask-dir', '--seed-map-dir', dest='seed_map_dir', type=Path,
                       help='VNet predicted centerline maps: KEY_seg.tif, KEY_mask.tif, KEY.tif_mask.tif or KEY.tif')
    masks.add_argument('--mask', type=Path, help='VNet predicted map for --image (probability or binary TIFF)')
    p.add_argument('--seed-mode', choices=['vnet', 'image'], default='vnet',
                   help='Default vnet requires a predicted map; image explicitly enables the legacy heuristic')
    p.add_argument('--soma-mask', type=Path, help='Optional soma mask for --image')
    p.add_argument('--soma-mask-dir', type=Path, help='Optional predicted KEY_soma.tif or KEY.tif; default: no soma stop')
    p.add_argument('--flip-soma-y', action='store_true', help='Official human_4 soma requires this; not CWMBS default')
    p.add_argument('--seed-spacing', type=int, default=3)
    p.add_argument('--seed-threshold', type=float, help='Threshold after smoothing (image seed mode)')
    p.add_argument('--max-seeds', type=int, default=0, help='0 means all; positive values truncate for debugging')
    p.add_argument('--background-percentile', type=float, default=0, help='Optional subtraction; 0 disables (upstream behavior)')
    p.add_argument('--lambda', dest='lambda_', type=float, default=4)
    p.add_argument('--max-iter', type=int, default=100, help='Maximum steps per direction per seed (official: 100)')
    p.add_argument('--coordinate-origin', type=int, choices=[0, 1], default=0, help='0: array coordinates; 1: upstream Vaa3D convention')
    p.add_argument('--largest-tree', action='store_true', help='Keep only largest connected component')
    return p


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(argv=None):
    cli = parser()
    args = cli.parse_args(argv)
    if min(args.limit, args.offset, args.max_seeds) < 0 or min(args.threads, args.seed_spacing, args.max_iter) < 1:
        raise ValueError('Invalid limit, offset, threads, spacing, max-seeds or max-iter')
    if not 0 <= args.background_percentile < 100 or args.lambda_ <= 0:
        raise ValueError('Invalid background percentile or lambda')
    if args.mask and not args.image:
        cli.error('--mask requires --image; use --mask-dir for a list')
    if args.soma_mask and (not args.image or args.soma_mask_dir):
        cli.error('--soma-mask requires --image and cannot be combined with --soma-mask-dir')
    if args.seed_mode == 'image' and (args.mask or args.seed_map_dir):
        cli.error('--seed-mode image cannot be combined with VNet masks')
    if args.seed_mode == 'vnet' and not (args.mask or args.seed_map_dir) and not args.check_inputs:
        cli.error('VNet mode requires --mask-dir (batch) or --image IMAGE --mask MASK. '
                  'Use --seed-mode image explicitly for the legacy heuristic.')
    if args.image:
        args.image = args.image.resolve()
        if not args.image.is_file():
            raise FileNotFoundError(args.image)
        samples = [(args.image.stem, args.image)][args.offset:]
    else:
        samples = read_manifest(args.list, args.data_root)[args.offset:]
    if args.limit:
        samples = samples[:args.limit]
    if not samples:
        raise ValueError('No samples selected')
    if args.check_inputs:
        for key, path in samples:
            seed_path = args.mask or (find_aux(args.seed_map_dir, key, '_seg') if args.seed_map_dir else None)
            if seed_path and not seed_path.is_file():
                raise FileNotFoundError(seed_path)
            print(f'{key}\t{path}\t-> {args.output / (key + ".swc")}')
            if seed_path:
                print(f'  VNet mask: {seed_path}')
        print(f'{len(samples)} images resolved; annotation columns are ignored.')
        return 0
    torch.set_num_threads(args.threads)
    device = torch.device(('cuda' if torch.cuda.is_available() else 'cpu') if args.device == 'auto' else args.device)
    if device.type == 'cuda' and not torch.cuda.is_available():
        raise RuntimeError('CUDA requested but unavailable. Use --device cpu or fix GPU access.')
    checkpoint = torch.load(args.weights, map_location='cpu', weights_only=True)
    model = CenterlineNet_Discrimintor_2D_Radii_32(NUM_ACTIONS=1024, n=10)
    model.load_state_dict(checkpoint['net_dict'], strict=True)
    model.to(device).eval()
    weight_sha = sha256(args.weights)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / 'logs').mkdir(exist_ok=True)
    config = {k: str(v) if isinstance(v, Path) else v for k, v in vars(args).items()}
    config.update(device=str(device), weights_sha256=weight_sha, checkpoint_epoch=checkpoint.get('epoch'))
    code_hash = hashlib.sha256()
    for source in ['infer.py', 'pipeline.py', 'functions/CNNTracker_v2D_radii.py', 'functions/utlis.py', 'model/centerline_net.py']:
        code_hash.update((HERE / source).read_bytes())
    config['implementation_sha256'] = code_hash.hexdigest()
    identity = {k: v for k, v in config.items() if k not in ('resume', 'limit', 'offset', 'check_inputs', 'output')}
    fingerprint = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    (args.output / 'run_config.json').write_text(json.dumps(config, indent=2) + '\n')
    print(f'Loaded official weights (epoch {checkpoint.get("epoch")}) on {device}; {len(samples)} samples', flush=True)
    print(f'Seed mode: {args.seed_mode}', flush=True)
    sphere = generate_sphere(32, 32)[0]
    results, failures = [], 0
    for index, (key, path) in enumerate(samples, 1):
        start = time.monotonic()
        swc_path, meta_path = args.output / f'{key}.swc', args.output / f'{key}.json'
        record = {'sample': key, 'image': str(path), 'swc': str(swc_path), 'fingerprint': fingerprint}
        try:
            seed_path = args.mask or (find_aux(args.seed_map_dir, key, '_seg') if args.seed_map_dir else None)
            soma_path = args.soma_mask or (find_aux(args.soma_mask_dir, key, '_soma') if args.soma_mask_dir else None)
            record['input_stats'] = {str(p.resolve()): [p.stat().st_size, p.stat().st_mtime_ns]
                                     for p in (path, seed_path, soma_path) if p}
            if args.resume and swc_path.exists() and meta_path.exists():
                previous = json.loads(meta_path.read_text())
                if (previous.get('fingerprint') == fingerprint and previous.get('input_stats') == record['input_stats']
                        and previous.get('status') in ('ok', 'empty') and previous.get('swc_sha256') == sha256(swc_path)):
                    results.append(previous)
                    print(f'[{index}/{len(samples)}] {key}: resume', flush=True)
                    continue
            image = read_volume(path).astype(np.float32)
            if image.min() < 0:
                raise ValueError('Negative image intensities are unsupported')
            background = float(np.percentile(image, args.background_percentile)) if args.background_percentile else 0.
            if background:
                image = np.maximum(image - background, 0)
            record.update(shape_zyx=list(image.shape), background_subtracted=background,
                          seed_method='vnet-map' if seed_path else 'image-skeleton',
                          soma_method='external-mask' if soma_path else 'disabled')
            if seed_path:
                seeds = map_seeds(seed_path, image.shape, args.max_seeds)
            else:
                seeds, cutoff = image_seeds(image, args.seed_spacing, args.seed_threshold, args.max_seeds)
                record['seed_threshold'] = cutoff
            soma = np.zeros(image.shape, dtype=bool)
            if soma_path:
                soma = read_volume(soma_path) > 0
                if soma.shape != image.shape:
                    raise ValueError('Soma mask and image shapes differ')
                if args.flip_soma_y:
                    soma = np.flip(soma, axis=1)
            record['seeds'] = len(seeds)
            print(f'[{index}/{len(samples)}] {key}: {len(seeds)} seeds, tracing...', flush=True)
            padded, padded_soma = np.pad(image, 10), np.pad(soma, 10)
            seeds[:, :3] += 10
            zb, xb, yb = padded.shape
            tracker = Tracker(padded, padded_soma, seeds, args.lambda_, 1024, np.pi/3,
                              args.max_iter, 1, 1, 3, 10, 32, 32, 10, xb, yb, zb,
                              model, sphere, sphere, device)
            with (args.output / 'logs' / f'{key}.log').open('w') as log:
                with contextlib.redirect_stdout(log), contextlib.redirect_stderr(log), torch.inference_mode():
                    tracker.trace_JointDecision()
            swc = graph_to_swc(tracker.ndlist, origin=args.coordinate_origin, largest_tree=args.largest_tree)
            validate_swc(swc, image.shape, args.coordinate_origin)
            record.update(status='ok' if len(swc) else 'empty', nodes=len(swc),
                          roots=int(np.sum(swc[:, 6] == -1)), seconds=round(time.monotonic()-start, 3),
                          coordinate_origin=args.coordinate_origin, weights_sha256=weight_sha)
            save_swc(swc_path, swc, {k: record[k] for k in ('sample', 'seed_method', 'soma_method', 'coordinate_origin', 'weights_sha256', 'status')})
            record['swc_sha256'] = sha256(swc_path)
            del tracker, padded, padded_soma, image, soma
            print(f'  {record["status"]}: {len(swc)} nodes -> {swc_path} ({record["seconds"]:.1f}s)', flush=True)
        except Exception as exc:
            failures += 1
            record.update(status='error', error=str(exc), seconds=round(time.monotonic()-start, 3))
            with (args.output / 'logs' / f'{key}.log').open('a') as log:
                traceback.print_exc(file=log)
            print(f'  ERROR {key}: {exc}', file=sys.stderr, flush=True)
        meta_path.write_text(json.dumps(record, indent=2) + '\n')
        results.append(record)
        (args.output / 'summary.json').write_text(json.dumps(results, indent=2) + '\n')
    (args.output / 'summary.json').write_text(json.dumps(results, indent=2) + '\n')
    print(f'Finished: {len(results)} samples; {failures} errors; {sum(r["status"] == "empty" for r in results)} empty predictions.', flush=True)
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
