import os
import sys
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

def force_rmtree(path):
    def remove_readonly(func, p, exc_info):
        try:
            import stat
            os.chmod(p, stat.S_IWRITE)
            func(p)
        except Exception:
            pass

    if os.path.exists(path):
        try:
            shutil.rmtree(path, onexc=remove_readonly)
        except TypeError:
            shutil.rmtree(path, onerror=remove_readonly)
        except Exception:
            pass

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
        is_holdout = scene in (args.ood_holdout or [])
        active_dataset_dir = os.path.abspath(args.ood_dataset_dir) if is_holdout else dataset_dir
        target_patches_dir = os.path.join(active_dataset_dir, scene)
        if is_holdout:
            logger.info(f"Scene {scene} is designated OOD holdout -> routing to {active_dataset_dir} instead of the training set.")

        # Check if already processed
        if os.path.exists(target_patches_dir) and len(os.listdir(target_patches_dir)) > 0 and not args.force:
            logger.info(f"Scene {scene} already processed into {target_patches_dir}. Skipping.")
            continue

        raw_tif_files = [f for f in os.listdir(scene_raw_path) if f.lower().endswith('.tif')]
        if len(raw_tif_files) == 0:
            logger.warning(f"No .tif files found in {scene_raw_path}. Skipping.")
            continue

        logger.info(f"--- Processing Scene: {scene} ---")

        # Step 1: Copy raw scene files from Google Drive to local SSD input/ folder
        local_scene_input = os.path.join(input_root, scene)
        force_rmtree(local_scene_input)
        os.makedirs(local_scene_input, exist_ok=True)

        logger.info(f"Step 1: Copying raw scene files to local SSD {local_scene_input}...")
        for f in raw_tif_files:
            src = os.path.join(scene_raw_path, f)
            dst = os.path.join(local_scene_input, f)
            shutil.copy2(src, dst)

        # Step 2: Execute local driver.py script
        logger.info("Step 2: Executing driver.py preprocessing pipeline...")
        driver_script = os.path.join(base_dir, 'driver.py')
        try:
            subprocess.run([sys.executable, driver_script], check=True, cwd=base_dir)
        except subprocess.CalledProcessError as e:
            logger.error(f"driver.py processing failed for {scene}: {e}")
            force_rmtree(local_scene_input)
            continue

        # Step 3: Transfer reference RGB TIFF back to Google Drive scene folder
        rgb_output_dir = os.path.join(output_dir, 'rgb_images')
        if os.path.exists(rgb_output_dir):
            rgb_candidates = [f for f in os.listdir(rgb_output_dir) if f.endswith('.tif')]
            for rgb_file in rgb_candidates:
                local_ref = os.path.join(rgb_output_dir, rgb_file)
                gdrive_rgb_dest = os.path.join(scene_raw_path, rgb_file)
                logger.info(f"Step 3: Copying reference RGB image back to Google Drive at {gdrive_rgb_dest}...")
                shutil.copy2(local_ref, gdrive_rgb_dest)

        # Step 4: Move generated patches to final dataset folder
        patches_output_dir = os.path.join(output_dir, 'patches')
        os.makedirs(target_patches_dir, exist_ok=True)
        if os.path.exists(patches_output_dir):
            items = os.listdir(patches_output_dir)
            logger.info(f"Step 4: Moving generated patches to final dataset directory {target_patches_dir}...")
            for item in items:
                src_item = os.path.join(patches_output_dir, item)
                dst_item = os.path.join(target_patches_dir, item)
                if os.path.exists(dst_item):
                    if os.path.isdir(dst_item):
                        force_rmtree(dst_item)
                    else:
                        try:
                            os.remove(dst_item)
                        except Exception:
                            pass
                shutil.move(src_item, dst_item)
            force_rmtree(patches_output_dir)

        # Step 5: Clean up local input/ and output/ folders
        logger.info(f"Step 5: Cleaning up local input/ and output/ folders for {scene}...")
        import gc
        gc.collect()

        force_rmtree(local_scene_input)
        force_rmtree(output_dir)

        logger.info(f"Local input/output cleanup finished for {scene}.")

    logger.info("Dataset Builder completed all scenes.")

if __name__ == "__main__":
    main()
