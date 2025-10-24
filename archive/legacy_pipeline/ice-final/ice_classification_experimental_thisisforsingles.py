#!/usr/bin/env python3
"""
Verbose debug run — processing at pooled 40 m, exporting full-resolution PNGs.
"""

# ---------- bootstrap logging BEFORE heavy imports ----------
import sys, time, argparse, logging
print("BOOT: script starting", flush=True)

def parse_args_boot():
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("--log", default="DEBUG",
                    choices=["DEBUG","INFO","WARNING","ERROR"])
    return ap.parse_known_args()[0]

_boot_args = parse_args_boot()
logging.basicConfig(format="%(asctime)s  %(levelname)-8s %(message)s",
                    datefmt="%H:%M:%S",
                    level=_boot_args.log.upper())
log = logging.getLogger("boot")

def _trace_import(label, fn):
    t0 = time.time()
    print(f"BOOT: importing {label} ...", flush=True)
    out = fn()
    print(f"BOOT: imported {label} in {time.time()-t0:.2f}s", flush=True)
    return out

# ---------- traced imports ----------
import os, csv, gc, queue, threading, pathlib, datetime, textwrap, concurrent.futures as cf
os.environ.setdefault("AWS_NO_SIGN_REQUEST", "YES")

np = _trace_import("numpy", lambda: __import__("numpy"))
if not hasattr(np, "round_"): np.round_ = np.round

pystac_client = _trace_import("pystac_client", lambda: __import__("pystac_client"))
Client = pystac_client.Client

# dask.typing shim
try:
    _trace_import("dask.typing", lambda: __import__("dask").typing)
    import dask.typing; dask.typing.Key
except Exception:
    import dask.typing, types; dask.typing.Key = object   # type: ignore

# torch & friends
torch = _trace_import("torch", lambda: __import__("torch"))
F = _trace_import("torch.nn.functional", lambda: __import__("torch.nn.functional", fromlist=["dummy"]))
autocast = _trace_import("torch.amp.autocast", lambda: __import__("torch.amp", fromlist=["autocast"])).autocast

# odc.stac
odc_stac = _trace_import("odc.stac", lambda: __import__("odc.stac", fromlist=["load"]))
load = odc_stac.load

# PIL
Image = _trace_import("PIL.Image", lambda: __import__("PIL.Image", fromlist=["dummy"]))

# matplotlib (only for quick-look panel)
plt = _trace_import("matplotlib.pyplot", lambda: __import__("matplotlib.pyplot", fromlist=["pyplot"]))

# scipy
binary_closing = _trace_import("scipy.ndimage.binary_closing",
                               lambda: __import__("scipy.ndimage", fromlist=["binary_closing"])).binary_closing

# segmentation_models_pytorch
smp = _trace_import("segmentation_models_pytorch",
                    lambda: __import__("segmentation_models_pytorch"))

# ---------- switch to app logger ----------
log = logging.getLogger(__name__)
log.debug("Starting script; argv=%s", sys.argv)

# ---------------- CLI / logging ---------------------
def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--log", default="DEBUG",
                    choices=["DEBUG","INFO","WARNING","ERROR"],
                    help="Logging level (default DEBUG for full trace)")
    return ap.parse_args()

args = parse_args()
logging.basicConfig(format="%(asctime)s  %(levelname)-8s %(message)s",
                    datefmt="%H:%M:%S", level=args.log.upper())
log = logging.getLogger(__name__)

# ---------------- user settings ---------------------
CHECKPOINT_FILE = "/src/ice-final/UNetMobV2_V2.pt"
LANDMASK_FILE   = "src/ice-final/landmask_template.png"
CSV_FILE        = "summary_test_singleimage.csv"
OUT_DIR         = pathlib.Path("out");  IMG_DIR = OUT_DIR / "imgtestsingleoutput"
IMG_DIR.mkdir(parents=True, exist_ok=True)
log.debug("Out dir: %s  Img dir: %s", OUT_DIR, IMG_DIR)

SEARCH_AOI = {"type":"Polygon","coordinates":[
    [[-52.336121,70.788206],[-51.945564,70.788206],
     [-51.945564,70.628226],[-52.336121,70.628226],
     [-52.336121,70.788206]]
]}
DATE_RANGE = "2025-05-14T00:00:00Z/2025-05-15T00:00:00Z"

# ---------------- thresholds ------------------------
NDSI_LIGHT_THR   = 0.31
NDSI_SOLID_THR   = 0.52
NDVI_MIN         = -0.20
VIS_BRIGHT_MIN   = 0.08
NIR_BRIGHT_MIN   = 0.17
SWIR_DARK_MAX    = 0.10
NDWI_THR         = 0.25

NODATA_THR   = 0.20
DL_THREADS   = 4
DECODE_QUEUE = 3
OVERWRITE_CSV = True

log.info("Parameters: NDSI_LIGHT=%.2f NDSI_SOLID=%.2f NDWI=%.2f",
         NDSI_LIGHT_THR, NDSI_SOLID_THR, NDWI_THR)
log.info("DL_THREADS=%d DECODE_QUEUE=%d", DL_THREADS, DECODE_QUEUE)

# ---------------- band list ------------------------
bands = ["coastal","blue","green","red",
         "rededge1","rededge2","rededge3",
         "nir","nir08","nir09","cirrus","swir16","swir22"]
g_idx, red_idx, nir_idx, sw_idx = map(bands.index, ["green","red","nir","swir16"])

# ---------------- helpers --------------------------
proc_times = []          # store per-tile wall-clock durations

def fix_l1c_hrefs(item):
    for a in item.assets.values():
        if "sentinel-s2-l2a" in a.href:
            a.href = a.href.replace("sentinel-s2-l2a", "sentinel-s2-l1c")
    return item

def preview(mask):
    hi = Image.fromarray((mask*255).astype(np.uint8),"L")
    return hi.resize((2048,2048),Image.NEAREST)

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

def upsample_bool(mask_bool: np.ndarray, size_xy):
    """Nearest-neighbor upsample of a boolean mask to (W,H)"""
    return (np.array(
        Image.fromarray((mask_bool.astype(np.uint8) * 255), "L").resize(size_xy, Image.NEAREST)
    ) > 127)

# ---------------- device & model --------------------
device = (torch.device("mps") if torch.backends.mps.is_available()
      else torch.device("cuda") if torch.cuda.is_available()
      else torch.device("cpu"))
log.info("device: %s (mps=%s cuda=%s)", device, torch.backends.mps.is_available(), torch.cuda.is_available())

model = smp.Unet("mobilenet_v2", encoder_weights=None, in_channels=13, classes=4).to(device)
if not pathlib.Path(CHECKPOINT_FILE).exists():
    log.warning("Checkpoint file %s not found — model will use random weights.", CHECKPOINT_FILE)
else:
    try:
        ckpt  = torch.load(CHECKPOINT_FILE, map_location=device)
        state = ckpt.get("model_state_dict",ckpt)
        mapped = {k.removeprefix("module.").removeprefix("model."):v for k,v in state.items()}
        model.load_state_dict(mapped, strict=False)
        log.info("Loaded checkpoint with %d keys (strict=False).", len(mapped))
    except Exception:
        log.exception("Failed to load checkpoint %s — continuing with partial/random weights", CHECKPOINT_FILE)
model.eval()

# ---------------- CSV init --------------------------
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

# ---------------- STAC search -----------------------
client=Client.open("https://earth-search.aws.element84.com/v1")
tiles=list(client.search(collections=["sentinel-2-l1c"],
                         intersects=SEARCH_AOI,
                         datetime=DATE_RANGE).items())
tiles=[fix_l1c_hrefs(t) for t in tiles]
tiles={t.datetime.date():t for t in tiles}.values()
tiles=[t for t in tiles if (t.id,t.datetime.strftime("%Y%m%dT%H%M%S")) not in done]
logging.info("%d new tile(s) to process\n",len(tiles))
if not tiles: sys.exit(0)

# ---------------- threaded download & decode ----------
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

# ---------------- main loop --------------------------
proc_times=[]; idx=0
try:
    while True:
        item = decode_q.get()
        if item is None:
            log.info("Main loop: received sentinel; breaking")
            break

        t0 = time.time()
        it,ds = item
        idx+=1; ts=it.datetime.strftime("%Y%m%dT%H%M%S")
        log.info("[%d/%d] item=%s ts=%s", idx, len(tiles), it.id, ts)

        baseline = it.properties.get("s2:processing_baseline","N/A")
        log.info("   processing baseline: %s", baseline)

        if isinstance(ds,Exception):
            log.error("   skipped – load failed for %s (exception object)", it.id)
            continue
        if not all(b in ds.data_vars for b in ("red","green","blue")):
            log.error("   skipped – RGB band missing in dataset data_vars=%s", list(ds.data_vars.keys()))
            continue

        # ----- RGB: native + 2048 preview (preview only for quicklook) -----
        R,G,B = [ds[c][0].values.astype(np.float32) for c in ("red","green","blue")]
        scale = 255. if R.max() <= 1.0 else 255./10000.
        rgb_native = Image.merge("RGB", [Image.fromarray(np.clip(ch*scale,0,255).astype(np.uint8), "L")
                                         for ch in (R,G,B)])
        rgb512 = rgb_native.resize((2048, 2048), Image.BILINEAR)

        # ---------- harmonised 40-m reflectance cube (FIXED) -------
        # The STAC field s2:processing_baseline tells us whether
        # the +1000-DN shift is present (baseline ≥ 04.00) or not.

        baseline_str = it.properties.get("s2:processing_baseline", "0.0")
        baseline_maj = int(float(baseline_str))    # "03.09" → 3, "04.00" → 4 …

        def toa_reflectance(band_da, band_name):
            # Earth-Search COGs have no add_offset tag, so we apply it ourselves.
            dn = band_da.values.astype(np.float32)
            refl = dn * 0.0001                      # DN / 10 000
            if baseline_maj < 4:                   # pre-2022 tiles: still missing +0.1
                refl += 0.1
            logging.debug("   %s  baseline=%s  %+0.3f shift applied",
                        band_name, baseline_str, 0.1 if baseline_maj < 4 else 0.0)
            return refl

        cube = np.stack([toa_reflectance(ds[b][0], b) for b in bands])

        H4, W4 = (cube.shape[1]//4)*4, (cube.shape[2]//4)*4
        small  = F.avg_pool2d(torch.from_numpy(cube[None])[...,:H4,:W4], 4, 4).squeeze(0)
        s_np   = small.numpy(); _, h4, w4 = small.shape

        nodata = (s_np.sum(0) < 1e-6)
        land   = np.array(Image.open(LANDMASK_FILE).convert("L")
                        .resize((w4,h4),Image.NEAREST)) > 127

        # ----- masks on pooled grid -----
        nodata = (s_np.sum(0) < 1e-6)
        if not pathlib.Path(LANDMASK_FILE).exists():
            log.warning("Landmask %s not found — using all-false", LANDMASK_FILE)
            land = np.zeros((h4,w4), dtype=bool)
        else:
            land = np.array(Image.open(LANDMASK_FILE).convert("L").resize((w4,h4),Image.NEAREST)) > 127

        with autocast(device_type=device.type), torch.no_grad():
            prob = torch.softmax(model(pad32(small)[None].to(device)),1)[0,1].cpu().numpy()
        cloud = binary_closing(prob[:h4,:w4] > 0.5, structure=np.ones((3,3)))

        ndsi = (s_np[g_idx]-s_np[sw_idx])/(s_np[g_idx]+s_np[sw_idx]+1e-6)
        ndwi = (s_np[g_idx]-s_np[nir_idx])/(s_np[g_idx]+s_np[nir_idx]+1e-6)

        ice_solid = (ndsi > NDSI_SOLID_THR) & ~cloud & ~land & ~nodata
        ice_light = (ndsi > NDSI_LIGHT_THR) & (ndsi < NDSI_SOLID_THR) & ~cloud & ~land & ~nodata
        water     = (ndwi > NDWI_THR) & ~ice_light & ~ice_solid & ~cloud & ~land & ~nodata

        log.debug("   pooled counts solid=%d light=%d water=%d cloud=%d land=%d nodata=%d",
                  int(ice_solid.sum()), int(ice_light.sum()), int(water.sum()),
                  int(cloud.sum()), int(land.sum()), int(nodata.sum()))

        # ----- upsample masks to full-res for overlay/exports -----
        full_size = rgb_native.size  # (W,H)
        cloud_big     = upsample_bool(cloud,     full_size)
        land_big      = upsample_bool(land,      full_size)
        nodata_big    = upsample_bool(nodata,    full_size)
        ice_solid_big = upsample_bool(ice_solid, full_size)
        ice_light_big = upsample_bool(ice_light, full_size)
        water_big     = upsample_bool(water,     full_size)

        # ----- overlay (full-res) -----
        try:
            overlay = overlay_rgb(rgb_native, ice_solid_big, ice_light_big, water_big,
                                  cloud_big, land_big, nodata_big)
            p = IMG_DIR / f"{it.id}_{ts}_Overlay.png"
            overlay.save(p)
            log.info("   Saved overlay %s", p)
        except Exception:
            log.exception("   Failed to build/save overlay for %s", it.id)

        # ----- quick-look panel (unchanged preview) -----
        try:
            fig,ax = plt.subplots(2,3,figsize=(13,8))
            ax[0,0].imshow(rgb512);                   ax[0,0].set_title("RGB");        ax[0,0].axis("off")
            ax[0,1].imshow(preview(cloud),cmap="gray"); ax[0,1].set_title("Cloud");  ax[0,1].axis("off")
            ax[0,2].imshow(preview(land),cmap="gray");  ax[0,2].set_title("Land");   ax[0,2].axis("off")
            ax[1,0].imshow(preview(ice_solid),cmap="gray"); ax[1,0].set_title("Solid ice");ax[1,0].axis("off")
            ax[1,1].imshow(preview(ice_light),cmap="gray"); ax[1,1].set_title("Light ice");ax[1,1].axis("off")
            ax[1,2].imshow(overlay);                 ax[1,2].set_title("Overlay");  ax[1,2].axis("off")
            plt.suptitle(f"{it.id}  {ts}",fontsize=11); plt.tight_layout()
            outp = IMG_DIR/f"{it.id}_{ts}_panel.png"
            fig.savefig(outp,dpi=150)
            plt.close(fig)
            log.info("   Saved quicklook panel %s", outp)
        except Exception:
            log.exception("   quicklook panel save failed for %s", it.id)

        # ----- per-panel PNGs (FULL-RES, no titles/whitespace) -----
        def save_mask_png(mask_bool: np.ndarray, outpath: pathlib.Path):
            Image.fromarray((mask_bool.astype(np.uint8) * 255), "L").save(outpath)

        out_rgb = IMG_DIR / f"{it.id}_{ts}_RGB.png"
        rgb_native.save(out_rgb)

        save_mask_png(cloud_big,     IMG_DIR / f"{it.id}_{ts}_Cloud.png")
        save_mask_png(land_big,      IMG_DIR / f"{it.id}_{ts}_Land.png")
        save_mask_png(ice_solid_big, IMG_DIR / f"{it.id}_{ts}_Solid_ice.png")
        save_mask_png(ice_light_big, IMG_DIR / f"{it.id}_{ts}_Light_ice.png")

        # ----- CSV -----
        total=h4*w4
        cnt_water,cnt_cloud = int(water.sum()), int(cloud.sum())
        cnt_land,cnt_nodata = int(land.sum()),  int(nodata.sum())
        unknown = total-(ice_solid.sum()+ice_light.sum()+cnt_water+cnt_cloud+cnt_land+cnt_nodata)
        csv_wr.writerow([
            it.id, ts,
            int(ice_solid.sum()), int(ice_light.sum()), cnt_water, cnt_cloud,
            cnt_land, cnt_nodata, int(unknown),
            round(ice_solid.sum()/total,4), round(ice_light.sum()/total,4), round(cnt_water/total,4),
            round(cnt_cloud/total,4), round(cnt_land/total,4), round(cnt_nodata/total,4),
            round(np.nanmean(ndsi[ice_solid]),4) if ice_solid.any() else "",
            round(np.nanmean(ndsi[ice_light]),4) if ice_light.any() else "",
            round(np.nanmean(ndwi[water]),4)     if water.any()     else "",
            int((cnt_nodata/total)>=NODATA_THR)
        ])
        csv_fh.flush()

        # timing & cleanup
        dt = time.time() - t0
        proc_times.append(dt)
        mean_dt = sum(proc_times)/len(proc_times)
        eta_sec = mean_dt * (len(tiles) - idx)
        log.info("   elapsed %.1fs  |  Ø %.1fs  |  ETA %s",
                 dt, mean_dt, datetime.timedelta(seconds=int(eta_sec)))

        del ds,cube,small; gc.collect()
        if torch.backends.mps.is_available(): torch.mps.empty_cache()
        elif torch.cuda.is_available():       torch.cuda.empty_cache()

except KeyboardInterrupt:
    log.warning("Interrupted by user (KeyboardInterrupt)")
except Exception:
    log.exception("Fatal error in main loop")
finally:
    try:
        csv_fh.close()
        log.info("Finished – results appended to %s", CSV_FILE)
    except Exception:
        log.exception("Error closing CSV file")