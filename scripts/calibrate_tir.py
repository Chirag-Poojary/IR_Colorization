import tifffile
import numpy as np
import os
import argparse
import logging
import cv2

logger = logging.getLogger(__name__)

from utils.file_utils import validate_extension
from utils.radiometry import st_dn_to_kelvin
from utils.visualization import percentile_stretch


def calibrate_tir(input_filepath, output_filepath):
    validate_extension(input_filepath)
    validate_extension(output_filepath)
    os.makedirs(os.path.dirname(output_filepath), exist_ok=True)

    dn = tifffile.imread(input_filepath)
    kelvin = st_dn_to_kelvin(dn)

    tifffile.imwrite(output_filepath, kelvin)
    logger.info(f'Calibrated {input_filepath} (raw DN) -> {output_filepath} (Kelvin)')

    png_output_dir = os.path.join(os.path.dirname(output_filepath), 'png')
    os.makedirs(png_output_dir, exist_ok=True)
    png_output_path = os.path.join(
        png_output_dir, os.path.splitext(os.path.basename(output_filepath))[0] + '.png'
    )
    cv2.imwrite(png_output_path, percentile_stretch(kelvin))
    logger.info(f'Saved visualization PNG to {png_output_path}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Calibrate a raw Landsat C2 L2 ST_B10 band to Kelvin.')
    parser.add_argument('input_filepath', type=str, help='Path to the raw ST_B10 TIFF file.')
    parser.add_argument('output_filepath', type=str, help='Path to save the calibrated (Kelvin) TIFF file.')
    args = parser.parse_args()

    try:
        calibrate_tir(args.input_filepath, args.output_filepath)
    except Exception as e:
        logger.error(f"Error calibrating TIR band: {e}")
        exit(1)
