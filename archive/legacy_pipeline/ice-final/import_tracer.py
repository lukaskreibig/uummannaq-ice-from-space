# test_imports.py
import time, sys
print("start import test", flush=True)

def try_import(name, alias=None):
    print(f"IMPORT START: {name}", flush=True)
    t0 = time.time()
    try:
        module = __import__(name) if alias is None else __import__(name, fromlist=[alias])
        elapsed = time.time() - t0
        print(f"IMPORT OK: {name} ({elapsed:.2f}s)", flush=True)
        return module
    except Exception as e:
        print(f"IMPORT FAIL: {name}  -> {e!r}", flush=True)
        raise

# lightweight ones first
try_import("numpy")
try_import("pystac_client")
try_import("odc.stac")
try_import("torch")
try_import("segmentation_models_pytorch")
print("all imports attempted", flush=True)