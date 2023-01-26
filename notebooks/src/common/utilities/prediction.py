import numpy as np
import rasterio


from common.constants import NODATA_BYTE, NODATA_INT8


def predict_forest(band_dict, dst_path):

    with rasterio.open(band_dict['NDVI']) as ndvi_src:
        ndvi_data = ndvi_src.read(1, masked=True)
        meta = ndvi_src.meta.copy()
        meta['dtype'] = 'int8'
        meta['nodata'] = NODATA_INT8

    is_forest = (ndvi_data > 0.70)
    not_forest = (ndvi_data < 0.30)

    forest_data = np.full(ndvi_data.shape, 0)
    forest_data[is_forest] = 1
    forest_data[not_forest] = -1
    forest_data[ndvi_data.mask] = NODATA_INT8
    forest_data = forest_data.astype(np.int8)

    with rasterio.open(dst_path, "w", **meta) as forest_dst:
        forest_dst.write(forest_data, indexes=1)


def predict_forest_change(before_forest_path, after_forest_path, dst_path):
    
    with rasterio.open(before_forest_path) as before_src:
        before_forest = before_src.read(1, masked=True)
        meta = before_src.meta.copy()

    with rasterio.open(after_forest_path) as after_src:
        after_forest = after_src.read(1, masked=True)

    gain = (after_forest - before_forest) > 1.0
    loss = (after_forest - before_forest) < -1.0

    change = np.full(before_forest.shape, 0)
    change[gain] = 1
    change[loss] = -1
    change[gain.mask] = NODATA_INT8
    change = change.astype(np.int8)

    with rasterio.open(dst_path, "w", **meta) as change_dst:
        change_dst.write(change, indexes=1)


