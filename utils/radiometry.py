"""
Radiometric calibration for Landsat Collection 2 Level-2 products.

These scale/offset pairs are fixed constants published by USGS for every
Landsat 8/9 Collection 2 Level-2 scene -- they are NOT scene-specific and do
NOT require an .MTL file. (Contrast with Level-1 products, where converting
raw DN to brightness temperature needs per-scene K1/K2 constants from that
scene's .MTL file -- this pipeline downloads Level-2 products, so that path
does not apply here.)

Source: USGS, "How do I use a scale factor with Landsat Level-2 science products?"
"""
import numpy as np

SR_SCALE, SR_OFFSET = 0.0000275, -0.2
ST_SCALE, ST_OFFSET = 0.00341802, 149.0

# Valid DN ranges per USGS docs. DN outside this range (most commonly exactly 0)
# is fill/no-data, not a real reading.
ST_VALID_DN_MIN, ST_VALID_DN_MAX = 293, 65535
SR_VALID_DN_MIN, SR_VALID_DN_MAX = 7273, 43636


def sr_dn_to_reflectance(dn_array):
    """Raw SR_B* digital numbers -> surface reflectance (unitless, roughly 0-1)."""
    return dn_array.astype(np.float32) * SR_SCALE + SR_OFFSET


def st_dn_to_kelvin(dn_array):
    """
    Raw ST_B10 digital numbers -> Kelvin.

    Scope note: this applies ONLY the scale/offset. It deliberately does not
    mask fill values (DN outside [293, 65535], most commonly DN == 0) -- that
    is the job of the QA_PIXEL/no-data filtering step, a separate build-order
    item, not this one. A raw DN of 0 will convert to exactly 149.0 K
    (~-124 degC) here; that is a fill sentinel, not a real temperature, and
    it is expected to still be present in the output of this function.
    """
    return dn_array.astype(np.float32) * ST_SCALE + ST_OFFSET
