import requests

url = "http://127.0.0.1:8000/trace_neutube"
image_path = "/home/yangzekang/data1/vol.tiff"

with open(image_path, "rb") as f:
    files = {"file": f}
    r = requests.post(url, files=files)

# 检查状态
if r.status_code != 200:
    print("Request failed:", r.status_code)
    print(r.text)
else:
    # 保存返回的 swc 文件
    with open("result.swc", "wb") as out:
        out.write(r.content)
    print("Saved result.swc")