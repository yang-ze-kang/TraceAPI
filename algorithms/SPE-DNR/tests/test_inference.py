import contextlib
import io
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np
import tifffile
import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from functions.CNNTracker_v2D_radii import Tracker
from functions.utlis import Node, generate_sphere, local_max
from pipeline import read_manifest, image_seeds, map_seeds, graph_to_swc, validate_swc
from infer import main


class ForegroundModel(torch.nn.Module):
    def forward(self, x):
        directions = torch.zeros((1, 1024, 1, 1))
        stop_radius = torch.tensor([10., -10., 0.]).reshape(1, 3, 1, 1)
        return directions, stop_radius


class PipelineTests(unittest.TestCase):
    def test_manifest_parent_root_and_no_annotation_dependency(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            (root / 'image').mkdir()
            (root / 'splits').mkdir()
            (root / 'image/a.tif').touch()
            manifest = root / 'splits/test.txt'
            manifest.write_text('# comment\nimage,swc,mask\nimage/a.tif,missing.swc,missing.tif\n')
            self.assertEqual(read_manifest(manifest), [('a', root / 'image/a.tif')])
            manifest.write_text('image/a.tif\nimage/a.tif\n')
            with self.assertRaisesRegex(ValueError, 'duplicate'):
                read_manifest(manifest)

    def test_seed_map_matches_official_local_max(self):
        rng = np.random.default_rng(42)
        image = rng.integers(0, 256, (7, 9, 11), dtype=np.uint8)
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'seed.tif'
            tifffile.imwrite(path, image, photometric='minisblack')
            with contextlib.redirect_stderr(io.StringIO()):
                _, expected = local_max(image, wsize=3, thre=127.5)
            expected = np.asarray(expected)
            expected = expected[np.argsort(expected[:, -1])[::-1]]
            np.testing.assert_array_equal(map_seeds(path, image.shape), expected)

    def test_empty_image_and_axis_order(self):
        seeds, _ = image_seeds(np.zeros((12, 14, 16), np.float32))
        self.assertEqual(seeds.shape, (0, 4))
        node = Node(np.array([13, 15, 17]), 1, 2)
        swc = graph_to_swc([node], padding=10)
        np.testing.assert_array_equal(swc[0, 2:5], [5, 3, 7])
        validate_swc(swc, (12, 14, 16), 0)

    def test_vnet_probabilities_and_binary_masks(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'vnet.tif'
            volume = np.zeros((9, 9, 9), np.float32)
            volume[3, 3, 3] = 0.9
            volume[3, 3, 4] = 0.8  # not a local maximum
            volume[6, 6, 6] = 0.5  # strictly >0.5, not >=
            volume[0, 3, 3] = 1.0  # upstream excludes volume boundary
            tifffile.imwrite(path, volume, photometric='minisblack')
            seeds = map_seeds(path, volume.shape)
            self.assertEqual(seeds.shape, (1, 4))
            np.testing.assert_allclose(seeds[0], [3, 3, 3, 0.9*255], rtol=1e-6)
            for value in (1, 255):
                binary = np.zeros_like(volume, dtype=np.uint8)
                binary[3, 3, 3:5] = value
                tifffile.imwrite(path, binary, photometric='minisblack')
                seeds = map_seeds(path, binary.shape)
                self.assertEqual(len(seeds), 2)  # plateau follows upstream; no skeletonization
                np.testing.assert_array_equal(seeds[:, 3], [255, 255])

    def test_vnet_is_required_by_default(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as cm:
                main([])
        self.assertEqual(cm.exception.code, 2)

    def test_single_image_vnet_mask_empty_prediction(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            image, mask = root / 'image.tif', root / 'mask.tif'
            tifffile.imwrite(image, np.ones((12, 13, 14), np.uint8), photometric='minisblack')
            tifffile.imwrite(mask, np.zeros((12, 13, 14), np.float32), photometric='minisblack')
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(['--image', str(image), '--mask', str(mask), '--output', str(root/'out'), '--device', 'cpu']), 0)
            self.assertTrue((root/'out/image.swc').read_text().startswith('#'))

    def test_bfs_retains_parent_zero_and_breaks_cycles(self):
        nodes = [Node(np.array([15, 15, 15+i]), 1, 1) for i in range(4)]
        nodes[0].nbr = [1, 2]
        nodes[1].nbr = [0, 2]
        nodes[2].nbr = [0, 1]
        swc = graph_to_swc(nodes)
        np.testing.assert_array_equal(swc[:, 6], [-1, 1, 1, -1])
        validate_swc(swc, (30, 30, 30), 0)
        largest = graph_to_swc(nodes, largest_tree=True)
        self.assertEqual(largest.shape, (3, 7))
        self.assertEqual(graph_to_swc([]).shape, (0, 7))

    def tracker(self):
        sphere = generate_sphere(32, 32)[0]
        tracker = Tracker(np.ones((42, 42, 42), np.float32), np.zeros((42, 42, 42), bool),
                          np.empty((0, 4)), 4, 1024, np.pi/3, 1, 1, 1, 3, 10,
                          32, 32, 10, 42, 42, 42, ForegroundModel(), sphere, sphere, torch.device('cpu'))
        tracker.ndlist = [Node(np.array([20., 20., 20.]), 1., 1.)]
        tracker.rlist = [1.]
        tracker.pt_index = tracker.position_id = 1
        return tracker

    def test_reverse_branch_attaches_to_seed_without_self_loop(self):
        tracker = self.tracker()
        with contextlib.redirect_stdout(io.StringIO()), torch.inference_mode():
            tracker._Track_Pos(np.array([20., 20., 20.]), np.array([1., 0., 0.]), True, 1.)
        self.assertEqual(tracker.ndlist[0].nbr, [1])
        self.assertEqual(tracker.ndlist[1].nbr, [0])

    def test_meeting_last_traced_node_has_valid_radius_index(self):
        tracker = self.tracker()
        tracker.indx_map[20, 21, 20] = 1
        with contextlib.redirect_stdout(io.StringIO()):
            tracker._Track_Pos(np.array([20., 20., 20.]), np.array([1., 0., 0.]), False, 1.)
        self.assertEqual(len(tracker.ndlist), 2)
        self.assertEqual(tracker.ndlist[1].radius, 1.)

    def test_real_weights_empty_output_resume_and_error_isolation(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            tifffile.imwrite(root / 'empty.tif', np.zeros((12, 13, 14), np.uint8), photometric='minisblack')
            (root / 'bad.tif').write_text('invalid TIFF')
            manifest = root / 'test.txt'
            manifest.write_text('empty.tif,not-read.swc,not-read.tif\nbad.tif\n')
            args = ['--list', str(manifest), '--output', str(root / 'out'), '--device', 'cpu', '--seed-mode', 'image']
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main(args), 1)
            swc = root / 'out/empty.swc'
            self.assertTrue(swc.exists())
            self.assertFalse((root / 'out/bad.swc').exists())
            mtime = swc.stat().st_mtime_ns
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main(args + ['--resume', '--limit', '1']), 0)
            self.assertEqual(swc.stat().st_mtime_ns, mtime)


if __name__ == '__main__':
    unittest.main()
