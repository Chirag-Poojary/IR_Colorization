import os
import sys
import time
import yaml
import shutil
import argparse
import subprocess
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("DatasetBuilder")

def load_config_raw_dir(config_path="download_config.yaml"):
    if os.path.exists(config_path):
        try:
            with open(config_path, 'r') as f:
                config = yaml.safe_load(f)
                return config.get('raw_landsat_dir', 'G:/My Drive/Raw_Landsat')
        except Exception:
            pass
    return "G:/My Drive/Raw_Landsat"

def force_rmtree(path, retries=3, delay=0.5):
    """Robust directory removal for Windows with readonly override and retries."""
    def remove_readonly(func, p, exc_info):
        try:
            import stat
            os.chmod(p, stat.S_IWRITE)
            func(p)
        except Exception:
            pass

    for attempt in range(retries):
        if not os.path.exists(path):
            return
        try:
            try:
                shutil.rmtree(path, onexc=remove_readonly)
            except TypeError:
                shutil.rmtree(path, onerror=remove_readonly)
            return
        except Exception:
            if attempt < retries - 1:
                time.sleep(delay)

def safe_copy(src, dst, chunk_size=1024*1024, max_retries=5, retry_delay=2.0):
    """
    Safely copy a file across filesystems (especially Google Drive virtual drives).
    Uses standard chunked read/write stream copying with automatic retries for transient
    cloud stream stalls ([Errno 22] Invalid argument / network drops on Google Drive).
    """
    os.makedirs(os.path.dirname(dst), exist_ok=True)

    # Check if dst already exists and is fully intact
    try:
        if os.path.exists(dst) and os.path.exists(src):
            src_size = os.path.getsize(src)
            dst_size = os.path.getsize(dst)
            if src_size > 0 and src_size == dst_size:
                logger.info(f"File {os.path.basename(dst)} already fully copied ({dst_size} bytes). Skipping.")
                return
    except Exception:
        pass

    last_err = None
    cur_delay = retry_delay
    for attempt in range(1, max_retries + 1):
        try:
            if os.path.exists(dst):
                try:
                    os.remove(dst)
                except Exception:
                    pass
            with open(src, 'rb') as fsrc, open(dst, 'wb') as fdst:
                while True:
                    chunk = fsrc.read(chunk_size)
                    if not chunk:
                        break
                    fdst.write(chunk)
            try:
                shutil.copystat(src, dst)
            except OSError:
                pass
            return
        except OSError as e:
            last_err = e
            logger.warning(
                f"Transient error copying {os.path.basename(src)} (attempt {attempt}/{max_retries}): {e}. "
                f"Retrying in {cur_delay:.1f}s..."
            )
            time.sleep(cur_delay)
            cur_delay *= 1.5

    raise last_err

def select_scene_band_files(scene_raw_path):
    """
    Selects only the required input band files (_B2, _B3, _B4, _B5, _B10, QA_PIXEL)
    from a scene folder, skipping any reference RGB TIFFs or duplicate files.
    """
    all_files = [f for f in os.listdir(scene_raw_path) if f.lower().endswith(('.tif', '.tiff'))]
    # Filter out reference RGB images
    candidates = [f for f in all_files if '_rgb_' not in f.lower()]
    
    target_keys = ['_B2', '_B3', '_B4', '_B5', '_B10', 'QA_PIXEL']
    selected = {}
    for key in target_keys:
        for f in candidates:
            if key.upper() in f.upper():
                if key not in selected:
                    selected[key] = f
                elif len(f) < len(selected[key]):
                    # Prefer shorter clean name if available
                    selected[key] = f
    return list(selected.values())

def main():
    default_raw_dir = load_config_raw_dir()

    parser = argparse.ArgumentParser(description="Stage 2: Dataset Builder Orchestrator")
    parser.add_argument("--raw_dir", default=default_raw_dir, help="Google Drive raw Landsat directory path")
    parser.add_argument("--dataset_dir", default="dataset/train", help="Target dataset output directory")
    parser.add_argument("--force", action="store_true", help="Force re-processing of existing datasets")
    parser.add_argument("--ood_holdout", nargs='*', default=['Atacama_Winter'],
                        help="Full scene folder names (e.g. 'Atacama_Winter') to route to a held-out OOD split "
                             "instead of the training set. Pass each season explicitly if you want multiple.")
    parser.add_argument("--ood_dataset_dir", default="dataset/ood_holdout",
                        help="Target directory for OOD-holdout scenes.")
    args = parser.parse_args()

    raw_dir = os.path.abspath(args.raw_dir)
    dataset_dir = os.path.abspath(args.dataset_dir)
    base_dir = os.path.dirname(os.path.abspath(__file__))
    input_root = os.path.join(base_dir, 'input')
    output_dir = os.path.join(base_dir, 'output')

    logger.info("Starting Dataset Builder Preprocessing Pipeline")
    logger.info(f"Raw Landsat Google Drive Path: {raw_dir}")
    logger.info(f"Dataset Output Path: {dataset_dir}")

    if not os.path.exists(raw_dir):
        logger.error(f"Raw directory {raw_dir} does not exist. Run download.py first.")
        sys.exit(1)

    scene_folders = [e for e in os.listdir(raw_dir) if os.path.isdir(os.path.join(raw_dir, e))]
    logger.info(f"Found {len(scene_folders)} scenes to process: {scene_folders}")

    for scene in scene_folders:
        scene_raw_path = os.path.join(raw_dir, scene)
        is_holdout = any(scene.startswith(h) for h in (args.ood_holdout or []))
        active_dataset_dir = os.path.abspath(args.ood_dataset_dir) if is_holdout else dataset_dir
        target_patches_dir = os.path.join(active_dataset_dir, scene)
        if is_holdout:
            logger.info(f"Scene {scene} is designated OOD holdout -> routing to {active_dataset_dir} instead of the training set.")

        # Check if already processed (must have sample_* directories directly inside)
        if os.path.exists(target_patches_dir) and not args.force:
            existing_samples = [s for s in os.listdir(target_patches_dir) if s.startswith('sample_')]
            if len(existing_samples) > 0:
                logger.info(f"Scene {scene} already processed ({len(existing_samples)} samples in {target_patches_dir}). Skipping.")
                continue

        raw_tif_files = select_scene_band_files(scene_raw_path)
        if len(raw_tif_files) == 0:
            logger.warning(f"No valid raw band .tif files found in {scene_raw_path}. Skipping.")
            continue

        logger.info(f"--- Processing Scene: {scene} ---")

        # Step 1: Copy raw scene files from Google Drive to local SSD input/ folder
        # Wipe input_root first so no previous scenes remain
        force_rmtree(input_root)
        local_scene_input = os.path.join(input_root, scene)
        os.makedirs(local_scene_input, exist_ok=True)

        logger.info(f"Step 1: Copying {len(raw_tif_files)} raw band files to local SSD {local_scene_input}...")
        for f in raw_tif_files:
            src = os.path.join(scene_raw_path, f)
            dst = os.path.join(local_scene_input, f)
            safe_copy(src, dst)

        # Step 2: Execute local driver.py script for this specific scene
        force_rmtree(output_dir)
        logger.info(f"Step 2: Executing driver.py preprocessing pipeline for {scene}...")
        driver_script = os.path.join(base_dir, 'driver.py')
        try:
            subprocess.run([sys.executable, driver_script, '--scene', scene], check=True, cwd=base_dir)
        except subprocess.CalledProcessError as e:
            logger.error(f"driver.py processing failed for {scene}: {e}")
            force_rmtree(input_root)
            force_rmtree(output_dir)
            continue

        # Step 3: Move generated patches directly to final dataset folder (flat: dataset/train/<scene>/sample_xxx)
        patches_output_dir = os.path.join(output_dir, 'patches')
        scene_patch_dir = os.path.join(patches_output_dir, scene)
        os.makedirs(target_patches_dir, exist_ok=True)

        if os.path.exists(scene_patch_dir):
            sample_dirs = [s for s in os.listdir(scene_patch_dir) if s.startswith('sample_')]
            logger.info(f"Step 3: Moving {len(sample_dirs)} generated samples to final dataset directory {target_patches_dir}...")
            for sample in sample_dirs:
                src_sample = os.path.join(scene_patch_dir, sample)
                dst_sample = os.path.join(target_patches_dir, sample)
                if os.path.exists(dst_sample):
                    force_rmtree(dst_sample)
                shutil.move(src_sample, dst_sample)
        else:
            logger.warning(f"No patch output directory found at {scene_patch_dir} for {scene}.")

        # Step 4: Transfer reference RGB TIFF back to Google Drive scene folder (if not already present)
        rgb_output_dir = os.path.join(output_dir, 'rgb_images')
        target_rgb_file = f'{scene}_rgb_30m.tif'
        local_ref = os.path.join(rgb_output_dir, target_rgb_file)
        if os.path.exists(local_ref):
            gdrive_rgb_dest = os.path.join(scene_raw_path, target_rgb_file)
            if os.path.exists(gdrive_rgb_dest) and os.path.getsize(gdrive_rgb_dest) > 0:
                logger.info(f"Step 4: Reference RGB image already exists on Google Drive at {gdrive_rgb_dest}. Skipping copy.")
            else:
                try:
                    logger.info(f"Step 4: Copying reference RGB image back to Google Drive at {gdrive_rgb_dest}...")
                    safe_copy(local_ref, gdrive_rgb_dest)
                except Exception as e:
                    logger.warning(f"Step 4: Could not copy reference RGB back to Google Drive: {e}. Dataset samples are safely saved.")

        # Step 5: Clean up local input/ and output/ folders
        logger.info(f"Step 5: Cleaning up local input/ and output/ folders for {scene}...")
        import gc
        gc.collect()

        force_rmtree(input_root)
        force_rmtree(output_dir)

        logger.info(f"Local input/output cleanup finished for {scene}.")

    logger.info("Dataset Builder completed all scenes.")

if __name__ == "__main__":
    main()
