import tifffile
import numpy as np
import os
import argparse
import cv2
import logging

logger = logging.getLogger(__name__)

from utils.file_utils import validate_extension
from utils.qa_mask import decode_qa_pixel_invalid
from utils.radiometry import ST_VALID_DN_MIN, ST_VALID_DN_MAX


def build_invalid_mask(qa_pixel_path, st_b10_raw_path):
    qa = tifffile.imread(qa_pixel_path)
    invalid = decode_qa_pixel_invalid(qa)

    st_dn = tifffile.imread(st_b10_raw_path)
    st_fill = (st_dn < ST_VALID_DN_MIN) | (st_dn > ST_VALID_DN_MAX)

    return (invalid | st_fill).astype(np.float32)  # 1.0 = invalid, 0.0 = good


def downscale_mask(mask, factor):
    h, w = mask.shape
    new_h, new_w = int(round(h / factor)), int(round(w / factor))
    # Plain box average is correct here - this is an areal coverage
    # fraction, not a physical signal, so PSF+noise does not apply.
    return cv2.resize(mask, (new_w, new_h), interpolation=cv2.INTER_AREA)


def generate_invalid_fraction_map(qa_pixel_path, st_b10_raw_path, output_filepath, scale_factor):
    validate_extension(qa_pixel_path)
    validate_extension(st_b10_raw_path)
    os.makedirs(os.path.dirname(output_filepath), exist_ok=True)

    invalid_mask = build_invalid_mask(qa_pixel_path, st_b10_raw_path)
    invalid_fraction = downscale_mask(invalid_mask, scale_factor)

    tifffile.imwrite(output_filepath, invalid_fraction.astype(np.float32))
    logger.info(f'Wrote invalid-fraction map to {output_filepath}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Build a downscaled invalid-pixel-fraction map from QA_PIXEL + ST fill detection.'
    )
    parser.add_argument('qa_pixel_path', type=str)
    parser.add_argument('st_b10_raw_path', type=str)
    parser.add_argument('output_filepath', type=str)
    parser.add_argument('scale_factor', type=float)
    args = parser.parse_args()

    try:
        generate_invalid_fraction_map(
            args.qa_pixel_path, args.st_b10_raw_path, args.output_filepath, args.scale_factor
        )
    except Exception as e:
        logger.error(f"Error building invalid-fraction map: {e}")
        exit(1)
