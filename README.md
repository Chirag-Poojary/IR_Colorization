# 🛰️ IR Colorization — BAH 2026

**Problem Statement:** Infrared Image Colorization and Enhancement for Improved Object Interpretation  
**Hackathon:** Bhartiya Antriksh Hackathon (BAH) 2026

---

## 📐 Architecture Overview

```
STAGE 1 — Download
  download.py -> USGS M2M API -> Google Drive: Raw_Landsat/<Scene>/

STAGE 2 — Dataset Builder
  dataset_builder.py (orchestrates per-scene loop):
    1. Copy .tif files:  Drive -> local  input/<Scene>/
    2. Run driver.py    (all preprocessing — see step-by-step below)
    3. Copy reference RGB TIFF back to Drive/<Scene>/
    4. Move final patches to  dataset/train/<Scene>/  (or ood_holdout/)
    5. Wipe local input/ and output/ to keep SSD footprint near zero
```

---

## 📦 Bands Downloaded per Scene

| Band | USGS name | What it is | Native res |
|------|-----------|-----------|------------|
| Blue | `SR_B2` | Surface Reflectance Band 2 | 30 m |
| Green | `SR_B3` | Surface Reflectance Band 3 | 30 m |
| Red | `SR_B4` | Surface Reflectance Band 4 | 30 m |
| NIR | `SR_B5` | Surface Reflectance Band 5 *(reserved for NDVI/emissivity)* | 30 m |
| TIR | `ST_B10` | Surface Temperature Band 10 | 30 m raster (TIRS native ~100 m) |
| QA | `QA_PIXEL` | Bit-packed cloud / fill mask | 30 m |

> All six bands are co-registered to the same grid by USGS, delivered as Cloud-Optimised GeoTIFFs.

---

## 🗺️ 20 Curated Locations (40 Seasonal Pairs)

| Scenic / Biome Type | Primary / India Scene | Secondary / Global Scene | Seasons & Date Windows |
|---------------------|-----------------------|--------------------------|------------------------|
| **Urban** | Mumbai | NewYorkCity | Mumbai: Summer (Mar–May) / Winter (Nov–Jan)<br>NYC: Winter (Dec–Feb) / Summer (Jun–Aug) |
| **Agriculture** | Punjab | Iowa | Punjab: Growing (Jul–Sep) / Rabi (Nov–Jan)<br>Iowa: Harvest (Sep–Nov) / Growing (Jun–Aug) |
| **Forest** | WesternGhats | BlackForest | Western Ghats: Summer (Mar–May) / PostMonsoon (Oct–Dec)<br>Black Forest: Autumn (Sep–Nov) / Summer (Jun–Aug) |
| **Arid / Desert** | Thar | Atacama | Thar: Summer (Mar–May) / Winter (Nov–Jan)<br>Atacama: Winter (Jun–Aug) / Summer (Dec–Feb) |
| **High Mountains** | Ladakh | SwissAlps | Ladakh: Summer (Jun–Aug) / Spring (Apr–May)<br>Swiss Alps: Winter (Dec–Feb) / Summer (Jul–Sep) |
| **Coastal Urban** | Chennai | Sydney | Chennai: Summer (Mar–May) / NEMonsoon (Oct–Dec)<br>Sydney: Winter (Jun–Aug) / Summer (Dec–Feb) |
| **Wetlands / Delta**| Sundarbans | Everglades | Sundarbans: Summer (Mar–May) / Winter (Nov–Jan)<br>Everglades: Winter (Dec–Feb) / Summer (Jun–Aug) |
| **Hyper-Arid Sand** | Sahara (Cairo) | — | Summer (Jun–Aug) / Winter (Dec–Feb) |
| **Dense Metropolis**| Tokyo | — | Summer (Jun–Aug) / Winter (Dec–Feb) |
| **Tropical Rainforest** | Amazon (Manaus) | — | DrySeason (Jul–Sep) / WetSeason (Jan–Mar) |
| **Savanna / Grassland** | Serengeti | — | DrySeason (Jun–Sep) / GreenSeason (Nov–Jan) |
| **Boreal Taiga** | Yakutsk (Siberia) | — | Summer (Jun–Aug) / Spring (Apr–May) |
| **Subpolar Steppe** | Patagonia | — | Summer (Dec–Feb) / Autumn (Mar–May) |

**OOD Holdout (default):** `Atacama_Winter` is routed to `dataset/ood_holdout/` instead of `dataset/train/`.  
Override with `--ood_holdout <Scene1> <Scene2> ...` when running `dataset_builder.py`.


---

## 🔄 Step-by-Step Data Flow

When you run `python dataset_builder.py`, for **each scene** the following runs in order:

### Step 1 — Copy raw scene from Google Drive to local SSD

```
Google Drive:  Raw_Landsat/<Scene>/*.TIF   (all 6 bands)
                    |  shutil.copy2
Local SSD:     input/<Scene>/*.TIF
```

### Step 2 — Merge RGB bands (30 m, reflectance-calibrated)

**Script:** `scripts/merge_rgb.py`  
**Input:** `input/<Scene>/..._SR_B4.TIF`, `..._SR_B3.TIF`, `..._SR_B2.TIF`  
**Process:** Converts raw uint16 DNs to float32 **surface reflectance** (scale = 0.0000275, offset = −0.2); stacks as (3, H, W).  
**Output — local:**

```
output/rgb_images/<Scene>_rgb_30m.tif          <- float32 reflectance (3, H, W)
output/rgb_images/png/<Scene>_rgb_30m.png      <- percentile-stretched preview
```

### Step 2b — Calibrate TIR raw DN to Kelvin

**Script:** `scripts/calibrate_tir.py`  
**Input:** `input/<Scene>/..._ST_B10.TIF` (raw uint16)  
**Process:** USGS C2 L2 scale/offset (0.00341802, +149.0). Fill pixels (DN=0) become 149.0 K sentinel.  
**Output — local:**

```
output/calibrated/<Scene>_tir_kelvin.tif       <- float32 Kelvin
output/calibrated/png/<Scene>_tir_kelvin.png   <- preview
```

### Step 2c — Build QA invalid-pixel fraction maps

**Script:** `scripts/downscale_qa.py`  
**Input:** `input/<Scene>/..._QA_PIXEL.TIF` + raw `..._ST_B10.TIF`  
**Process:** Decodes QA_PIXEL bits 0–4 (fill, dilated cloud, cirrus, cloud, cloud shadow) OR’d with ST DN fill check (DN < 293 or > 65535). Box-averages binary mask to fraction map in [0.0, 1.0].  
**Output — local:**

```
output/downscaled_data/<Scene>_qainvalid_100m.tif   <- float32 invalid fraction at 100 m grid
output/downscaled_data/<Scene>_qainvalid_200m.tif   <- float32 invalid fraction at 200 m grid
```

### Step 3 — Capture native georeferencing

**Direct call inside:** `driver.py` (no subprocess)  
**Input:** `input/<Scene>/..._ST_B10.TIF` (or any band — all share the same grid)  
**Process:** `rasterio.open` reads CRS string + 6-element affine transform + width/height.  
**Output — local:**

```
output/geo/<Scene>_native_geo.json
  {"crs": "EPSG:32643", "transform": [a,b,c,d,e,f], "width": N, "height": N}
```

### Step 4 — Downscale RGB 30 m to 100 m (box average)

**Script:** `scripts/downscale.py --mode box`  
**Input:** `output/rgb_images/<Scene>_rgb_30m.tif`  
**Factor:** x3.33  
**Output — local:**

```
output/downscaled_data/<Scene>_rgb_100m.tif    <- float32 reflectance (3, ~H/3.33, ~W/3.33)
```

### Step 5 — Downscale TIR (Kelvin) to 100 m (box average, ground-truth target)

**Script:** `scripts/downscale.py --mode box`  
**Input:** `output/calibrated/<Scene>_tir_kelvin.tif`  
**Factor:** x3.33  
**Why box-average:** The 100 m TIR is the **ground-truth target** for super-resolution — must not be blurred or noised.  
**Output — local:**

```
output/downscaled_data/<Scene>_tir_100m.tif    <- float32 Kelvin (~H/3.33, ~W/3.33)
```

### Step 6 — Downscale TIR (Kelvin) to 200 m (PSF + NEΔT noise, model input)

**Script:** `scripts/downscale.py --mode psf_thermal`  
**Input:** `output/calibrated/<Scene>_tir_kelvin.tif`  
**Factor:** x6.67  
**Process:** Gaussian blur (σ = factor/2.355) → INTER\_AREA resize → additive Gaussian noise (σ = 0.4 K, Landsat TIRS design-spec NEΔT). This is the **model’s coarser-sensor input**, simulating realistic degradation.  
**Output — local:**

```
output/downscaled_data/<Scene>_tir_200m.tif    <- float32 Kelvin + PSF blur + 0.4 K noise
```

### Step 7 — Extract co-registered patches with QA filtering and geo sidecars

**Script:** `scripts/create_patches.py`  
**Input:** `output/downscaled_data/` + `output/geo/`  
**Process:**
1. Groups files by scene (regex on `_rgb_` / `_tir_` / `_qainvalid_` suffix).
2. Loads all five arrays: `tir_200m`, `tir_100m`, `rgb_100m`, `qainvalid_200m`, `qainvalid_100m`.
3. Derives `transform_200m` and `transform_100m` from native geo JSON (once per scene).
4. Slides a **non-overlapping 256×256 window** over the 200 m grid.
5. **Rejects** patches where mean invalid fraction > 5% on either view.
6. Writes per-sample directory for accepted patches.

**Patch layout per sample — local:**

```
output/patches/<Scene>/
  sample_NNN/
    tir_200m.npy        <- (256, 256) float32 K    MODEL INPUT  (PSF-degraded 200 m)
    tir_200m.png
    tir_100m_512.npy    <- (512, 512) float32 K    GROUND TRUTH (box-avg 100 m)
    tir_100m_512.png
    rgb_100m_512.npy    <- (3,512,512) float32     RGB GUIDANCE (100 m reflectance)
    rgb_100m_512.png
    qa_meta.json        <- {"invalid_fraction_200m": 0.01, "invalid_fraction_100m": 0.008}
    geo_meta.json       <- {"crs":"EPSG:...", "patch_transform_200m":[...],
                            "bounds_wgs84":{"west":...,"south":...,"east":...,"north":...}}
```

> **Patch count estimates (stride=128, 50% overlap, 20 locations × 2 seasons = 40 pairs):**
>
> | Configuration | Tiles/scene | Total scenes | Est. patches |
> |---|---|---|---|
> | Baseline (stride=256, 1 scene/loc, 14 locs) | 16 | 14 | ~89 |
> | + 20 locations × 2 seasons (40 scenes) | 16 | 40 | ~256 |
> | + stride=128 overlap (50% stride) | 56 | 40 | ~1,456 |
> | **All combined (40 scenes × top-3 multi-scene = 120 scenes)** | **56** | **120** | **~4,368** |
>
> Tile calculation on a typical 200m footprint (~1144×1165 px):
> stride=128 yields 7×8 = 56 candidate tiles vs 4×4 = 16 at stride=256 (3.5× more).
> Assuming ~65% QA acceptance (varies by cloud cover), 40 seasonal scenes yield ~1,456 high-quality patches (up to ~4,368 with multi-scene).

### Step 8 — Copy reference RGB back to Google Drive

```
output/rgb_images/<Scene>_rgb_30m.tif  ->  Google Drive: Raw_Landsat/<Scene>/
```

### Step 9 — Move patches to final dataset directory

```
output/patches/<Scene>/  ->  dataset/train/<Scene>/       (all scenes except OOD holdout)
                         ->  dataset/ood_holdout/<Scene>/  (Atacama_Winter by default)
```

### Step 10 — Wipe local temp data

```
input/<Scene>/  and  output/   <- both deleted
```
Local SSD footprint returns to near zero. Next scene starts fresh.

---

## 📂 Final Dataset Layout on Local SSD

```
dataset/
  train/
    Mumbai_Summer/
      sample_000/
        tir_200m.npy        # (256,256)    float32 K    model input
        tir_100m_512.npy    # (512,512)    float32 K    ground truth
        rgb_100m_512.npy    # (3,512,512)  float32      reflectance
        qa_meta.json
        geo_meta.json
      sample_001/ ...
    NewYorkCity_Winter/
    Punjab_Growing/
    Iowa_Harvest/
    WesternGhats_Summer/
    BlackForest_Autumn/
    Thar_Summer/
    Ladakh_Summer/
    SwissAlps_Winter/
    Chennai_Summer/
    Sydney_Winter/
    Sundarbans_Summer/
    Everglades_Winter/
  ood_holdout/
    Atacama_Winter/           <- held-out OOD evaluation split
      sample_000/ ...
```

---

## 📂 Google Drive Layout (after download + pipeline)

```
Raw_Landsat/
  Mumbai_Summer/
    LC09_..._SR_B2.TIF
    LC09_..._SR_B3.TIF
    LC09_..._SR_B4.TIF
    LC09_..._SR_B5.TIF
    LC09_..._ST_B10.TIF
    LC09_..._QA_PIXEL.TIF
    Mumbai_Summer_rgb_30m.tif     <- 30 m reference RGB copied back by pipeline
  NewYorkCity_Winter/   ...  (one folder per scene, same structure)
```

---

## ⚡ Quick Start — Run the Full Pipeline

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure credentials

```bash
cp download_config.example.yaml download_config.yaml
```

Edit `download_config.yaml`:

```yaml
usgs_username: "YOUR_USGS_USERNAME"
usgs_password: "YOUR_USGS_PASSWORD"
raw_landsat_dir: "G:/My Drive/Raw_Landsat"
```

> You can also set `USGS_USERNAME` and `USGS_PASSWORD` as environment variables.

### 3. Stage 1 — Download all 14 scenes to Google Drive

```bash
python download.py
```

Searches USGS M2M API, downloads `.tar` archives, extracts 6 bands per scene, transfers `.TIF` files to Google Drive. Retries up to 3× for corrupt archives.

> ⏱️ Duration: several hours depending on USGS bandwidth and Drive write speed.

### 4. Stage 2 — Build the training dataset

```bash
python dataset_builder.py
```

Processes all 14 scenes from Google Drive one-by-one and populates `dataset/train/` and `dataset/ood_holdout/`.

**Optional flags:**

```bash
# Change OOD holdout scene(s) — list each season explicitly
python dataset_builder.py --ood_holdout Atacama_Winter SwissAlps_Winter

# Force re-processing even if patches exist
python dataset_builder.py --force

# Custom Google Drive path
python dataset_builder.py --raw_dir "D:/MyDrive/Landsat"
```

**Or use the shell wrapper (Linux / macOS / WSL):**

```bash
chmod +x scripts/download_data.sh
./scripts/download_data.sh
```

### Preprocessing only (raw .TIF already in input/)

```bash
python driver.py
```

### Advanced — tune individual steps

```bash
# Accept up to 10% invalid pixels per patch (default: 5%)
python scripts/create_patches.py \
    --input_dir output/downscaled_data \
    --output_dir output/patches \
    --max_invalid_fraction 0.10

# Use on-orbit measured TIRS noise (0.06 K) instead of spec NEdeltaT (0.4 K)
python scripts/downscale.py input.tif output_200m.tif 6.67 --mode psf_thermal --neqt_kelvin 0.06

# Reproducible noise (fixed seed)
python scripts/downscale.py input.tif output_200m.tif 6.67 --mode psf_thermal --seed 42
```

---

## 🔬 Physical Units in the Dataset

| Array file | dtype | Units | Typical range |
|------------|-------|-------|---------------|
| `tir_200m.npy` | float32 | Kelvin (PSF-blurred + 0.4 K noise) | 250–330 K |
| `tir_100m_512.npy` | float32 | Kelvin (box average) | 250–330 K |
| `rgb_100m_512.npy` | float32 | Surface reflectance | −0.2 to 1.3 |
| Fill sentinel | float32 | 149.0 K exactly (DN was 0) | — |

---

## 🛠️ Scripts & Utils Reference

| File | Role |
|------|------|
| `download.py` | USGS M2M API downloader |
| `dataset_builder.py` | Per-scene orchestrator with OOD routing |
| `driver.py` | Preprocessing pipeline runner |
| `scripts/merge_rgb.py` | B4+B3+B2 → float32 reflectance RGB TIFF |
| `scripts/calibrate_tir.py` | ST_B10 raw DN → float32 Kelvin |
| `scripts/downscale_qa.py` | QA_PIXEL + ST fill → invalid-fraction map |
| `scripts/downscale.py` | Box-average or PSF+NEΔT downscaling |
| `scripts/create_patches.py` | Patch extraction, QA filtering, geo sidecars |
| `utils/file_utils.py` | `find_file`, `extract_product_id`, `validate_extension` |
| `utils/radiometry.py` | USGS C2 L2 calibration constants and functions |
| `utils/qa_mask.py` | QA_PIXEL bit-mask decoder (bits 0–4) |
| `utils/geo.py` | rasterio geo capture, `scale_transform`, `patch_bounds_wgs84` |
| `utils/visualization.py` | `percentile_stretch` for PNG previews |
| `utils/logging_utils.py` | Shared logging setup |

---

## 🎯 Model Output Format (Evaluation)

```
output/model_outputs/
  tir_superresolved_100m/
    <product_id>.tif        <- 512x512 super-resolved TIR
  colorized_tir_100m/
    <product_id>.tif        <- colorized output (Layer 1: Blue, Layer 2: Green, Layer 3: Red)
```
