import glob
import numpy as np
import numpy.ma as ma
import os
import rasterio

from common.constants import NODATA_BYTE, NODATA_UINT16


CLOUD_SCL_CLASSES = [0, 1, 2, 3, 8, 9, 10, 11]


def _add_cloud_prob(image):
    """"""
    pass

def _add_dark_pixels(image):
    """"""
    pass

def _add_cloud_direction(image):
    """"""
    pass


def _mask_band(band_array, scl_array):
    
    mask = np.isin(scl_array, CLOUD_SCL_CLASSES)
    masked_array = ma.masked_array(band_array, mask=mask)
    return masked_array


def save_cloud_masked_images(scene_dict):

    masked_dict = {}

    for band_name in scene_dict:
        if band_name == "SCL": continue

        band_path = scene_dict[band_name]

        masked_path = band_path.replace('.tif', '_masked.tif')
        masked_dict[band_name] = masked_path

        if os.path.exists(masked_path):
            continue

        scl_path = band_path.replace(band_name, "SCL")
        with rasterio.open(scl_path) as scl_src:
            scl_data = scl_src.read(1)

        with rasterio.open(band_path) as band_src:        
            band_data = band_src.read(1)
            masked_data = _mask_band(band_data, scl_data) # MaskedArray
                        
            zeroed_data = masked_data.data
            zeroed_data[masked_data.mask] = NODATA_UINT16
            
            with rasterio.open(masked_path, "w", **band_src.profile) as masked_src:
                masked_src.write(zeroed_data, 1)

    return masked_dict

