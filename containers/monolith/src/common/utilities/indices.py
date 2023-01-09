import numpy as np
import rasterio
from rasterio.windows import Window

from common.constants import NODATA_UINT16


def save_ndvi(red_path, nir_path, step):
    """"""
    
    red_src = rasterio.open(red_path)
    nir_src = rasterio.open(nir_path)

    meta = nir_src.meta.copy()        
    width, height = nir_src.width, nir_src.height

    ndvi_path = f'/tmp/{step}/ndvi.tif'
    with rasterio.open(ndvi_path, "w", **meta) as ndvi_dst:
        for row in range(height):
            red = red_src.read(1, masked=True, window=Window(0, row, width, 1))
            nir = nir_src.read(1, masked=True, window=Window(0, row, width, 1))

            # (NIR-Red) / (NIR+Red)
            ndvi = (nir.astype(np.float64) - red.astype(np.float64)) / (nir + red)
            ndvi = ndvi.astype(np.uint16)
            
            ndvi[ndvi.mask] = NODATA_UINT16 
            ndvi_dst.write(ndvi, window=Window(0, row, width, 1), indexes=1)

    return ndvi_path


