"""
Lightweight geolocation helpers built on rasterio.

Every other script in this pipeline reads pixels with tifffile, which drops
all georeferencing (CRS + affine transform). This module is the only place
rasterio is used - purely to capture that georeferencing once per scene (all
bands of one Landsat scene share the same grid) and propagate it forward as
a small JSON sidecar, without re-plumbing rasterio through every existing
script.
"""
import os
import json
import rasterio
from rasterio.transform import Affine
from rasterio.warp import transform_bounds


def read_scene_geo(raw_band_path):
    """
    Read CRS + affine transform + shape from any one raw band of a scene.
    All bands of a single Landsat scene share the same grid, so any one
    (SR_B2, ST_B10, etc.) is representative of the whole scene.
    """
    with rasterio.open(raw_band_path) as src:
        return {
            'crs': src.crs.to_string(),
            'transform': list(src.transform)[:6],
            'width': src.width,
            'height': src.height,
        }


def save_scene_geo(geo_dict, output_path):
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, 'w') as f:
        json.dump(geo_dict, f)


def load_scene_geo(geo_json_path):
    with open(geo_json_path, 'r') as f:
        d = json.load(f)
    d['transform'] = Affine(*d['transform'])
    return d


def scale_transform(native_transform, native_shape, new_shape):
    """
    Derive the transform for a downscaled grid, preserving the exact
    original geographic extent (top-left corner + total footprint) rather
    than naively multiplying by a nominal scale factor. This absorbs the
    rounding in round(h/factor)/round(w/factor) into a negligibly adjusted
    pixel size instead of letting positional error creep in.
    """
    h0, w0 = native_shape
    new_h, new_w = new_shape
    extent_x = native_transform.a * w0
    extent_y = native_transform.e * h0
    new_pixel_w = extent_x / new_w
    new_pixel_h = extent_y / new_h
    return Affine(new_pixel_w, 0, native_transform.c, 0, new_pixel_h, native_transform.f)


def patch_transform(parent_transform, row_off, col_off):
    """Transform for a sub-window patch: the parent transform translated to the patch's pixel offset."""
    return parent_transform * Affine.translation(col_off, row_off)


def patch_bounds_wgs84(transform, width, height, crs):
    """Corner bounding box of a patch, reprojected to WGS84 (lon/lat)."""
    left, top = transform.c, transform.f
    right = left + transform.a * width
    bottom = top + transform.e * height
    minx, miny, maxx, maxy = transform_bounds(crs, 'EPSG:4326', left, bottom, right, top)
    return {'west': minx, 'south': miny, 'east': maxx, 'north': maxy}
