Xvfb :99 -screen 0 1920x1080x24 -ac &
export DISPLAY=:99
# uvicorn app:app --host 0.0.0.0 --port 8000 --workers 32
python -m uvicorn app:app --host 0.0.0.0 --port 8000 --workers 32

sudo apt-get install libglu1-mesa
sudo apt-get install -y libqt5widgets5 libqt5gui5 libqt5xml5 libqt5network5 libqt5core5a
sudo apt-get install -y libqt5concurrent5


export LD_LIBRARY_PATH=/gpfs-flash/hulab/yangzekang/miniconda/envs/py39/lib:$LD_LIBRARY_PATH

export LD_LIBRARY_PATH=/gpfs-flash/hulab/yangzekang/neuron/TraceAPI/algorithms:$LD_LIBRARY_PATH


/gpfs-flash/hulab/yangzekang/neuron/TraceAPI/algorithms/Vaa3D-x.1.1.4_Ubuntu/Vaa3D-x \
    -x vn2 -f app2 \
    -i /gpfs-flash/hulab/yangzekang/neuron/neuron-trace/outputs/C2-cubes1937-iter10000/dynunet-cldice-iter3/2026-04-25-07-33-40/preds/cube300_x4500_y15700_z3700.tif \
    -o test1.swc

# 2) 调 APP2 接口测试单个 tif（终端2）
curl -X POST "http://127.0.0.1:8000/trace_vaa3d_app2" \
  -F "file=@/gpfs-flash/hulab/yangzekang/neuron/neuron-trace/outputs/C2-cubes1937-iter10000/dynunet-cldice-iter3/2026-04-25-07-33-40/preds/cube300_x4500_y15700_z3700.tif" \
  --output test_app2_output2-2.swc

curl -X POST "http://127.0.0.1:8000/trace_vaa3d_smartTrace" \
  -F "file=@/gpfs-flash/hulab/yangzekang/neuron/neuron-trace/outputs/C2-cubes1937-iter10000/dynunet-cldice-iter3/2026-04-25-07-33-40/preds/cube300_x4500_y15700_z3700.tif" \
  --output test_app2_output3.swc

# ---- APP2 marker format check ----
# simple marker: x,y,z
/gpfs-flash/hulab/yangzekang/neuron/TraceAPI/algorithms/Vaa3D-x.1.1.4_Ubuntu/Vaa3D-x \
    -x vn2 -f app2 \
    -i /gpfs-flash/hulab/yangzekang/neuron/neuron-trace/outputs/C2-cubes1937-iter10000/dynunet-cldice-iter3/2026-04-25-07-33-40/preds/cube300_x4500_y15700_z3700.tif \
    -o test_marker_simple.swc \
    -p /gpfs-flash/hulab/yangzekang/neuron/TraceAPI/test_seed_simple.marker 0 10 1 1 0 0 5 1 0 0

# full marker: x,y,z,radius,shape,name,comment,color_r,color_g,color_b
/gpfs-flash/hulab/yangzekang/neuron/TraceAPI/algorithms/Vaa3D-x.1.1.4_Ubuntu/Vaa3D-x \
    -x vn2 -f app2 \
    -i /gpfs-flash/hulab/yangzekang/neuron/neuron-trace/outputs/C2-cubes1937-iter10000/dynunet-cldice-iter3/2026-04-25-07-33-40/preds/cube300_x4500_y15700_z3700.tif \
    -o test_marker_full.swc \
    -p /gpfs-flash/hulab/yangzekang/neuron/TraceAPI/test_seed_full.marker 0 10 1 1 0 0 5 1 0 0

/gpfs-flash/hulab/yangzekang/neuron/TraceAPI/algorithms/Vaa3D-x.1.1.4_Ubuntu/Vaa3D-x -x vn2 -f app2 -i /gpfs-flash/hulab/yangzekang/neuron/TraceAPI/runs/20260429_160333_954/vol_uint8.tiff -o /gpfs-flash/hulab/yangzekang/neuron/TraceAPI/runs/20260429_160333_954/seed_000_003.swc -p /gpfs-flash/hulab/yangzekang/neuron/TraceAPI/runs/20260429_160333_954/seed_000_003.marker 0 10 0 1 0 0 5 1 0 
/gpfs-flash/hulab/yangzekang/neuron/TraceAPI/algorithms/Vaa3D-x.1.1.4_Ubuntu/Vaa3D-x -x vn2 -f app2 -i /gpfs-flash/hulab/yangzekang/neuron/TraceAPI/runs/20260429_160333_954/vol_uint8.tiff -o /gpfs-flash/hulab/yangzekang/neuron/TraceAPI/runs/20260429_160333_954/seed_000_003.swc -p None 0 10 0 1 0 0 5 1 0 

/gpfs-flash/hulab/yangzekang/neuron/TraceAPI/algorithms/Vaa3D-x.1.1.4_Ubuntu/Vaa3D-x -x smartTrace -f smartTrace -i /gpfs-flash/hulab/yangzekang/neuron/TraceAPI/runs/20260429_184601_565/vol_uint8.tiff -p /gpfs-flash/hulab/yangzekang/neuron/TraceAPI/runs/20260429_184601_565/smart_seed_000_000.marker 0 10 0 1 0 0 5 1 0 


curl -X POST "http://127.0.0.1:8000/trace_vaa3d_app2" \
  -F "file=@/gpfs-flash/hulab/yangzekang/neuron/neuron-trace/outputs/C2-cubes1937-iter10000/vnet-dice/2026-04-24-23-39-35/preds/cube300_x13200_y20500_z4000.tif" \
  --output /gpfs-flash/hulab/yangzekang/neuron/TraceAPI/test_app2_output2.swc


curl -X POST "http://127.0.0.1:8000/trace_vaa3d_smartTrace" \
  -F "file=@/gpfs-flash/hulab/yangzekang/neuron/neuron-trace/outputs/C2-cubes1937-iter10000/vnet-dice/2026-04-24-23-39-35/preds/cube300_x13200_y20500_z4000.tif" \
  --output /gpfs-flash/hulab/yangzekang/neuron/TraceAPI/test_app2_output2.swc
