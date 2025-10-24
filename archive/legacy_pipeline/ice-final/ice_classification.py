#!/usr/bin/env python3
"""
Fast CloudSEN12 UNetMobV2_V2 – sea-ice / water / cloud
• download-pool  +  decode-thread   (hides I/O)
• full-scene inference (no patches) + torch.compile()
• morph-closing cloud mask
• résumé-safe CSV  +  PNG panels
"""

# ───────────── imports & env ──────────────────────────────────
import os, sys, csv, gc, time, queue, threading, pathlib, logging, datetime
import concurrent.futures as cf
os.environ.setdefault("AWS_NO_SIGN_REQUEST", "YES")        # GDAL-S3 (public)

import numpy as np
from   pystac_client import Client
try:        # dask.typing.Key-hack (old dask versions)
    import dask.typing; dask.typing.Key
except Exception:
    import dask.typing, types; dask.typing.Key = object       # type: ignore

if not hasattr(np, "round_"): np.round_ = np.round

import torch, torch.nn.functional as F
from torch.amp          import autocast
from odc.stac           import load
from PIL                import Image
import matplotlib.pyplot as plt
from scipy.ndimage      import binary_closing
import segmentation_models_pytorch as smp

# ───────────── user settings ─────────────────────────────────
CHECKPOINT_FILE = "UNetMobV2_V2.pt"
LANDMASK_FILE   = "landmask_template.png"
CSV_FILE        = "summary.csv"
OUT_DIR         = pathlib.Path("out");  IMG_DIR = OUT_DIR / "img"
IMG_DIR.mkdir(parents=True, exist_ok=True)

SEARCH_AOI = {"type":"Polygon","coordinates":[[
    [-52.336121,70.788206],[-51.945564,70.788206],
    [-51.945564,70.628226],[-52.336121,70.628226],
    [-52.336121,70.788206]]]}
DATE_RANGE = "2015-01-01T00:00:00Z/2022-06-06T23:59:59Z"


NDSI_THR, NDWI_THR = 0.42, 0.05
NODATA_THR         = 0.20          # ≥20 % black → edge-gap
BATCH_SIZE         = 1             # whole scene → single batch
DL_THREADS         = 4             # parallel JP2 fetch
DECODE_QUEUE       = 3             # scenes buffered between stages

bands   = ["coastal","blue","green",""
"red","rededge1","rededge2","rededge3",
           "nir","nir08","nir09","cirrus","swir16","swir22"]
g_idx, nir_idx, sw_idx = map(bands.index, ["green","nir","swir16"])
colors  = {"ice":(0,255,255),"water":(0,0,255),
           "cloud":(200,200,200),"land":(150,75,0),"nodata":(255,0,255)}

# ───────────── logging / CSV init ────────────────────────────
logging.basicConfig(format="%(asctime)s  %(levelname)-5s %(message)s",
                    datefmt="%H:%M:%S", level=logging.INFO)

header = ["tile_id","timestamp",
          "ice_px","water_px","cloud_px","land_px","nodata_px","unknown_px",
          "ice_pct","water_pct","cloud_pct","land_pct","nodata_pct",
          "mean_ndsi_ice","mean_ndwi_water",
          "eo_cloud_cover","sun_elev","sun_azim","edge_gap"]

csv_path = pathlib.Path(CSV_FILE)
done = set()
if csv_path.exists():
    with csv_path.open() as fh:
        rdr = csv.reader(fh); next(rdr, None)
        done = {(r[0],r[1]) for r in rdr}

csv_fh = csv_path.open("a", newline="")
csv_wr = csv.writer(csv_fh)
if csv_path.stat().st_size == 0:
    csv_wr.writerow(header)

# ───────────── helpers ───────────────────────────────────────
def fix_l1c_hrefs(item):
    for a in item.assets.values():
        if "sentinel-s2-l2a" in a.href:
            a.href = a.href.replace("sentinel-s2-l2a", "sentinel-s2-l1c")
    return item

def preview(mask: np.ndarray):
    hi = Image.fromarray((mask*255).astype(np.uint8),"L")
    return hi.resize((2048,2048),Image.NEAREST).resize((512,512),Image.BILINEAR)

def overlay_rgb(rgb, ice, water, cloud, land, nodata):
    base = rgb.convert("RGBA")
    ov   = np.zeros((*base.size[::-1],4), np.uint8)
    for m,lbl in [(ice,"ice"),(water,"water"),(cloud,"cloud"),
                  (land,"land"),(nodata,"nodata")]:
        im = Image.fromarray((m*255).astype(np.uint8)).resize(base.size,Image.NEAREST)
        ov[np.array(im)>127] = (*colors[lbl],120)
    return Image.alpha_composite(base,Image.fromarray(ov,"RGBA")).convert("RGB")

def pad32(t: torch.Tensor):
    """pad bottom/right to next multiple of 32"""
    _,h,w = t.shape
    tgt_h = ((h+31)//32)*32
    tgt_w = ((w+31)//32)*32
    return F.pad(t,(0,tgt_w-w,0,tgt_h-h)) if (tgt_h!=h or tgt_w!=w) else t

# ───────────── device & CNN ──────────────────────────────────
device = (torch.device("mps") if torch.backends.mps.is_available()
      else torch.device("cuda") if torch.cuda.is_available()
      else torch.device("cpu"))
logging.info("device: %s", device)

model = smp.Unet("mobilenet_v2", encoder_weights=None,
                 in_channels=13, classes=4).to(device)
ckpt  = torch.load(CHECKPOINT_FILE, map_location=device)
model.load_state_dict({k.removeprefix("module.").removeprefix("model."):v
                       for k,v in ckpt.get("model_state_dict",ckpt).items()},
                      strict=False)
try:
    model = torch.compile(model, backend="aot_eager")
    logging.info("model compiled with torch.compile()")
except Exception:
    logging.info("torch.compile unavailable – running eager")
model.eval()

# ───────────── STAC search ───────────────────────────────────
client = Client.open("https://earth-search.aws.element84.com/v1")
tiles  = list(client.search(collections=["sentinel-2-l1c"],
                            intersects=SEARCH_AOI,
                            datetime=DATE_RANGE).items())
tiles  = [fix_l1c_hrefs(t) for t in tiles]
tiles  = {t.datetime.date(): t for t in tiles}.values()
tiles  = [t for t in tiles if (t.id,t.datetime.strftime("%Y%m%dT%H%M%S")) not in done]
total  = len(tiles)
if not total:
    logging.info("nothing new to process"); sys.exit(0)
logging.info("%d new tile(s) to process\n", total)

# ───────────── Stage A – download pool -----------------------
def _download_scene(item):
    _ = [a.href for a in item.assets.values()]    # trigger vsicurl cache
    return item

dl_pool  = cf.ThreadPoolExecutor(max_workers=DL_THREADS)
dl_q     = queue.Queue()
def stageA():
    for t in tiles: dl_q.put(dl_pool.submit(_download_scene,t))
    dl_q.put(None)
threading.Thread(target=stageA, daemon=True).start()

# ───────────── Stage B – decode thread -----------------------
decode_q = queue.Queue(maxsize=DECODE_QUEUE)
def decoder():
    while True:
        fut = dl_q.get()
        if fut is None:
            decode_q.put(None); break
        try:
            item = fut.result()
            ds   = load([item], geopolygon=SEARCH_AOI,
                        fail_on_error=False, groupby=None, chunks={})
        except Exception as e:
            ds = e
        decode_q.put((item, ds))
threading.Thread(target=decoder, daemon=True).start()

# ───────────── Stage C – main loop ---------------------------
dur, idx = [], 0
while True:
    it_ds = decode_q.get()
    if it_ds is None: break
    it, ds = it_ds
    idx += 1; ts = it.datetime.strftime("%Y%m%dT%H%M%S")
    logging.info("[%d/%d] %s", idx, total, it.id)
    t0 = time.time()

    if isinstance(ds, Exception) or not all(b in ds.data_vars for b in ("red","green","blue")):
        logging.error("   skipped – load failed or mandatory band missing"); continue

    # ---------- 10 m RGB preview -----------------------------
    R,G,B = [ds[c].isel(time=0).values.astype(np.float32) for c in ("red","green","blue")]
    scale = 255. if R.max()<=1 else 255./10000.
    rgb512 = Image.merge("RGB",[
        Image.fromarray(np.clip(c*scale,0,255).astype(np.uint8),"L")
        for c in (R,G,B)]).resize((512,512), Image.BILINEAR)

    # ---------- 40 m cube  -----------------------------------
    cube  = np.stack([ds[b].isel(time=0).values for b in bands]).astype(np.float32)
    if cube.max()>1.1: cube /= 10000.
    C,H,W = cube.shape; H4,W4 = (H//4)*4,(W//4)*4
    small = F.avg_pool2d(torch.from_numpy(cube[None])[...,:H4,:W4],4,4).squeeze(0)
    small_pad = pad32(small)                     # (C,H',W') divisible by 32
    s_np = small.numpy(); _,h4,w4 = small.shape

    nodata = (s_np.sum(0)<1e-6)
    land   = np.array(Image.open(LANDMASK_FILE).convert("L")
                      .resize((w4,h4),Image.NEAREST))>127
    nodata_px = int(nodata.sum()); nodata_pct = nodata_px/(h4*w4)
    edge_gap  = int(nodata_pct>=NODATA_THR)

    # ---------- Cloud CNN – single pass ----------------------
    with autocast(device_type=device.type), torch.no_grad():
        prob = torch.softmax(model(small_pad.unsqueeze(0).to(device)),1)[0,1].cpu().numpy()
    prob = prob[:h4,:w4]                  # remove padding
    cloud = prob > 0.5
    cloud = binary_closing(cloud, structure=np.ones((3,3)))

    # ---------- ND-indices → classes -------------------------
    ndsi  = (s_np[g_idx]-s_np[sw_idx])/(s_np[g_idx]+s_np[sw_idx]+1e-6)
    ndwi  = (s_np[g_idx]-s_np[nir_idx])/(s_np[g_idx]+s_np[nir_idx]+1e-6)
    ice   = (ndsi>NDSI_THR)&~cloud&~land&~nodata
    water = (ndwi>NDWI_THR)&~ice&~cloud&~land&~nodata

    total_px = h4*w4
    cnt = {"ice":int(ice.sum()),"water":int(water.sum()),
           "cloud":int(cloud.sum()),"land":int(land.sum()),
           "nodata":nodata_px}
    unknown  = total_px - sum(cnt.values())
    pct      = {k:v/total_px for k,v in cnt.items()}
    mean_ndsi= float(np.nanmean(ndsi[ice]))   if cnt["ice"] else np.nan
    mean_ndwi= float(np.nanmean(ndwi[water])) if cnt["water"] else np.nan

    # ---------- save ----------------------------------------
    overlay = overlay_rgb(rgb512, ice, water, cloud, land, nodata)
    overlay.save(IMG_DIR/f"{it.id}_{ts}_overlay512.png")

    fig,ax = plt.subplots(2,3,figsize=(13,8))
    ax[0,0].imshow(rgb512);                   ax[0,0].set_title("RGB");      ax[0,0].axis("off")
    ax[0,1].imshow(preview(cloud),cmap="gray"); ax[0,1].set_title("Cloud"); ax[0,1].axis("off")
    ax[0,2].imshow(preview(land),cmap="gray");  ax[0,2].set_title("Land");  ax[0,2].axis("off")
    ax[1,0].imshow(preview(ice),cmap="gray");   ax[1,0].set_title("Sea-ice");ax[1,0].axis("off")
    ax[1,1].imshow(preview(water),cmap="gray"); ax[1,1].set_title("Water"); ax[1,1].axis("off")
    ax[1,2].imshow(overlay);                   ax[1,2].set_title("Overlay");ax[1,2].axis("off")
    plt.suptitle(f"{it.id}  {ts}",fontsize=11); plt.tight_layout()
    fig.savefig(IMG_DIR/f"{it.id}_{ts}_panel.png",dpi=150)
    plt.close(fig)

    csv_wr.writerow([
        it.id, ts,
        cnt["ice"],cnt["water"],cnt["cloud"],cnt["land"],
        nodata_px, unknown,
        round(pct["ice"],4),round(pct["water"],4),
        round(pct["cloud"],4),round(pct["land"],4),round(nodata_pct,4),
        round(mean_ndsi,4) if not np.isnan(mean_ndsi) else "",
        round(mean_ndwi,4) if not np.isnan(mean_ndwi) else "",
        it.properties.get("eo:cloud_cover",""),
        it.properties.get("sat:solar_elevation",""),
        it.properties.get("sat:solar_azimuth",""),
        edge_gap
    ])
    csv_fh.flush()

    dur.append(time.time()-t0)
    mean_dt = sum(dur)/len(dur)
    eta     = datetime.timedelta(seconds=int(mean_dt*(total-idx)))
    logging.info("   Ø %5.1fs  |  ETA %s", mean_dt, eta)

    del ds,cube,small; gc.collect()
    if torch.backends.mps.is_available(): torch.mps.empty_cache()
    elif torch.cuda.is_available():       torch.cuda.empty_cache()

csv_fh.close()
logging.info("Finished – results appended to %s", CSV_FILE)
