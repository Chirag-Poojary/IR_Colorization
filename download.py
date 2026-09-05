import os
import sys
import yaml
import tarfile
import shutil
import time
import argparse
import logging

try:
    from usgsxplore import API
except ImportError:
    API = None

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("Downloader")

def download_and_extract_scene(api, scene_id, target_gdrive_dir, temp_dir, target_bands, max_retries=3):
    os.makedirs(target_gdrive_dir, exist_ok=True)
    os.makedirs(temp_dir, exist_ok=True)

    for attempt in range(1, max_retries + 1):
        logger.info(f"Download attempt {attempt}/{max_retries} for scene: {scene_id}")
        tar_path = None
        try:
            # Download the tar file to temp_dir
            downloaded_files = api.download(scene_id, output_dir=temp_dir)
            if not downloaded_files:
                # If usgsxplore returns string/path directly
                tar_path = os.path.join(temp_dir, f"{scene_id}.tar")
            elif isinstance(downloaded_files, list) and len(downloaded_files) > 0:
                tar_path = downloaded_files[0]
            elif isinstance(downloaded_files, str):
                tar_path = downloaded_files

            if not tar_path or not os.path.exists(tar_path):
                # Search temp_dir for matching tar file
                candidates = [os.path.join(temp_dir, f) for f in os.listdir(temp_dir) if f.endswith('.tar') or f.endswith('.tar.gz')]
                if candidates:
                    tar_path = candidates[0]
                else:
                    raise FileNotFoundError(f"No downloaded tar archive found for {scene_id} in {temp_dir}")

            logger.info(f"Extracting requested bands {target_bands} from {tar_path}...")
            extracted_count = 0
            with tarfile.open(tar_path, 'r:*') as tar:
                members = tar.getmembers()
                for member in members:
                    # Match target bands (e.g. _SR_B2.TIF, _ST_B10.TIF, _QA_PIXEL.TIF)
                    for band in target_bands:
                        band_suffix = f"_{band}.TIF"
                        if member.name.upper().endswith(band_suffix.upper()):
                            tar.extract(member, path=temp_dir)
                            extracted_file = os.path.join(temp_dir, member.name)
                            dest_file = os.path.join(target_gdrive_dir, os.path.basename(member.name))
                            shutil.move(extracted_file, dest_file)
                            logger.info(f"Transferred band file to Google Drive: {dest_file}")
                            extracted_count += 1
                            break

            logger.info(f"Successfully extracted and transferred {extracted_count} band files for {scene_id}.")

            # Cleanup temp tar file
            if os.path.exists(tar_path):
                os.remove(tar_path)
            return True

        except (tarfile.TarError, EOFError, OSError, Exception) as e:
            logger.warning(f"Attempt {attempt} failed for scene {scene_id}: {e}")
            # Clean up temp files before retry
            if tar_path and os.path.exists(tar_path):
                try:
                    os.remove(tar_path)
                except Exception:
                    pass
            for f in os.listdir(temp_dir):
                fp = os.path.join(temp_dir, f)
                try:
                    if os.path.isfile(fp):
                        os.remove(fp)
                    elif os.path.isdir(fp):
                        shutil.rmtree(fp)
                except Exception:
                    pass
            time.sleep(3)

    logger.error(f"Failed to download/extract scene {scene_id} after {max_retries} attempts.")
    return False

def main():
    parser = argparse.ArgumentParser(description="Stage 1: Landsat Downloader from USGS to Google Drive")
    parser.add_argument("--config", default=None, help="Path to YAML config file")
    args = parser.parse_args()

    config_path = args.config or os.environ.get("DOWNLOAD_CONFIG_PATH")
    if not config_path:
        if os.path.exists("download_config.yaml"):
            config_path = "download_config.yaml"
        elif os.path.exists("download_config.example.yaml"):
            config_path = "download_config.example.yaml"
            logger.info("download_config.yaml not found, loading download_config.example.yaml structure.")
        else:
            config_path = "download_config.yaml"

    if not os.path.exists(config_path):
        logger.error(f"Config file {config_path} not found.")
        sys.exit(1)

    logger.info(f"Loading configuration from: {config_path}")
    with open(config_path, 'r') as f:
        config = yaml.safe_load(f) or {}

    # Environment variables override config file credentials
    usgs_user = os.environ.get('USGS_USERNAME') or config.get('usgs_username')
    usgs_pass = os.environ.get('USGS_PASSWORD') or config.get('usgs_password')

    placeholders = {'YOUR_USGS_USERNAME', 'YOUR_USGS_PASSWORD', 'YOUR_PASSWORD_HERE', ''}
    if not usgs_user or usgs_user in placeholders or not usgs_pass or usgs_pass in placeholders:
        logger.error("USGS credentials missing or set to placeholder values.")
        logger.error("Please update 'download_config.yaml' with real credentials or set USGS_USERNAME and USGS_PASSWORD environment variables.")
        sys.exit(1)

    dataset = config.get('dataset', 'landsat_ot_c2_l2')
    global_cloud_limit = config.get('cloud_cover', 10)
    raw_landsat_dir = config.get('raw_landsat_dir', 'G:/My Drive/Raw_Landsat')
    temp_dir = config.get('temp_download_dir', 'temp_download')
    bands = config.get('bands', ['SR_B2', 'SR_B3', 'SR_B4', 'SR_B5', 'ST_B10', 'QA_PIXEL'])
    locations = config.get('locations', [])

    if API is None:
        logger.error("usgsxplore package is not installed. Please run `pip install usgsxplore`.")
        sys.exit(1)

    logger.info(f"Connecting to USGS M2M API as user: {usgs_user}")
    api = API(usgs_user, usgs_pass)

    os.makedirs(raw_landsat_dir, exist_ok=True)
    os.makedirs(temp_dir, exist_ok=True)

    for loc in locations:
        loc_name = loc['name']
        lat = loc['latitude']
        lon = loc['longitude']
        cloud_limit = loc.get('cloud_cover', global_cloud_limit)
        seasons = loc.get('seasons', [])

        bbox = (lon - 0.05, lat - 0.05, lon + 0.05, lat + 0.05)

        for season in seasons:
            season_name = season['name']
            start_date = season['start_date']
            end_date = season['end_date']

            folder_name = f"{loc_name}_{season_name}"
            target_gdrive_dir = os.path.join(raw_landsat_dir, folder_name)

            # Check if scene is already downloaded
            if os.path.exists(target_gdrive_dir):
                tif_files = [f for f in os.listdir(target_gdrive_dir) if f.endswith('.tif') or f.endswith('.TIF')]
                if len(tif_files) >= 5:
                    logger.info(f"Scene for {folder_name} already exists in {target_gdrive_dir} ({len(tif_files)} band files). Skipping.")
                    continue

            logger.info(f"Searching USGS for {folder_name} (BBOX: {bbox}, Dates: {start_date} to {end_date}, Max Cloud Cover: {cloud_limit}%)...")
            try:
                results = api.search(
                    dataset=dataset,
                    bbox=bbox,
                    start_date=start_date,
                    end_date=end_date,
                    max_cloud_cover=cloud_limit
                )
            except Exception as e:
                logger.error(f"USGS API search error for {folder_name}: {e}")
                continue

            if not results or len(results) == 0:
                logger.warning(f"No scenes found for {folder_name} matching search criteria.")
                continue

            # Pick the clearest scene (lowest cloud cover)
            best_scene = min(results, key=lambda x: x.get('cloud_cover', 100))
            scene_id = best_scene.get('entity_id') or best_scene.get('display_id')
            cloud_val = best_scene.get('cloud_cover', 'N/A')

            logger.info(f"Selected best scene for {folder_name}: {scene_id} (Cloud Cover: {cloud_val}%)")

            download_and_extract_scene(api, scene_id, target_gdrive_dir, temp_dir, bands)

            # Cleanup temp directory completely after each location
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)
                os.makedirs(temp_dir, exist_ok=True)

    try:
        api.logout()
    except Exception:
        pass

    logger.info("Stage 1 Landsat Downloader completed.")

if __name__ == "__main__":
    main()
