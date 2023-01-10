import numpy as np
import rasterio

from common.constants import NODATA_BYTE, NODATA_INT8


def save_forest_classification(band_dict, step):

    blue_src = rasterio.open(band_dict["B02"])
    green_src = rasterio.open(band_dict["B03"])
    red_src = rasterio.open(band_dict["B04"])
    nir_src = rasterio.open(band_dict["B08"])
    ndvi_src = rasterio.open(band_dict["NDVI"])

    forest_path = f'/tmp/{step}/forest.tif'

    # super basic placeholder "classifier"

    ndvi_data = ndvi_src.read(1, masked=True)

    is_forest = (ndvi_data > 0.70)
    not_forest = (ndvi_data < 0.30)

    forest_data = np.full(ndvi_data.shape, 0)
    forest_data[is_forest] = 1
    forest_data[not_forest] = -1
    forest_data[ndvi_data.mask] = NODATA_INT8
    forest_data = forest_data.astype(np.int8)

    meta = ndvi_src.meta.copy()
    meta['dtype'] = 'int8'
    meta['nodata'] = NODATA_INT8
    with rasterio.open(forest_path, "w", **meta) as forest_dst:
        forest_dst.write(forest_data, indexes=1)

    return forest_path


def save_forest_change(before_path, after_path):
    
    before_src = rasterio.open(before_path)
    before_forest = before_src.read(1, masked=True)

    after_src = rasterio.open(after_path)
    after_forest = after_src.read(1, masked=True)
    
    gain = (after_forest - before_forest) > 1.0
    loss = (after_forest - before_forest) < -1.0

    change = np.full(before_forest.shape, 0)
    change[gain] = 1
    change[loss] = -1
    change[gain.mask] = NODATA_INT8
    change = change.astype(np.int8)

    meta = after_src.meta.copy()
    change_path = '/tmp/change.tif'
    with rasterio.open(change_path, "w", **meta) as change_dst:
        change_dst.write(change, indexes=1)

    return change_path
