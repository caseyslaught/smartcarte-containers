import numpy as np
import rioxarray

from common.constants import NODATA_FLOAT32



def create_ndvi(red_path, nir_path, dst_path):
    """
    Calculates and save the Normalized Difference Vegetation Index (NDVI) to disk.
    """

    red_da = rioxarray.open_rasterio(red_path, chunks=(1, 1000, 1000), masked=True)
    nir_da = rioxarray.open_rasterio(nir_path, chunks=(1, 1000, 1000), masked=True)

    ndvi_da = (nir_da.astype(np.float32) - red_da.astype(np.float32)) / (nir_da + red_da)
    
    ndvi_da.rio.to_raster(dst_path, dtype='float32', nodata=NODATA_FLOAT32)


def create_ndwi(green_path, nir_path, dst_path):
    """
    Calaculates and save the Normalized Difference Water Index (NDWI) to disk.
    """
    
    green_da = rioxarray.open_rasterio(green_path, chunks=(1, 1000, 1000), masked=True)
    nir_da = rioxarray.open_rasterio(nir_path, chunks=(1, 1000, 1000), masked=True)

    ndwi_da = (green_da.astype(np.float32) - nir_da.astype(np.float32)) / (green_da + nir_da)
    
    ndwi_da.rio.to_raster(dst_path, dtype='float32', nodata=NODATA_FLOAT32)


def create_ndbi(swir1_path, nir_path, dst_path):
    """
    Calculates and save the Normalized Difference Built-up Index (NDBI) to disk.
    """
        
    swir1_da = rioxarray.open_rasterio(swir1_path, chunks=(1, 1000, 1000), masked=True)
    nir_da = rioxarray.open_rasterio(nir_path, chunks=(1, 1000, 1000), masked=True)

    ndbi_da = (swir1_da.astype(np.float32) - nir_da.astype(np.float32)) / (swir1_da + nir_da)
    
    ndbi_da.rio.to_raster(dst_path, dtype='float32', nodata=NODATA_FLOAT32)


