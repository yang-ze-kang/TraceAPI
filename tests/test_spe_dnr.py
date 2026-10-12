from __future__ import annotations

import io
import json
from pathlib import Path
import sys
import zipfile

import numpy as np
import pytest
import tifffile
from fastapi import HTTPException
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as api
import spe_dnr_utils as backend


def tiff_bytes(array):
    stream = io.BytesIO()
    tifffile.imwrite(stream, array, photometric='minisblack')
    return stream.getvalue()


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(api, 'RUNS_DIR', tmp_path / 'runs')
    return TestClient(api.app)


@pytest.fixture
def inputs(tmp_path):
    image, mask = tmp_path / 'image.tif', tmp_path / 'mask.tif'
    tifffile.imwrite(image, np.full((12, 13, 14), 53, np.uint8), photometric='minisblack')
    data = np.zeros((12, 13, 14), np.float32)
    data[5, 5, 5] = 0.8
    tifffile.imwrite(mask, data, photometric='minisblack')
    return {'tif_path': str(image), 'mask_path': str(mask)}


@pytest.fixture
def traced(monkeypatch):
    calls = []
    def fake_trace(**kwargs):
        calls.append(kwargs)
        assert tifffile.imread(kwargs['image'])[0, 0, 0] == 53
        assert np.isclose(tifffile.imread(kwargs['mask'])[5, 5, 5], 0.8)
        path = kwargs['workdir'] / 'full.swc'
        path.write_text('1 3 5 5 5 1 -1\n2 3 7 5 5 1 1\n3 3 9 5 5 1 2\n4 3 3 5 5 1 1\n')
        return path
    monkeypatch.setattr(api, 'run_spe_dnr', fake_trace)
    return calls


def test_full_upload_preserves_image_and_probabilities(client, inputs, traced):
    files = {'file': ('image.tif', Path(inputs['tif_path']).read_bytes(), 'image/tiff'),
             'mask_file': ('mask.tif', Path(inputs['mask_path']).read_bytes(), 'image/tiff')}
    response = client.post('/trace_spe_dnr', files=files)
    assert response.status_code == 200, response.text
    assert 'output.swc' in response.headers['content-disposition']
    assert len(traced) == 1 and traced[0]['timeout_sec'] == 3000
    assert '1 3 5 5 5' in response.text


def test_subtree_single_and_batch_direction(client, inputs, traced):
    response = client.post('/trace_spe_dnr_subtree', data={**inputs, 's1': '5,5,5', 's2': '7,5,5'})
    assert response.status_code == 200, response.text
    rows = np.loadtxt(io.StringIO(response.text), ndmin=2)
    np.testing.assert_allclose(rows[0, 2:5], [5, 5, 5])
    assert np.all(rows[:, 2] >= 5)
    response = client.post('/trace_spe_dnr_subtree', data={**inputs, 's1': '5,5,5;5,5,5', 's2': '7,5,5;3,5,5'})
    assert response.status_code == 200, response.text
    assert response.headers['content-type'] == 'application/zip'
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert len(archive.namelist()) == 2
        left = np.loadtxt(io.StringIO(archive.read('subtree_001.swc').decode()), ndmin=2)
        assert np.all(left[:, 2] <= 5)
    assert len(traced) == 2  # one reconstruction per request, not per seed pair
    assert traced[0]['timeout_sec'] == 600


@pytest.mark.parametrize('change', ['missing_mask', 'both_masks', 'shape', 'nan', 'range', 'not_tiff'])
def test_bad_masks_fail_before_backend(client, inputs, traced, change):
    data = dict(inputs)
    files = None
    if change == 'missing_mask':
        data.pop('mask_path')
    elif change == 'both_masks':
        files = {'mask_file': ('mask.tif', Path(data['mask_path']).read_bytes())}
    elif change == 'not_tiff':
        Path(data['mask_path']).write_text('not a TIFF')
    else:
        array = np.zeros((5, 5, 5) if change == 'shape' else (12, 13, 14), np.float32)
        if change == 'nan': array[0, 0, 0] = np.nan
        if change == 'range': array[0, 0, 0] = 256
        tifffile.imwrite(data['mask_path'], array, photometric='minisblack')
    response = client.post('/trace_spe_dnr', data=data, files=files)
    assert response.status_code == 400, response.text
    assert not traced


@pytest.mark.parametrize('s1,s2', [('nan,5,5','6,5,5'), ('14,5,5','6,5,5'), ('5,5,5','5,5,5'), ('5,5,5;6,5,5','7,5,5')])
def test_invalid_seed_pairs(client, inputs, traced, s1, s2):
    response = client.post('/trace_spe_dnr_subtree', data={**inputs, 's1': s1, 's2': s2})
    assert response.status_code == 400, response.text
    assert not traced


def test_fractional_boundary_seed_is_preserved(client, inputs, traced):
    # The image width is 14: x=13.75 is a valid continuous coordinate even
    # though the largest integer voxel index is 13.
    response = client.post('/trace_spe_dnr_subtree', data={
        **inputs, 's1': '13.75,5,5', 's2': '12.75,5,5',
    })
    assert response.status_code == 200, response.text
    rows = np.loadtxt(io.StringIO(response.text), ndmin=2)
    np.testing.assert_allclose(rows[0, 2:5], [13.75, 5, 5])
    assert len(traced) == 1


@pytest.mark.parametrize('point', [(256, 1, 1), (-0.001, 1, 1), (1, 256, 1),
                                  (1, 1, 256), (float('inf'), 1, 1)])
def test_continuous_seed_bounds_still_reject_invalid_points(point):
    with pytest.raises(HTTPException) as exc:
        backend.validate_seed_pairs([(point, (2, 2, 2))], (256, 256, 256))
    assert exc.value.status_code == 400


def test_cwmbs_fractional_corner_in_both_seeds():
    backend.validate_seed_pairs([((255.952, 255.960, 255.964), (255.5, 255.5, 255.5))], (256, 256, 256))


def test_empty_subtree(client, inputs, monkeypatch):
    def empty(**kwargs):
        path = kwargs['workdir'] / 'empty.swc'
        path.write_text('# empty prediction\n')
        return path
    monkeypatch.setattr(api, 'run_spe_dnr', empty)
    response = client.post('/trace_spe_dnr_subtree', data={**inputs, 's1': '5,5,5', 's2': '7,5,5'})
    assert response.status_code == 200, response.text
    assert all(not row.strip() or row.startswith('#') for row in response.text.splitlines())


def test_backend_command_and_timeout(tmp_path, monkeypatch):
    project, workdir = tmp_path/'project', tmp_path/'work'
    project.mkdir(); workdir.mkdir()
    (project/'infer.py').touch()
    weights = project/'checkpoint/classification_checkpoints/weight.pkl'
    weights.parent.mkdir(parents=True)
    weights.touch()
    args = dict(project_dir=project, workdir=workdir, image=workdir/'image.tif', mask=workdir/'mask.tif')
    monkeypatch.setenv('SPE_DNR_DEVICE', 'cpu')
    monkeypatch.setenv('SPE_DNR_PYTHON', '/missing/external/python')
    def command(cmd, log, cwd, timeout):
        assert cmd[0] == sys.executable
        assert cmd[cmd.index('--weights')+1] == str(weights)
        assert cmd[cmd.index('--mask')+1] == str(args['mask'])
        assert cmd[cmd.index('--coordinate-origin')+1] == '0'
        assert cmd[cmd.index('--device')+1] == 'cpu'
        dest = workdir/'prediction'; dest.mkdir()
        (dest/'image.swc').write_text('# empty\n')
        (dest/'image.json').write_text(json.dumps({'status': 'empty'}))
        return True
    monkeypatch.setattr(backend, 'run_cmd', command)
    assert backend.run_spe_dnr(**args).exists()
    monkeypatch.setattr(backend, 'run_cmd', lambda *a: False)
    with pytest.raises(HTTPException) as exc:
        backend.run_spe_dnr(**args)
    assert exc.value.status_code == 504


def test_backend_is_bundled_with_official_weights():
    import hashlib
    root = Path(api.__file__).resolve().parent
    assert api.SPE_DNR_DIR == root / 'algorithms' / 'SPE-DNR'
    assert (api.SPE_DNR_DIR / 'infer.py').is_file()
    weight = api.SPE_DNR_DIR / 'checkpoint/classification_checkpoints/weight.pkl'
    assert not weight.is_symlink()
    assert hashlib.sha256(weight.read_bytes()).hexdigest() == 'e8bd5a57955e967282a13b8003e0436001373c75d8eae5a423ede5427729dec7'
