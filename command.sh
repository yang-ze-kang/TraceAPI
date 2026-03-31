Xvfb :99 -screen 0 1920x1080x24 -ac &
export DISPLAY=:99
# uvicorn app:app --host 0.0.0.0 --port 8000 --workers 32
python -m uvicorn app:app --host 0.0.0.0 --port 8000 --workers 32

sudo apt-get install libglu1-mesa
sudo apt-get install -y libqt5widgets5 libqt5gui5 libqt5xml5 libqt5network5 libqt5core5a
sudo apt-get install -y libqt5concurrent5