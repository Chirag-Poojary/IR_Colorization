import os
import argparse
import subprocess
import logging
from utils.logging_utils import setup_logging
from utils.file_utils import find_file
from utils.geo import read_scene_geo, save_scene_geo

def run_script(script_name, logger, *args):
    base_dir = os.path.dirname(os.path.abspath(__file__))
    scripts_dir = os.path.join(base_dir, 'scripts')
    script_path = os.path.join(scripts_dir, script_name)
    command = ['python', script_path] + list(args)
    logger.info(f"Running: {' '.join(command)}")
    try:
        # Add the project root to PYTHONPATH so scripts can import from utils
        env = os.environ.copy()
        env['PYTHONPATH'] = base_dir + os.pathsep + env.get('PYTHONPATH', '')
        result = subprocess.run(command, capture_output=True, text=True, check=True, env=env)
        if result.stdout:
            logger.info(f"STDOUT from {script_name}:\n{result.stdout}")
        if result.stderr:
            logger.warning(f"STDERR from {script_name}:\n{result.stderr}")
    except subprocess.CalledProcessError as e:
        logger.error(f"Error running {script_name}: {e}")
        logger.error(f"STDOUT: {e.stdout}")
        logger.error(f"STDERR: {e.stderr}")
        raise e

def main():
    parser = argparse.ArgumentParser(description='IR-Colorization Dataset Generation Baseline')
    parser.add_argument('--scene', default=None, help='Specific scene / product ID to process')
    args = parser.parse_args()

    base_dir = os.path.dirname(os.path.abspath(__file__))
    input_root = os.path.join(base_dir, 'input')
    output_dir = os.path.join(base_dir, 'output')
    
    output_downscale_dir = os.path.join(output_dir, 'downscaled_data')
    output_rgb_dir = os.path.join(output_dir, 'rgb_images')
    output_patches_dir = os.path.join(output_dir, 'patches')
    output_calibrated_dir = os.path.join(output_dir, 'calibrated')   # raw DN -> physical units
    output_geo_dir = os.path.join(output_dir, 'geo')                 # native geo JSON sidecars

    for d in [output_downscale_dir, output_rgb_dir, output_patches_dir, output_calibrated_dir, output_geo_dir]:
        os.makedirs(d, exist_ok=True)

    logger = setup_logging(output_dir)

    if not os.path.isdir(input_root):
        logger.error(f"Input root directory {input_root} not found.")
        exit(1)

    if args.scene:
        if not os.path.isdir(os.path.join(input_root, args.scene)):
            logger.error(f"Scene directory {args.scene} not found in {input_root}.")
            exit(1)
        product_folders = [args.scene]
    else:
        product_folders = [e for e in os.listdir(input_root) if os.path.isdir(os.path.join(input_root, e))]

    for product_id in product_folders:
        input_dir = os.path.join(input_root, product_id)
        logger.info(f"Processing product: {product_id}")

        band2_path = find_file(input_dir, '_B2')
        band3_path = find_file(input_dir, '_B3')
        band4_path = find_file(input_dir, '_B4')
        band10_path = find_file(input_dir, '_B10')
        qa_pixel_path = find_file(input_dir, 'QA_PIXEL')

        if not all([band2_path, band3_path, band4_path, band10_path, qa_pixel_path]):
            logger.warning(f"Skipping {product_id}: Missing required bands.")
            continue

        file_prefix = product_id

        # Capture native (30m) georeferencing once per scene, from any raw
        # band - all bands of one Landsat scene share the same grid.
        native_geo = read_scene_geo(band10_path)
        geo_output_path = os.path.join(output_geo_dir, f'{file_prefix}_native_geo.json')
        save_scene_geo(native_geo, geo_output_path)
        logger.info(f"Saved native geo metadata for {product_id} to {geo_output_path}")

        try:
            # 1. Merge RGB (30m) -- merge_rgb.py now converts DN -> reflectance internally
            rgb_output_path = os.path.join(output_rgb_dir, f'{file_prefix}_rgb_30m.tif')
            run_script('merge_rgb.py', logger, band4_path, band3_path, band2_path, rgb_output_path)

            # 1b. Calibrate raw TIR DN -> Kelvin, before any downscaling touches it
            calibrated_tir_path = os.path.join(output_calibrated_dir, f'{file_prefix}_tir_kelvin.tif')
            run_script('calibrate_tir.py', logger, band10_path, calibrated_tir_path)

            # 1c. Build downscaled invalid-pixel-fraction maps (cloud/shadow/fill)
            qainvalid_100m_path = os.path.join(output_downscale_dir, f'{file_prefix}_qainvalid_100m.tif')
            run_script('downscale_qa.py', logger, qa_pixel_path, band10_path, qainvalid_100m_path, '3.33')

            qainvalid_200m_path = os.path.join(output_downscale_dir, f'{file_prefix}_qainvalid_200m.tif')
            run_script('downscale_qa.py', logger, qa_pixel_path, band10_path, qainvalid_200m_path, '6.67')

            # 2. Downscale RGB to 100m (3.33x)
            downscaled_rgb_100m = os.path.join(output_downscale_dir, f'{file_prefix}_rgb_100m.tif')
            run_script('downscale.py', logger, rgb_output_path, downscaled_rgb_100m, '3.33')

            # 3. Downscale TIR to 100m (3.33x) -- stays box-average: this is the
            #    ground-truth target, not a simulated coarser sensor.
            downscaled_tir_100m = os.path.join(output_downscale_dir, f'{file_prefix}_tir_100m.tif')
            run_script('downscale.py', logger, calibrated_tir_path, downscaled_tir_100m, '3.33')

            # 4. Downscale TIR to 200m (6.67x) -- PSF + NEdeltaT noise: this is
            #    the model's input, simulating a genuinely coarser sensor.
            downscaled_tir_200m = os.path.join(output_downscale_dir, f'{file_prefix}_tir_200m.tif')
            run_script('downscale.py', logger, calibrated_tir_path, downscaled_tir_200m, '6.67', '--mode', 'psf_thermal')

            # 5. Create Coregistered Patches
            run_script('create_patches.py', logger, '--input_dir', output_downscale_dir,
                       '--output_dir', output_patches_dir, '--geo_dir', output_geo_dir)

            logger.info(f"Successfully generated dataset samples for {product_id}")

        except Exception as e:
            logger.error(f"Error processing {product_id}: {e}")

    logger.info("Dataset generation finished. Samples available in output/patches")
    for handler in list(logger.handlers) + list(logging.root.handlers):
        try:
            handler.close()
        except Exception:
            pass

if __name__ == '__main__':
    main()