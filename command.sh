Xvfb :99 -screen 0 1920x1080x24 -ac &
export DISPLAY=:99
uvicorn app:app --host 0.0.0.0 --port 8000 --workers 32