import numpy as np

# Landsat 8/9 Collection 2 QA_PIXEL bit positions, per USGS "Landsat
# Collection 2 Quality Assessment Bands" documentation. Bits 0-4 are the
# same bit range used in USGS's and Google Earth Engine's own reference
# cloud-masking examples for Landsat 8/9 Collection 2 Level-2 products.
BIT_FILL = 0
BIT_DILATED_CLOUD = 1
BIT_CIRRUS = 2
BIT_CLOUD = 3
BIT_CLOUD_SHADOW = 4

INVALID_BITMASK = (
    (1 << BIT_FILL) | (1 << BIT_DILATED_CLOUD) | (1 << BIT_CIRRUS) |
    (1 << BIT_CLOUD) | (1 << BIT_CLOUD_SHADOW)
)  # 0b11111 = 31


def decode_qa_pixel_invalid(qa_array):
    """Boolean array, True where fill, dilated cloud, cirrus, cloud, or cloud shadow (bits 0-4) is set."""
    return (qa_array.astype(np.uint16) & INVALID_BITMASK) != 0
