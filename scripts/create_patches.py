import tifffile
import numpy as np
import os
import glob
import argparse
import logging
import json
import cv2
from utils.logging_utils import setup_logging
from utils.visualization import percentile_stretch
from utils.file_utils import find_file, extract_product_id
from utils.geo import load_scene_geo, scale_transform, patch_transform, patch_bounds_wgs84

def load_rgb(directory):
    """
    Loads RGB data from a single file or from B2, B3, B4 bands.
    Expected to be 100m resolution.
    """
    rgb_file = find_file(directory, "*100m*RGB*")
    if rgb_file:
        return tifffile.imread(rgb_file)

    b2 = find_file(directory, "*100m*B2*")
    b3 = find_file(directory, "*100m*B3*")
    b4 = find_file(directory, "*100m*B4*")

    if b2 and b3 and b4:
        img2 = tifffile.imread(b2)
        img3 = tifffile.imread(b3)
        img4 = tifffile.imread(b4)
        return np.stack([img2, img3, img4], axis=0)

    return None

def save_as_png(data, path):
    """Saves a numpy array as a normalized PNG for visualization."""
    # Handle (C, H, W) or (H, W)
    if data.ndim == 3:
        # (C, H, W) -> (H, W, C)
        data = np.moveaxis(data, 0, -1)

    # Use percentile stretch for better visualization
    stretched = percentile_stretch(data)
    cv2.imwrite(path, stretched)

def create_patches(input_root, output_root, max_invalid_fraction=0.05, geo_dir=None, stride=128):
    os.makedirs(output_root, exist_ok=True)
    logger = setup_logging(log_name='create_patches', log_dir='output')
    
    if not os.path.exists(input_root):
        logger.error(f"Input root directory {input_root} does not exist.")
        return

    # Find product directories in the input_root
    # If input_root is output_downscale_dir, we need to group files by product_id
    all_files = glob.glob(os.path.join(input_root, '*'))
    products = set()
    for f in all_files:
        filename = os.path.basename(f)
        # Anchor on '_rgb_' / '_tir_' suffix to preserve multi-word product ids
        # (e.g. 'Mumbai_Summer', 'NewYorkCity_Winter') — first-token split would
        # truncate 'Mumbai_Summer' -> 'Mumbai' and merge distinct scenes.
        product_id = extract_product_id(filename)
        products.add(product_id)

    logger.info(f"Found {len(products)} products in {input_root}")

    for product_id in products:
        # Filter files for this product (product_files is informational; paths
        # for each band are resolved individually via find_file below)
        # product_files = [f for f in all_files if os.path.basename(f).startswith(product_id)]
        
        # Identify required images for this product
        tir_200m_path = find_file(input_root, f'{product_id}*_tir_200m*')
        tir_100m_path = find_file(input_root, f'{product_id}*_tir_100m*')
        
        # For RGB, look for the rgb_100m file
        rgb_100m_path = find_file(input_root, f'{product_id}*_rgb_100m*')
        qainvalid_200m_path = find_file(input_root, f'{product_id}*_qainvalid_200m*')
        qainvalid_100m_path = find_file(input_root, f'{product_id}*_qainvalid_100m*')

        if not all([tir_200m_path, tir_100m_path, rgb_100m_path, qainvalid_200m_path, qainvalid_100m_path]):
            logger.warning(f"Skipping {product_id}: Missing required images (200m TIR, 100m TIR, 100m RGB, or QA invalid-fraction maps).")
            continue

        try:
            tir_200m = tifffile.imread(tir_200m_path)
            tir_100m = tifffile.imread(tir_100m_path)
            rgb_100m = tifffile.imread(rgb_100m_path)
            qainvalid_200m = tifffile.imread(qainvalid_200m_path)
            qainvalid_100m = tifffile.imread(qainvalid_100m_path)
        except Exception as e:
            logger.error(f"Error reading images for {product_id}: {e}")
            continue

        h200, w200 = tir_200m.shape[-2:]
        logger.info(f"Generating full dataset patches for {product_id}...")

        # Load scene geo and derive per-resolution transforms (once per product, not per patch)
        scene_geo = None
        if geo_dir:
            geo_json_path = os.path.join(geo_dir, f'{product_id}_native_geo.json')
            if os.path.exists(geo_json_path):
                scene_geo = load_scene_geo(geo_json_path)
            else:
                logger.warning(f"No native geo metadata found for {product_id} at {geo_json_path}; "
                               f"patches for this product will be saved without geolocation.")

        transform_200m = crs = None
        if scene_geo is not None:
            native_transform = scene_geo['transform']
            native_shape = (scene_geo['height'], scene_geo['width'])
            crs = scene_geo['crs']
            transform_100m = scale_transform(native_transform, native_shape, tir_100m.shape[-2:])
            transform_200m = scale_transform(native_transform, native_shape, tir_200m.shape[-2:])

        count = 0
        rejected = 0
        for y in range(0, h200 - 256 + 1, stride):
            for x in range(0, w200 - 256 + 1, stride):
                patch_200m_tir = tir_200m[..., y:y+256, x:x+256]

                y100, x100 = 2*y, 2*x
                patch_100m_tir_512 = tir_100m[..., y100:y100+512, x100:x100+512]
                patch_100m_rgb_512 = rgb_100m[..., y100:y100+512, x100:x100+512]

                if patch_100m_tir_512.shape[-2:] != (512, 512) or patch_100m_rgb_512.shape[-2:] != (512, 512):
                    continue

                patch_200m_invalid = qainvalid_200m[y:y+256, x:x+256]
                patch_100m_invalid = qainvalid_100m[y100:y100+512, x100:x100+512]
                invalid_frac_200m = float(np.mean(patch_200m_invalid))
                invalid_frac_100m = float(np.mean(patch_100m_invalid))

                if invalid_frac_200m > max_invalid_fraction or invalid_frac_100m > max_invalid_fraction:
                    rejected += 1
                    continue

                sample_dir = os.path.join(output_root, product_id, f'sample_{count:03d}')
                os.makedirs(sample_dir, exist_ok=True)

                data_map = {
                    'tir_200m': patch_200m_tir,
                    'tir_100m_512': patch_100m_tir_512,
                    'rgb_100m_512': patch_100m_rgb_512
                }

                for name, data in data_map.items():
                    np.save(os.path.join(sample_dir, f'{name}.npy'), data)
                    save_as_png(data, os.path.join(sample_dir, f'{name}.png'))

                with open(os.path.join(sample_dir, 'qa_meta.json'), 'w') as f:
                    json.dump({'invalid_fraction_200m': invalid_frac_200m,
                               'invalid_fraction_100m': invalid_frac_100m}, f)

                if scene_geo is not None:
                    patch_t = patch_transform(transform_200m, row_off=y, col_off=x)
                    bounds = patch_bounds_wgs84(patch_t, width=256, height=256, crs=crs)
                    with open(os.path.join(sample_dir, 'geo_meta.json'), 'w') as f:
                        json.dump({
                            'crs': crs,
                            'patch_transform_200m': list(patch_t)[:6],
                            'bounds_wgs84': bounds,
                        }, f)

                count += 1

        logger.info(f"Successfully created {count} samples for {product_id} ({rejected} rejected for cloud/shadow/fill).")

    for handler in logger.handlers[:]:
        handler.close()
        logger.removeHandler(handler)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Create co-registered image patches.')
    parser.add_argument('--input_dir', type=str, default='input', help='Path to input root directory.')
    parser.add_argument('--output_dir', type=str, default='output/patches', help='Path to output directory.')
    parser.add_argument('--max_invalid_fraction', type=float, default=0.05,
                        help='Reject a patch if more than this fraction of it is cloud/shadow/fill/no-data.')
    parser.add_argument('--geo_dir', type=str, default=None,
                        help='Directory containing {product_id}_native_geo.json files (from driver.py). '
                             'If omitted, patches are created without geolocation metadata.')
    parser.add_argument('--stride', type=int, default=128,
                        help='Patch extraction stride in 200m pixels. '
                             '128 = 50%% overlap on 256px patches (default). '
                             '256 = non-overlapping (original behaviour).')
    args = parser.parse_args()
    create_patches(args.input_dir, args.output_dir,
                   max_invalid_fraction=args.max_invalid_fraction,
                   geo_dir=args.geo_dir,
                   stride=args.stride)
