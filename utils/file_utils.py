import os
import glob
import re
import logging

def validate_extension(file_path, expected_extension=".TIF"):
    """Validates that a file has the expected extension (case-insensitive)."""
    return file_path.lower().endswith(expected_extension.lower())

def find_file(directory, pattern):
    """Finds a file in the directory matching the pattern. Returns the first match or None."""
    # Add wildcards if not present to perform a 'contains' search
    search_pattern = pattern
    if not search_pattern.startswith('*'):
        search_pattern = '*' + search_pattern
    if not search_pattern.endswith('*'):
        search_pattern = search_pattern + '*'

    files = glob.glob(os.path.join(directory, search_pattern))
    # Prioritize .TIF (case-insensitive)
    tif_files = [f for f in files if f.lower().endswith(('.tif', '.tiff'))]

    if tif_files:
        return tif_files[0]
    return files[0] if files else None


def extract_product_id(filename):
    """
    Extract the product/scene id from a downscaled-output filename.

    Filenames produced by driver.py always have the form
    '{product_id}_rgb_{res}m.tif' or '{product_id}_tir_{res}m.tif',
    where product_id itself may contain underscores (e.g. 'Mumbai_Summer',
    'NewYorkCity_Winter'). Anchor on the known '_rgb_' / '_tir_' suffix
    instead of blindly splitting on the first underscore — a first-token
    split truncates 'Mumbai_Summer' down to just 'Mumbai' and silently
    collapses different seasons of the same location into one product id.
    """
    match = re.match(r'^(.+?)_(?:rgb|tir|qainvalid)_\d+m', filename)
    if match:
        return match.group(1)
    logging.getLogger(__name__).warning(
        f"Could not confidently parse product_id from '{filename}'; "
        f"falling back to a first-token split, which may be wrong."
    )
    return filename.split('_')[0]
