from __future__ import annotations

import io
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
import kimimaro_utils as backend


def tiff_bytes(array):
    stream = io.BytesIO()
    tifffile.imwrite(stream, array, photometric="minisblack")
    return stream.getvalue()


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "RUNS_DIR", tmp_path / "runs")
    return TestClient(api.app)


@pytest.fixture
def image(tmp_path):
    path = tmp_path / "prediction.tif"
    volume = np.zeros((24, 32, 64), np.float32)
    volume[7:12, 13:18, 5:59] = 0.8
    path.write_bytes(tiff_bytes(volume))
    return path


@pytest.fixture
def traced(monkeypatch):
    calls = []

    def fake_trace(**kwargs):
        calls.append(kwargs)
        assert np.isclose(tifffile.imread(kwargs["image"])[9, 15, 32], 0.8)
        output = kwargs["workdir"] / "output_full.swc"
        output.write_text(
            "1 3 32 15 9 1 -1\n2 3 42 15 9 1 1\n3 3 22 15 9 1 1\n"
        )
        return output

    monkeypatch.setattr(api, "run_kimimaro", fake_trace)
    return calls


def test_upload_preserves_probability_values_and_parameters(client, image, traced):
    response = client.post(
        "/trace_kimimaro",
        files={"file": (image.name, image.read_bytes(), "image/tiff")},
        data={"foreground_thres": "0.7", "kimimaro_anisotropy": "0.2,0.4,1.5"},
    )
    assert response.status_code == 200, response.text
    assert "output.swc" in response.headers["content-disposition"]
    assert len(traced) == 1
    assert traced[0]["foreground_thres"] == 0.7
    assert traced[0]["kimimaro_anisotropy"] == (0.2, 0.4, 1.5)
    assert traced[0]["timeout_sec"] == 3000


def test_subtree_direction_and_batch_trace_once(client, image, traced):
    response = client.post("/trace_kimimaro_subtree", data={
        "tif_path": str(image), "s1": "32.25,15,9", "s2": "34,15,9",
    })
    assert response.status_code == 200, response.text
    rows = np.loadtxt(io.StringIO(response.text), ndmin=2)
    np.testing.assert_allclose(rows[0, 2:5], [32.25, 15, 9])
    assert len(rows) > 1 and np.all(rows[:, 2] >= 32.25)
    response = client.post("/trace_kimimaro_subtree", data={
        "tif_path": str(image),
        "s1": "[[32,15,9],[32,15,9]]", "s2": "34,15,9;30,15,9",
    })
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert archive.namelist() == ["subtree_000.swc", "subtree_001.swc"]
        for index, sign in [(0, 1), (1, -1)]:
            rows = np.loadtxt(io.BytesIO(archive.read(f"subtree_{index:03d}.swc")), ndmin=2)
            assert len(rows) > 1 and np.all(sign * (rows[:, 2] - 32) >= 0)
    assert len(traced) == 2
    assert all(call["timeout_sec"] == 600 for call in traced)


@pytest.mark.parametrize("change", ["missing", "both", "not_tiff", "2d", "nan", "negative"])
def test_invalid_input_fails_before_backend(client, image, traced, change):
    data = {"tif_path": str(image)}
    files = None
    if change == "missing":
        data = {}
    elif change == "both":
        files = {"file": (image.name, image.read_bytes())}
    elif change == "not_tiff":
        image.write_text("not TIFF")
    else:
        volume = np.zeros((12, 13) if change == "2d" else (12, 13, 14), np.float32)
        if change == "nan":
            volume.flat[0] = np.nan
        elif change == "negative":
            volume.flat[0] = -1
        image.write_bytes(tiff_bytes(volume))
    response = client.post("/trace_kimimaro", data=data, files=files)
    assert response.status_code == 400, response.text
    assert not traced


@pytest.mark.parametrize("s1,s2", [
    ("nan,15,9", "34,15,9"), ("64,15,9", "34,15,9"),
    ("32,15,9", "32,15,9"), ("32,15,9;32,15,9", "34,15,9"),
    (";", ";"),
])
def test_invalid_seed_pairs_fail_before_backend(client, image, traced, s1, s2):
    response = client.post("/trace_kimimaro_subtree", data={
        "tif_path": str(image), "s1": s1, "s2": s2,
    })
    assert response.status_code == 400, response.text
    assert not traced


@pytest.mark.parametrize("value", ["0,1,1", "nan,1,1", "1,2", "1,-1,1"])
def test_invalid_anisotropy(client, image, traced, value):
    response = client.post("/trace_kimimaro", data={
        "tif_path": str(image), "kimimaro_anisotropy": value,
    })
    assert response.status_code == 400, response.text
    assert not traced


@pytest.mark.parametrize("value", ["0", "-1", "1.1", "nan", "inf"])
def test_invalid_threshold(client, image, traced, value):
    response = client.post("/trace_kimimaro", data={
        "tif_path": str(image), "foreground_thres": value,
    })
    assert response.status_code == 422, response.text
    assert not traced


def test_far_seed_returns_empty_subtree(client, image, traced):
    response = client.post("/trace_kimimaro_subtree", data={
        "tif_path": str(image), "s1": "1,1,1", "s2": "2,1,1",
    })
    assert response.status_code == 200, response.text
    assert response.content
    assert all(not row.strip() or row.startswith("#") for row in response.text.splitlines())


@pytest.mark.parametrize("spacing_xyz", [(0.35, 0.35, 1.0), (0.2, 0.4, 1.5)])
def test_threshold_and_physical_zyx_to_voxel_xyz(tmp_path, monkeypatch, spacing_xyz):
    kimimaro = pytest.importorskip("kimimaro")
    image, output = tmp_path / "input.tif", tmp_path / "output.swc"
    volume = np.zeros((4, 5, 6), np.float32)
    volume[1, 2, 3:6] = [0.39, 0.4, 0.8]
    image.write_bytes(tiff_bytes(volume))

    class Skeleton:
        def to_swc(self):
            return (
                "# anisotropic skeleton\n"
                f"1 3 {2 * spacing_xyz[2]} {3 * spacing_xyz[1]} {4 * spacing_xyz[0]} 0.7 -1\n"
            )

    def skeletonize(labels, **kwargs):
        expected = np.zeros_like(volume, dtype=np.uint8)
        expected[1, 2, 4:6] = 1
        np.testing.assert_array_equal(labels, expected)
        assert kwargs["anisotropy"] == spacing_xyz[::-1]
        assert kwargs["dust_threshold"] == 100
        return {1: Skeleton()}

    monkeypatch.setattr(kimimaro, "skeletonize", skeletonize)
    backend.trace_kimimaro(image, output, kimimaro_anisotropy=spacing_xyz)
    row = np.loadtxt(output)
    np.testing.assert_allclose(row, [1, 3, 4, 3, 2, 0.7, -1])


def test_empty_image_never_skeletonizes_background(tmp_path, monkeypatch):
    kimimaro = pytest.importorskip("kimimaro")
    image, output = tmp_path / "input.tif", tmp_path / "output.swc"
    image.write_bytes(tiff_bytes(np.zeros((8, 8, 8), np.uint8)))

    def fail(*args, **kwargs):
        pytest.fail("An all-zero volume must not be skeletonized")

    monkeypatch.setattr(kimimaro, "skeletonize", fail)
    backend.trace_kimimaro(image, output)
    assert output.read_text() == "# none\n"


def test_backend_timeout_and_missing_output(tmp_path, monkeypatch):
    def timeout(command, log, workdir, seconds):
        assert command[0] == sys.executable
        assert Path(command[1]).resolve() == Path(backend.__file__).resolve()
        assert command[-4:] == ["--anisotropy", "0.35", "0.35", "1.0"]
        assert seconds == 5
        return False

    monkeypatch.setattr(backend, "run_cmd", timeout)
    with pytest.raises(HTTPException) as exc:
        backend.run_kimimaro(workdir=tmp_path, image=tmp_path / "input.tif", timeout_sec=5)
    assert exc.value.status_code == 504
    monkeypatch.setattr(backend, "run_cmd", lambda *args: True)
    with pytest.raises(HTTPException) as exc:
        backend.run_kimimaro(workdir=tmp_path, image=tmp_path / "input.tif")
    assert exc.value.status_code == 500


def test_real_backend_full_subtree_batch_and_empty(client, image):
    pytest.importorskip("kimimaro")
    response = client.post("/trace_kimimaro", files={"file": (image.name, image.read_bytes())})
    assert response.status_code == 200, response.text
    rows = np.loadtxt(io.StringIO(response.text), ndmin=2)
    assert len(rows) > 10
    # Physical-to-voxel scaling retains the original floating-point precision.
    assert np.all(rows[:, 2:5] >= np.array([5, 13, 7]) - 1e-5)
    assert np.all(rows[:, 2:5] <= np.array([58, 17, 11]) + 1e-5)
    response = client.post("/trace_kimimaro_subtree", data={
        "tif_path": str(image), "s1": "32,15,9", "s2": "34,15,9",
    })
    assert response.status_code == 200, response.text
    rows = np.loadtxt(io.StringIO(response.text), ndmin=2)
    np.testing.assert_allclose(rows[0, 2:5], [32, 15, 9])
    assert len(rows) > 2 and np.all(rows[:, 2] >= 32)
    response = client.post("/trace_kimimaro_subtree", data={
        "tif_path": str(image), "s1": "32,15,9;32,15,9", "s2": "34,15,9;30,15,9",
    })
    assert response.status_code == 200, response.text
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert len(archive.namelist()) == 2
        rows = np.loadtxt(io.BytesIO(archive.read("subtree_001.swc")), ndmin=2)
        assert len(rows) > 2 and np.all(rows[:, 2] <= 32)

    image.write_bytes(tiff_bytes(np.zeros((24, 32, 64), np.uint8)))
    response = client.post("/trace_kimimaro", data={"tif_path": str(image)})
    assert response.status_code == 200 and response.text == "# none\n"
    response = client.post("/trace_kimimaro_subtree", data={
        "tif_path": str(image), "s1": "32,15,9", "s2": "34,15,9",
    })
    assert response.status_code == 200, response.text
    assert response.content
    assert all(not row.strip() or row.startswith("#") for row in response.text.splitlines())
