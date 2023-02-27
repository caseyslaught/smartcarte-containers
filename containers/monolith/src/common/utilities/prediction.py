import numpy as np
import rasterio


from common.constants import NODATA_BYTE
from common.utilities.imagery import write_array_to_tif


def predict_forest(composite_path, dst_path):

    with rasterio.open(composite_path) as src:
        bbox = list(src.bounds)
        composite_data = src.read(masked=True)
    
    red = composite_data[2, :, :]
    nir = composite_data[3, :, :]
    ndvi = (nir - red) / (nir + red) # this should be okay because they're already floats

    is_forest = (ndvi > 0.70)
    not_forest = (ndvi < 0.30)

    forest_data = np.full(ndvi.shape, 50).astype(np.uint8)
    forest_data[is_forest] = 100
    forest_data[not_forest] = 0
    forest_data[ndvi.mask] = NODATA_BYTE

    write_array_to_tif(forest_data, dst_path, bbox, dtype=np.uint8, nodata=NODATA_BYTE, is_cog=True)


def predict_forest_change(before_forest_path, after_forest_path, dst_path):
    
    with rasterio.open(before_forest_path) as before_src:
        before_forest = before_src.read(1, masked=True)
        bbox = list(before_src.bounds)

    with rasterio.open(after_forest_path) as after_src:
        after_forest = after_src.read(1, masked=True)

    gain = (after_forest - before_forest) > 1.0
    loss = (after_forest - before_forest) < -1.0

    change = np.full(before_forest.shape, 50).astype(np.uint8)
    change[gain] = 100
    change[loss] = 0
    change[gain.mask] = NODATA_BYTE

    write_array_to_tif(change, dst_path, bbox, dtype=np.uint8, nodata=NODATA_BYTE, is_cog=True)

