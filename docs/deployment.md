# Deployment

## Serve the API

Start an X display for Vaa3D, configure shared library paths, and run FastAPI with Uvicorn:

```bash
Xvfb :99 -screen 0 1920x1080x24 -ac &
export DISPLAY=:99
export LD_LIBRARY_PATH="$PWD/algorithms:$LD_LIBRARY_PATH"
python -m uvicorn app:app --host 0.0.0.0 --port 8000 --workers 4
```

## Serve the Documentation Locally

Install MkDocs Material:

```bash
pip install mkdocs-material
```

Preview the documentation:

```bash
mkdocs serve
```

Build the static site:

```bash
mkdocs build
```

## Publish to GitHub Pages

Deploy to the repository's `gh-pages` branch:

```bash
mkdocs gh-deploy --force
```

After deployment, the documentation is served at:

```text
https://yang-ze-kang.github.io/TraceAPI/
```

## Notes

- The GitHub Pages site is static documentation only.
- The FastAPI service must run on a server with access to the tracing binaries and input data.
- `tif_path` values are resolved on the API server, not in the browser.

