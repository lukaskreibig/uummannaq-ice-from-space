# debug_requests_stac.py
import requests, time, json
url = "https://earth-search.aws.element84.com/v1/search"
body = {"collections":["sentinel-2-l1c"], "limit":1}
print("POST", url, flush=True)
t0 = time.time()
try:
    r = requests.post(url, json=body, timeout=15)
    print("status", r.status_code, "took %.2fs" % (time.time()-t0), flush=True)
    j = r.json()
    print("keys:", list(j.keys()), "features:", len(j.get("features", [])), flush=True)
    if j.get("features"):
        f = j["features"][0]
        print("first id:", f.get("id"), "properties keys:", list(f.get("properties", {}).keys()), flush=True)
except Exception as e:
    print("ERROR:", repr(e), flush=True)