import numpy as np
import rasterio
from rasterio.windows import Window
import rioxarray

from common.constants import NODATA_FLOAT32, NODATA_UINT16



def create_ndvi(red_path, nir_path, dst_path):

    red_da = rioxarray.open_rasterio(red_path, chunks=(1, 1000, 1000), mask_and_scale=True)
    nir_da = rioxarray.open_rasterio(nir_path, chunks=(1, 1000, 1000), mask_and_scale=True)
    
    with rasterio.open(red_path) as band_src:
        meta = band_src.meta.copy()
        meta['dtype'] = 'float32'
        meta['nodata'] = NODATA_FLOAT32

    ndvi_da = (nir_da.astype(np.float32) - red_da.astype(np.float32)) / (nir_da + red_da)
    ndvi = ndvi_da.compute()

    with rasterio.open(dst_path, "w", **meta) as composite_dst:
        composite_dst.write(ndvi.data, indexes=1)



def save_ndvi_old(red_path, nir_path, step):
    """"""

    # TODO: use Dask to parallelize this
    
    red_src = rasterio.open(red_path)
    nir_src = rasterio.open(nir_path)

    meta = nir_src.meta.copy()
    meta['dtype'] = 'float32'
    meta['nodata'] = NODATA_FLOAT32
    width, height = nir_src.width, nir_src.height

    ndvi_path = f'/tmp/{step}/ndvi.tif'
    with rasterio.open(ndvi_path, "w", **meta) as ndvi_dst:
        for row in range(height):
            red = red_src.read(1, masked=True, window=Window(0, row, width, 1))
            nir = nir_src.read(1, masked=True, window=Window(0, row, width, 1))

            # (NIR-Red) / (NIR+Red)
            ndvi = (nir.astype(np.float32) - red.astype(np.float32)) / (nir + red)

            ndvi[ndvi.mask] = NODATA_FLOAT32 
            ndvi_dst.write(ndvi, window=Window(0, row, width, 1), indexes=1)

    return ndvi_path


