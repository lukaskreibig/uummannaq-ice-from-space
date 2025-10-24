#!/usr/bin/env python3
"""
Fast CloudSEN12 UNetMobV2_V2 – sea-ice / water / cloud
(debug build 2025-05-06 – v5 “solid + light”)

* solid ice  (yellow) : NDSI > 0.70 & NIR bright & SWIR dark
* light ice  (cyan)   : 0.40 < NDSI < 0.70 & NDVI > –0.10
* water      (blue)   : NDWI > 0.05 and not ice
"""

# ───────── imports & env ────────────────────────────────────
import os, sys, csv, gc, time, queue, threading, pathlib, logging, datetime
import argparse, textwrap, concurrent.futures as cf
os.environ.setdefault("AWS_NO_SIGN_REQUEST", "YES")

import numpy as np
from   pystac_client import Client
try:
    import dask.typing; dask.typing.Key
except Exception:
    import dask.typing, types; dask.typing.Key = object   # type: ignore
if not hasattr(np, "round_"): np.round_ = np.round

import torch, torch.nn.functional as F
from torch.amp          import autocast
from odc.stac           import load
from PIL                import Image
import matplotlib.pyplot as plt
from scipy.ndimage      import binary_closing
import segmentation_models_pytorch as smp

# ───────── CLI / logging ────────────────────────────────────
def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--log", default="INFO",
                    choices=["DEBUG","INFO","WARNING","ERROR"])
    return ap.parse_args()

logging.basicConfig(format="%(asctime)s  %(levelname)-8s %(message)s",
                    datefmt="%H:%M:%S", level=parse_args().log.upper())

# ───────── user settings ────────────────────────────────────
CHECKPOINT_FILE = "UNetMobV2_V2.pt"
LANDMASK_FILE   = "landmask_template.png"
CSV_FILE        = "summary_test.csv"
OUT_DIR         = pathlib.Path("out");  IMG_DIR = OUT_DIR / "imgtest"
IMG_DIR.mkdir(parents=True, exist_ok=True)

# The actual coordinates of our picture are -52.373222 70.787129 -51.905163 70.629154

SEARCH_AOI = {"type":"Polygon","coordinates":[[
    [-52.336121,70.788206],[-51.945564,70.788206],
    [-51.945564,70.628226],[-52.336121,70.628226],
    [-52.336121,70.788206]]]}
DATE_RANGE = "2017-04-03T00:00:00Z/2025-03-17T23:59:59Z"

# ───────── thresholds ──────────────────────────────────────


# NDSI_LIGHT_THR = 0.40   # global MODIS/VIIRS value
# NDSI_SOLID_THR = 0.70   # pure dry snow
# NDVI_MIN       = -0.10  # keeps wet ice, rejects water
# VIS_BRIGHT_MIN = 0.08   # screens shaded pixels
# NIR_BRIGHT_MIN = 0.17   # solid ice only
# SWIR_DARK_MAX  = 0.10   # solid ice only
# NDWI_THR       = 0.05   # water vs. land/ice

# NDSI_LIGHT_THR   ↑ stricter → loses thin/wet ice, ↓ admits slush
# NDSI_SOLID_THR   ↑ stricter yellow, ↓ more yellow
# NDVI_MIN         ↑ stricter water rejection, ↓ looser
# VIS_BRIGHT_MIN   ↑ removes dim pixels,        ↓ keeps darker ice
# NIR_BRIGHT_MIN   ↑ stricter solid,            ↓ larger solid mask
# SWIR_DARK_MAX    ↑ larger solid mask,         ↓ purer solid ice
# NDWI_THR         ↑ fewer water pixels,        ↓ more water

NDSI_LIGHT_THR   = 0.31
NDSI_SOLID_THR   = 0.52
NDVI_MIN         = -0.20  # (de-activated in masks below)
VIS_BRIGHT_MIN   = 0.08   # (de-activated in masks below)
NIR_BRIGHT_MIN   = 0.17   # (de-activated in masks below)
SWIR_DARK_MAX    = 0.10   # (de-activated in masks below)
NDWI_THR         = 0.25   # (de-activated in masks below)

NODATA_THR = 0.20
DL_THREADS = 4
DECODE_QUEUE = 3
OVERWRITE_CSV = True

logging.info("NDSI_LIGHT_THR   = %.2f", NDSI_LIGHT_THR)
logging.info("NDSI_SOLID_THR   = %.2f", NDSI_SOLID_THR)
logging.info("NDVI_MIN         = %.2f", NDVI_MIN)
logging.info("VIS_BRIGHT_MIN   = %.2f", VIS_BRIGHT_MIN)
logging.info("NIR_BRIGHT_MIN   = %.2f", NIR_BRIGHT_MIN)
logging.info("SWIR_DARK_MAX    = %.2f", SWIR_DARK_MAX)
logging.info("NDWI_THR         = %.2f", NDWI_THR)
logging.info("OVERWRITE_CSV    = %s", OVERWRITE_CSV)

# ───────── band list ────────────────────────────────────────
bands = ["coastal","blue","green","red",
         "rededge1","rededge2","rededge3",
         "nir","nir08","nir09","cirrus","swir16","swir22"]
g_idx, red_idx, nir_idx, sw_idx = map(bands.index,
                                      ["green","red","nir","swir16"])

# ───────── helpers (unchanged) ──────────────────────────────

proc_times = []          # store per-tile wall-clock durations


def fix_l1c_hrefs(item):
    for a in item.assets.values():
        if "sentinel-s2-l2a" in a.href:
            a.href = a.href.replace("sentinel-s2-l2a", "sentinel-s2-l1c")
    return item

def preview(mask):
    hi = Image.fromarray((mask*255).astype(np.uint8),"L")
    return hi.resize((2048,2048),Image.NEAREST).resize((512,512),Image.BILINEAR)

def pad32(t): _,h,w=t.shape; return F.pad(t,(0,(-w)%32,0,(-h)%32))

def overlay_rgb(rgb, solid, light, water, cloud, land, nodata):
    base = rgb.convert("RGBA")
    ov   = np.zeros((*base.size[::-1],4), np.uint8)
    layers = [
        (solid,              (255,255,0)),
        (light & ~solid,     (0,255,255)),
        (water,              (0,0,255)),
        (cloud,              (200,200,200)),
        (land,               (150,75,0)),
        (nodata,             (255,0,255))
    ]
    for m,col in layers:
        im = Image.fromarray((m*255).astype(np.uint8)).resize(base.size,Image.NEAREST)
        ov[np.array(im)>127] = (*col,120)
    return Image.alpha_composite(base,Image.fromarray(ov,"RGBA")).convert("RGB")

# ───────── device & CNN (unchanged) ─────────────────────────
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
model.eval()

# ───────── CSV init (unchanged) ─────────────────────────────
header = ["tile_id","timestamp",
          "solid_px","light_px","water_px","cloud_px","land_px","nodata_px","unknown_px",
          "solid_pct","light_pct","water_pct","cloud_pct","land_pct","nodata_pct",
          "mean_ndsi_solid","mean_ndsi_light","mean_ndwi_water",
          "eo_cloud_cover","sun_elev","sun_azim","edge_gap"]
csv_path = pathlib.Path(CSV_FILE)
done=set()
if csv_path.exists():
    with csv_path.open() as fh:
        rdr=csv.reader(fh); next(rdr,None)
        done={(r[0],r[1]) for r in rdr}
csv_fh=csv_path.open("a",newline=""); csv_wr=csv.writer(csv_fh)
if csv_path.stat().st_size==0: csv_wr.writerow(header)

# ───────── STAC search (unchanged) ──────────────────────────
client=Client.open("https://earth-search.aws.element84.com/v1")
tiles=list(client.search(collections=["sentinel-2-l1c"],
                         intersects=SEARCH_AOI,
                         datetime=DATE_RANGE).items())
tiles=[fix_l1c_hrefs(t) for t in tiles]
tiles={t.datetime.date():t for t in tiles}.values()
tiles=[t for t in tiles if (t.id,t.datetime.strftime("%Y%m%dT%H%M%S")) not in done]
logging.info("%d new tile(s) to process\n",len(tiles))
if not tiles: sys.exit(0)

# ───────── threaded download & decode (unchanged) ───────────
def _dl(it): _=[a.href for a in it.assets.values()]; return it
dl_pool=cf.ThreadPoolExecutor(max_workers=DL_THREADS)
dl_q, decode_q = queue.Queue(), queue.Queue(maxsize=DECODE_QUEUE)
def stageA():
    for t in tiles: dl_q.put(dl_pool.submit(_dl,t))
    dl_q.put(None)
def stageB():
    while True:
        fut = dl_q.get()
        if fut is None: decode_q.put(None); break
        try: it = fix_l1c_hrefs(fut.result()); ds = load([it],geopolygon=SEARCH_AOI,chunks={})
        except Exception as e: ds=e
        decode_q.put((it,ds))
threading.Thread(target=stageA,daemon=True).start()
threading.Thread(target=stageB,daemon=True).start()

# ───────── main loop ────────────────────────────────────────
dur=[]; idx=0
while True:
    it_ds=decode_q.get()
    if it_ds is None: break
    t0 = time.time()
    it,ds = it_ds
    idx+=1; ts=it.datetime.strftime("%Y%m%dT%H%M%S")
    logging.info("[%d/%d] %s  %s",idx,len(tiles),it.id,ts)
    if isinstance(ds,Exception): logging.error("   skipped – load failed"); continue
    if not all(b in ds.data_vars for b in ("red","green","blue")):
        logging.error("   skipped – RGB band missing"); continue

    # ---------- RGB preview ---------------------------------
    R,G,B=[ds[c][0].values.astype(np.float32) for c in ("red","green","blue")]
    scale=255. if R.max()<=1.0 else 255./10000.
    rgb512=Image.merge("RGB",[Image.fromarray(np.clip(ch*scale,0,255).astype(np.uint8),"L")
                              for ch in (R,G,B)]).resize((512,512),Image.BILINEAR)

    # ---------- 40-m reflectance cube -----------------------
    cube=np.stack([ds[b][0].values for b in bands]).astype(np.float32)
    if cube.max()>10: cube/=10000.
    H4,W4=(cube.shape[1]//4)*4,(cube.shape[2]//4)*4
    small=F.avg_pool2d(torch.from_numpy(cube[None])[...,:H4,:W4],4,4).squeeze(0)
    s_np=small.numpy(); _,h4,w4=small.shape

    nodata=(s_np.sum(0)<1e-6)
    land=np.array(Image.open(LANDMASK_FILE).convert("L")
                  .resize((w4,h4),Image.NEAREST))>127

    # ---------- Cloud CNN -----------------------------------
    with autocast(device_type=device.type), torch.no_grad():
        prob=torch.softmax(model(pad32(small)[None].to(device)),1)[0,1].cpu().numpy()
    cloud=binary_closing(prob[:h4,:w4]>0.5,structure=np.ones((3,3)))

    # ---------- Indices -------------------------------------
    ndsi=(s_np[g_idx]-s_np[sw_idx])/(s_np[g_idx]+s_np[sw_idx]+1e-6)
    # ndvi=(s_np[nir_idx]-s_np[red_idx])/(s_np[nir_idx]+s_np[red_idx]+1e-6)
    ndwi=(s_np[g_idx]-s_np[nir_idx])/(s_np[g_idx]+s_np[nir_idx]+1e-6)

    # vis_bright = s_np[g_idx]  > VIS_BRIGHT_MIN
    # nir_bright = s_np[nir_idx]> NIR_BRIGHT_MIN
    # swir_dark  = s_np[sw_idx] < SWIR_DARK_MAX

    ice_solid = (ndsi > NDSI_SOLID_THR) & \
                ~cloud & ~land & ~nodata 
    # deactivated & (ndwi < NDWI_THR) & vis_bright &

    ice_light = (ndsi > NDSI_LIGHT_THR) & (ndsi < NDSI_SOLID_THR) & ~cloud & ~land & ~nodata 
    # deactivated & (ndwi < NDWI_THR) & (ndvi > NDVI_MIN) & vis_bright 

    water = (ndwi > NDWI_THR) & ~ice_light & ~ice_solid & ~cloud & ~land & ~nodata

    # ---------- overlay PNG (unchanged) ---------------------
    overlay=overlay_rgb(rgb512, ice_solid, ice_light, water, cloud, land, nodata)
    overlay.save(IMG_DIR/f"{it.id}_{ts}_overlay512.png")

    # # ---------- threshold-diagnostic panel (NEW) ------------
    # diag_masks=[(ndsi>NDSI_LIGHT_THR,"NDSI>light"),
    #             (ndsi>NDSI_SOLID_THR,"NDSI>solid"),
    #             (ndvi>NDVI_MIN,"NDVI>min"),
    #             (vis_bright,"VIS>min"),
    #             (ndwi>NDWI_THR,"NDWI>thr"),
    #             (ice_solid,"solid mask"),
    #             (ice_light,"light mask"),
    #             (water,"water mask")]
    # fig_d,axs=plt.subplots(2,4,figsize=(12,10))
    # for ax,(m,title) in zip(axs.flatten(),diag_masks):
    #     ax.imshow(preview(m),cmap="gray"); ax.set_title(title); ax.axis("off")
    # plt.suptitle(f"{it.id}  {ts} – thresholds",fontsize=11); plt.tight_layout()
    # fig_d.savefig(IMG_DIR/f"{it.id}_{ts}_thresholds.png",dpi=150); plt.close(fig_d)
    # --------------------------------------------------------

    # ---------- six-panel quick-look (unchanged) ------------
    fig,ax=plt.subplots(2,3,figsize=(13,8))
    ax[0,0].imshow(rgb512);                   ax[0,0].set_title("RGB");      ax[0,0].axis("off")
    ax[0,1].imshow(preview(cloud),cmap="gray"); ax[0,1].set_title("Cloud"); ax[0,1].axis("off")
    ax[0,2].imshow(preview(land),cmap="gray");  ax[0,2].set_title("Land");  ax[0,2].axis("off")
    ax[1,0].imshow(preview(ice_solid),cmap="gray"); ax[1,0].set_title("Solid ice");ax[1,0].axis("off")
    ax[1,1].imshow(preview(ice_light),cmap="gray"); ax[1,1].set_title("Light ice");ax[1,1].axis("off")
    ax[1,2].imshow(overlay);                 ax[1,2].set_title("Overlay"); ax[1,2].axis("off")
    plt.suptitle(f"{it.id}  {ts}",fontsize=11); plt.tight_layout()
    fig.savefig(IMG_DIR/f"{it.id}_{ts}_panel.png",dpi=150)
    plt.close(fig)

    # ---------- CSV (unchanged) ------------------------------
    total=h4*w4
    cnt_water,cnt_cloud=int(water.sum()),int(cloud.sum())
    cnt_land,cnt_nodata=int(land.sum()),int(nodata.sum())
    unknown=total-(ice_solid.sum()+ice_light.sum()+cnt_water+cnt_cloud+cnt_land+cnt_nodata)
    csv_wr.writerow([
        it.id, ts,
        int(ice_solid.sum()), int(ice_light.sum()), cnt_water, cnt_cloud,
        cnt_land, cnt_nodata, unknown,
        round(ice_solid.sum()/total,4), round(ice_light.sum()/total,4), round(cnt_water/total,4),
        round(cnt_cloud/total,4), round(cnt_land/total,4), round(cnt_nodata/total,4),
        round(np.nanmean(ndsi[ice_solid]),4) if ice_solid.any() else "",
        round(np.nanmean(ndsi[ice_light]),4) if ice_light.any() else "",
        round(np.nanmean(ndwi[water]),4)     if water.any()     else "",
        int((cnt_nodata/total)>=NODATA_THR)])
    csv_fh.flush()

    # ---------- per-tile timing & global ETA (NEW) ----------
    dt = time.time() - t0                # seconds for this tile
    proc_times.append(dt)
    mean_dt = sum(proc_times)/len(proc_times)
    eta_sec = mean_dt * (len(tiles) - idx)
    logging.info("   elapsed %.1fs  |  Ø %.1fs  |  ETA %s",
                 dt, mean_dt,
                 datetime.timedelta(seconds=int(eta_sec)))
    # --------------------------------------------------------

    dur.append(time.time()-datetime.datetime.strptime(ts,"%Y%m%dT%H%M%S").timestamp())
    del ds,cube,small; gc.collect()
    if torch.backends.mps.is_available(): torch.mps.empty_cache()
    elif torch.cuda.is_available():       torch.cuda.empty_cache()

csv_fh.close()
logging.info("Finished – results appended to %s", CSV_FILE)
