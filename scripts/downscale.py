import numpy as np
import tifffile
import os
import argparse
import cv2
import logging

logger = logging.getLogger(__name__)

from utils.file_utils import validate_extension

def box_average_downscale(image, factor):
    h, w = image.shape
    new_h = int(round(h / factor))
    new_w = int(round(w / factor))
    return cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_AREA)


def psf_downscale(image, factor, sigma=None, neqt_kelvin=0.4, seed=None):
    """
    Simulate what a genuinely coarser thermal sensor would capture, instead
    of pure pixel-averaging: blur with an approximate Gaussian point-spread
    function (PSF) sized to the resampling factor, resample, then add
    sensor noise.

    sigma: defaults to factor / 2.355 (i.e. the PSF's FWHM ~= the resampling
    factor). This is a reasonable heuristic, not a measured TIRS MTF -
    refining it against the sensor's actual modulation transfer function is
    a fine future improvement, out of scope here.

    neqt_kelvin: defaults to 0.4K, which is Landsat TIRS's *design
    specification* NEdeltaT at 300K for bands 10/11 (<=0.4K per the
    official requirement). On-orbit *measured* performance is actually much
    better - about 0.05-0.06K (Montanaro et al., "On-Orbit Radiometric
    Performance of the Landsat 8 Thermal Infrared Sensor", Remote Sensing
    2014). 0.4K is used as the default here because it's the more
    conservative, citable spec value and gives the model a somewhat
    noisier, more robust training signal; pass neqt_kelvin=0.06 if you'd
    rather match measured real-world performance more closely.
    """
    if sigma is None:
        sigma = factor / 2.355
    blurred = cv2.GaussianBlur(image.astype(np.float32), ksize=(0, 0), sigmaX=sigma)
    h, w = image.shape
    new_h, new_w = int(round(h / factor)), int(round(w / factor))
    resized = cv2.resize(blurred, (new_w, new_h), interpolation=cv2.INTER_AREA)
    rng = np.random.default_rng(seed)
    noise = rng.normal(0, neqt_kelvin, resized.shape).astype(np.float32)
    return (resized + noise).astype(np.float32)


def downscale_image(input_filepath, output_filepath, scale_factor, mode='box', neqt_kelvin=0.4, seed=None):
    validate_extension(input_filepath)
    validate_extension(output_filepath)
    os.makedirs(os.path.dirname(output_filepath), exist_ok=True)

    image_data = tifffile.imread(input_filepath)
    if image_data.ndim == 2:
        image_data = image_data[np.newaxis, ...]

    downscaled_bands = []
    for band in image_data:
        if mode == 'psf_thermal':
            downscaled_band = psf_downscale(band, scale_factor, neqt_kelvin=neqt_kelvin, seed=seed)
        else:
            downscaled_band = box_average_downscale(band, scale_factor)
        downscaled_bands.append(downscaled_band)

    downscaled_data = np.stack(downscaled_bands, axis=0)
    out_dtype = np.float32 if mode == 'psf_thermal' else image_data.dtype
    tifffile.imwrite(output_filepath, downscaled_data.astype(out_dtype))
    logger.info(f'Downscaled {input_filepath} by factor {scale_factor} (mode={mode}) to {output_filepath}')

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Downscale a TIFF image.')
    parser.add_argument('input_filepath', type=str, help='Path to the input TIFF file.')
    parser.add_argument('output_filepath', type=str, help='Path to save the downscaled TIFF file.')
    parser.add_argument('scale_factor', type=float, help='Factor by which to downscale (e.g., 3.33 for 30m to 100m).')
    parser.add_argument('--mode', type=str, default='box', choices=['box', 'psf_thermal'],
                        help="'box' = plain pixel-average. 'psf_thermal' = Gaussian PSF + NEdeltaT noise.")
    parser.add_argument('--neqt_kelvin', type=float, default=0.4,
                        help='Noise std-dev in Kelvin for psf_thermal mode (default 0.4K = TIRS design spec).')
    parser.add_argument('--seed', type=int, default=None,
                        help='Optional RNG seed for reproducible noise.')

    args = parser.parse_args()

    try:
        downscale_image(args.input_filepath, args.output_filepath, args.scale_factor,
                        mode=args.mode, neqt_kelvin=args.neqt_kelvin, seed=args.seed)
    except Exception as e:
        logger.error(f"Error downscaling image: {e}")
        exit(1)
