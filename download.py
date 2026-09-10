"""
Stage 1: Landsat Downloader from USGS M2M API to Google Drive / Local Storage.

Reads download_config.yaml, searches Landsat Collection 2 Level-2 products for
each location and season pair, filters by cloud cover, sorts by clearest scenes,
downloads the product bundle via USGS M2M API (usgsxplore), selectively extracts
only the required bands (B2, B3, B4, B5, B10, QA_PIXEL), and saves them to the
raw Landsat storage directory.
"""

import os
import sys
import yaml
import tarfile
import shutil
import time
import argparse
import logging
from pathlib import Path

try:
    from usgsxplore import API, SceneDownloader
    from usgsxplore.scene_downloader import ProductSelector
    import usgsxplore.errors as usgs_errors
except ImportError:
    API = None
    SceneDownloader = None
    ProductSelector = object
    usgs_errors = None

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("USGSDownloader")


class BundleProductSelector(ProductSelector if ProductSelector is not object else object):
    """
    Custom ProductSelector that automatically selects the Landsat Level-2 product
    bundle archive without requiring interactive prompts or raising DownloadOptionsError.
    """
    def select(self, options, product_number=None):
        if product_number is not None:
            return super().select(options, product_number)

        available = [o for o in options if o.get("available")]
        if not available:
            if usgs_errors and hasattr(usgs_errors, "DownloadOptionsError"):
                raise usgs_errors.DownloadOptionsError("No product available for download")
            raise RuntimeError("No product available for download")

        ref_entity = available[0]["entityId"]
        product_variants = [o for o in available if o["entityId"] == ref_entity]

        if len(product_variants) > 1:
            # Look for bundle in product name
            bundle_indices = [
                i for i, p in enumerate(product_variants)
                if "bundle" in p.get("productName", "").lower()
            ]
            if bundle_indices:
                return super().select(options, bundle_indices[0])

            # Fall back to largest file size (the full scene bundle)
            max_idx = max(range(len(product_variants)), key=lambda i: product_variants[i].get("filesize", 0))
            return super().select(options, max_idx)

        return super().select(options, None)


def extract_target_bands_from_tar(tar_path, target_dir, temp_dir, target_bands):
    """
    Selectively extracts only requested bands from a downloaded tar archive,
    moving them into target_dir and ignoring unneeded bands.
    """
    os.makedirs(target_dir, exist_ok=True)
    extracted_count = 0

    with tarfile.open(tar_path, 'r:*') as tar:
        for member in tar.getmembers():
            for band in target_bands:
                band_suffix = f"_{band}.TIF"
                if member.name.upper().endswith(band_suffix.upper()):
                    tar.extract(member, path=temp_dir)
                    extracted_file = os.path.join(temp_dir, member.name)
                    dest_file = os.path.join(target_dir, os.path.basename(member.name))
                    shutil.move(extracted_file, dest_file)
                    logger.info(f"  Extracted band: {os.path.basename(member.name)}")
                    extracted_count += 1
                    break

    return extracted_count


def extract_target_bands_from_dir(search_dir, target_dir, target_bands):
    """
    Moves any target band TIFF files found loose in search_dir into target_dir.
    """
    os.makedirs(target_dir, exist_ok=True)
    extracted_count = 0
    for root, _, files in os.walk(search_dir):
        for f in files:
            for band in target_bands:
                band_suffix = f"_{band}.TIF"
                if f.upper().endswith(band_suffix.upper()):
                    src = os.path.join(root, f)
                    dst = os.path.join(target_dir, f)
                    if os.path.abspath(src) != os.path.abspath(dst):
                        shutil.move(src, dst)
                        logger.info(f"  Saved band: {f}")
                        extracted_count += 1
                    break
    return extracted_count


def download_and_extract_scene(api, dataset, entity_id, target_dir, temp_dir, target_bands, max_retries=3):
    """
    Downloads a Landsat scene by entity ID and extracts only the target bands.
    Cleans up all intermediate archives and temp files.
    """
    os.makedirs(target_dir, exist_ok=True)
    os.makedirs(temp_dir, exist_ok=True)

    selector = BundleProductSelector() if ProductSelector is not object else None
    downloader = SceneDownloader(api, selector=selector)

    for attempt in range(1, max_retries + 1):
        logger.info(f"Download attempt {attempt}/{max_retries} for scene: {entity_id}")
        try:
            # Download the bundle archive without auto-extracting all bands
            downloader.download(
                dataset=dataset,
                entity_ids=[entity_id],
                output_dir=temp_dir,
                overwrite=True,
                show_progress=True,
                extract=False
            )

            # Check for downloaded tar / archive in temp_dir
            candidates = [
                os.path.join(temp_dir, f) for f in os.listdir(temp_dir)
                if f.lower().endswith(('.tar', '.tar.gz', '.tgz', '.zip'))
            ]

            extracted = 0
            if candidates:
                tar_path = candidates[0]
                logger.info(f"Extracting target bands {target_bands} from {os.path.basename(tar_path)}...")
                extracted = extract_target_bands_from_tar(tar_path, target_dir, temp_dir, target_bands)
                try:
                    os.remove(tar_path)
                except Exception:
                    pass
            else:
                # In case files were downloaded directly or uncompressed
                extracted = extract_target_bands_from_dir(temp_dir, target_dir, target_bands)

            logger.info(f"Successfully extracted {extracted} target band files for {entity_id}.")
            return True

        except Exception as e:
            logger.warning(f"Attempt {attempt} failed for scene {entity_id}: {e}")
            # Clean up temp_dir on failure
            for item in os.listdir(temp_dir):
                p = os.path.join(temp_dir, item)
                try:
                    if os.path.isdir(p):
                        shutil.rmtree(p)
                    else:
                        os.remove(p)
                except Exception:
                    pass
            time.sleep(3)

    logger.error(f"Failed to download/extract scene {entity_id} after {max_retries} attempts.")
    return False


def is_scene_already_downloaded(target_dir, target_bands):
    """
    Checks whether all required target bands already exist in target_dir.
    """
    if not os.path.exists(target_dir):
        return False

    existing_files = os.listdir(target_dir)
    found_bands = set()
    for f in existing_files:
        if not f.lower().endswith(('.tif', '.tiff')):
            continue
        for band in target_bands:
            if f.upper().endswith(f"_{band}.TIF".upper()) or f.upper().endswith(f"_{band}.TIFF".upper()):
                found_bands.add(band)

    # Need at least the primary 5 bands (B2, B3, B4, B10, QA_PIXEL)
    essential = {'SR_B2', 'SR_B3', 'SR_B4', 'ST_B10', 'QA_PIXEL'}
    return essential.issubset(found_bands) or len(found_bands) >= len(target_bands)


def run_downloader(config_path="download_config.yaml", n_scenes_per_season=1,
                   filter_location=None, filter_season=None, dry_run=False, overwrite=False):
    """
    Main execution routine for downloading Landsat data from USGS M2M.
    """
    if not os.path.exists(config_path):
        if os.path.exists("download_config.example.yaml"):
            config_path = "download_config.example.yaml"
            logger.info("download_config.yaml not found, loading download_config.example.yaml structure.")
        else:
            logger.error(f"Configuration file {config_path} not found.")
            sys.exit(1)

    logger.info(f"Loading configuration from: {config_path}")
    with open(config_path, 'r') as f:
        config = yaml.safe_load(f) or {}

    usgs_user = os.environ.get('USGS_USERNAME') or config.get('usgs_username')
    usgs_token = os.environ.get('USGS_TOKEN') or os.environ.get('USGS_PASSWORD') or config.get('usgs_token') or config.get('usgs_password')

    placeholders = {'YOUR_USGS_USERNAME', 'YOUR_USGS_PASSWORD', 'YOUR_PASSWORD_HERE', 'YOUR_TOKEN_HERE', ''}
    if not usgs_user or usgs_user in placeholders or not usgs_token or usgs_token in placeholders:
        logger.error("USGS credentials missing or set to default placeholder values.")
        logger.error("Please update 'download_config.yaml' with valid USGS credentials or set USGS_USERNAME and USGS_TOKEN environment variables.")
        sys.exit(1)

    if API is None:
        logger.error("usgsxplore package is not installed. Please run `pip install usgsxplore`.")
        sys.exit(1)

    dataset = config.get('dataset', 'landsat_ot_c2_l2')
    global_cloud_limit = config.get('cloud_cover', 10)
    raw_landsat_dir = config.get('raw_landsat_dir', 'G:/My Drive/Raw_Landsat')
    temp_dir = config.get('temp_download_dir', 'temp_download')
    bands = config.get('bands', ['SR_B2', 'SR_B3', 'SR_B4', 'SR_B5', 'ST_B10', 'QA_PIXEL'])
    locations = config.get('locations', [])

    scenes_cfg = config.get('scenes_per_season', 1)
    n_scenes = n_scenes_per_season or scenes_cfg

    logger.info(f"Connecting to USGS M2M API as user: {usgs_user}")
    try:
        api = API(usgs_user, usgs_token)
    except usgs_errors.USGSAuthenticationError as e:
        logger.error(f"USGS Authentication failed: {e}")
        logger.error("Note: USGS M2M API v1.5 requires an Application Token rather than your web password.")
        logger.error("To generate a token:")
        logger.error("  1. Log in to https://ers.cr.usgs.gov/")
        logger.error("  2. Go to 'Authorized Applications' -> 'Generate Token'.")
        logger.error("  3. Paste the generated token into usgs_password / usgs_token in download_config.yaml or set USGS_TOKEN.")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Failed to connect to USGS M2M API: {e}")
        sys.exit(1)

    os.makedirs(raw_landsat_dir, exist_ok=True)
    os.makedirs(temp_dir, exist_ok=True)

    total_downloaded = 0
    total_skipped = 0

    try:
        for loc in locations:
            loc_name = loc['name']
            if filter_location and loc_name.lower() != filter_location.lower():
                continue

            lat = float(loc['latitude'])
            lon = float(loc['longitude'])
            cloud_limit = int(loc.get('cloud_cover', global_cloud_limit))
            seasons = loc.get('seasons', [])

            bbox = (round(lon - 0.05, 4), round(lat - 0.05, 4), round(lon + 0.05, 4), round(lat + 0.05, 4))

            for season in seasons:
                season_name = season['name']
                if filter_season and season_name.lower() != filter_season.lower():
                    continue

                start_date = str(season['start_date'])
                end_date = str(season['end_date'])

                logger.info(f"\n=======================================================")
                logger.info(f"Location: {loc_name} | Season: {season_name} ({start_date} to {end_date})")
                logger.info(f"Coordinates: ({lat}, {lon}) | Max Cloud Cover: {cloud_limit}%")
                logger.info(f"=======================================================")

                logger.info(f"Searching USGS for matching scenes...")
                try:
                    results = api.search(
                        dataset=dataset,
                        bbox=bbox,
                        date_interval=(start_date, end_date),
                        max_cloud_cover=cloud_limit
                    )
                except Exception as e:
                    logger.error(f"Search error for {loc_name}_{season_name}: {e}")
                    continue

                if not results:
                    logger.warning(f"No scenes found for {loc_name}_{season_name} with <= {cloud_limit}% cloud cover.")
                    # Try relaxing cloud cover slightly if none found
                    if cloud_limit < 30:
                        relaxed = min(30, cloud_limit + 15)
                        logger.info(f"Retrying search with relaxed cloud cover <= {relaxed}%...")
                        try:
                            results = api.search(
                                dataset=dataset,
                                bbox=bbox,
                                date_interval=(start_date, end_date),
                                max_cloud_cover=relaxed
                            )
                        except Exception:
                            results = []

                if not results:
                    logger.warning(f"No scenes available for {loc_name}_{season_name} in date range.")
                    continue

                # Sort scenes by lowest cloud cover
                def get_cloud(scene):
                    val = scene.get('cloudCover')
                    if val is None:
                        val = scene.get('cloud_cover', 100)
                    try:
                        return float(val)
                    except (ValueError, TypeError):
                        return 100.0

                results.sort(key=get_cloud)
                selected = results[:n_scenes]
                logger.info(f"Found {len(results)} scenes. Selected top {len(selected)} clearest:")
                for i, s in enumerate(selected):
                    s_id = s.get('displayId') or s.get('entityId')
                    logger.info(f"  [{i+1}] {s_id} (Cloud Cover: {get_cloud(s):.1f}%)")

                if dry_run:
                    logger.info("[DRY RUN] Skipping download phase.")
                    continue

                for idx, scene_info in enumerate(selected):
                    entity_id = scene_info.get('entityId') or scene_info.get('displayId')
                    display_id = scene_info.get('displayId') or entity_id

                    # Assign folder name: if n_scenes == 1, use Loc_Season; if multi-scene, append index
                    if n_scenes == 1:
                        folder_name = f"{loc_name}_{season_name}"
                    else:
                        folder_name = f"{loc_name}_{season_name}_{idx+1:02d}"

                    target_scene_dir = os.path.join(raw_landsat_dir, folder_name)

                    if not overwrite and is_scene_already_downloaded(target_scene_dir, bands):
                        logger.info(f"Scene {folder_name} already exists in {target_scene_dir} with required bands. Skipping.")
                        total_skipped += 1
                        continue

                    logger.info(f"Downloading scene {display_id} into {target_scene_dir}...")
                    success = download_and_extract_scene(
                        api=api,
                        dataset=dataset,
                        entity_id=entity_id,
                        target_dir=target_scene_dir,
                        temp_dir=temp_dir,
                        target_bands=bands
                    )

                    if success:
                        total_downloaded += 1
                    else:
                        logger.error(f"Failed to extract bands for {folder_name}.")

                    # Clean temp download directory
                    if os.path.exists(temp_dir):
                        try:
                            shutil.rmtree(temp_dir)
                            os.makedirs(temp_dir, exist_ok=True)
                        except Exception:
                            pass

    finally:
        try:
            api.logout()
            logger.info("USGS API session logged out successfully.")
        except Exception:
            pass

    logger.info(f"\nDownloader complete. Newly downloaded: {total_downloaded}, Already cached/skipped: {total_skipped}")


def main():
    parser = argparse.ArgumentParser(
        description="Stage 1: USGS M2M Landsat Downloader (Extracts 20 locations x 2 seasons)"
    )
    parser.add_argument("--config", default=None, help="Path to YAML config file (default: download_config.yaml)")
    parser.add_argument("--n_scenes", type=int, default=1, help="Number of lowest-cloud scenes to download per season (default: 1)")
    parser.add_argument("--location", default=None, help="Download only a specific location name (e.g. Mumbai)")
    parser.add_argument("--season", default=None, help="Download only a specific season name (e.g. Summer)")
    parser.add_argument("--dry_run", action="store_true", help="Search USGS and display matching scenes without downloading")
    parser.add_argument("--overwrite", action="store_true", help="Force redownload even if files exist")
    args = parser.parse_args()

    config_path = args.config or os.environ.get("DOWNLOAD_CONFIG_PATH") or "download_config.yaml"
    run_downloader(
        config_path=config_path,
        n_scenes_per_season=args.n_scenes,
        filter_location=args.location,
        filter_season=args.season,
        dry_run=args.dry_run,
        overwrite=args.overwrite
    )


if __name__ == "__main__":
    main()
