import glob
import numpy as np
import numpy.ma as ma
import os
import rasterio
import rioxarray
from scipy.ndimage import maximum_filter


from common.constants import NODATA_UINT16


### buffer around masked values ###

def _get_circular_mask(size):
    
    radius = int(size/2)
    center = (radius, radius)
    Y, X = np.ogrid[:size, :size]
    dist_from_center = np.sqrt((X - center[0])**2 + (Y-center[1])**2)

    mask = dist_from_center <= radius
    return mask


def _buffer_mask(mask, radius=12):
    
    kernel = _get_circular_mask(radius)
    mask = maximum_filter(mask, footprint=kernel, mode='constant', cval=0)
    return mask


### cloud shadow and directional masking ###

def _get_potential_shadow(cloud_height, azimuth_rad, zenith_rad, cloud_mask, scale=10):

    shadow_vector = round(np.tan(zenith_rad) * cloud_height)
        
    x_shift = round(np.cos(azimuth_rad) * shadow_vector / scale)
    y_shift = round(np.sin(azimuth_rad) * shadow_vector / scale)

    # print('\t\tx_shift:', x_shift, ', y_shift:', y_shift)
    
    shadows = np.roll(cloud_mask, y_shift, axis=0)
    shadows = np.roll(shadows, x_shift, axis=1)
    
    if x_shift > 0:
        shadows[:, :x_shift] = False
    elif x_shift < 0:
        shadows[:, x_shift:] = False

    if y_shift > 0:
        shadows[:y_shift, :] = False
    elif y_shift < 0:
        shadows[y_shift:, :] = False
    
    return shadows


def _get_cloud_shadow_mask(cloud_mask, azimuth, zenith, nir_array, scl_array):

    # solar azimuth is opposite of illumination direction plus another 90 for the S2 instrument
    azimuth = azimuth - 270   
    azimuth_rad = np.deg2rad(azimuth)
    zenith_rad = np.deg2rad(zenith)
        
    cloud_heights = np.arange(400, 1200, 200) 
    potential_shadow = np.array([
        _get_potential_shadow(cloud_height, azimuth_rad, zenith_rad, cloud_mask) 
        for cloud_height in cloud_heights
    ])

    potential_shadow = np.sum(potential_shadow, axis=0) > 0
    
    water = scl_array == 6
    dark_pixels = (nir_array < 1500) & ~water
    
    shadow = potential_shadow & dark_pixels
    
    return shadow


### SCL masking ###

def _get_scl_bad_pixel_mask(scl):
    
    bad_values = [0, 1, 11]
    mask = np.isin(scl, bad_values)
    return mask
    

def _get_scl_cloud_mask(scl):

    cloud_values = [8, 9, 10]
    mask = np.isin(scl, cloud_values)    
    return mask


def _get_bcy_cloud_mask(green, red):
    
    # (green > 0.175 AND NDGR > 0) OR (green > 0.39)
       
    ndgr = (green.astype(np.float32) - red.astype(np.float32)) / (green + red)
    
    cond1 = (green > 1750) & (ndgr > 0) 
    cond2 = green > 3900
    mask = cond1 | cond2
    
    return mask


### cloud masking coordinator ###

def save_cloud_masked_images(scene_dict, dst_dir, overwrite=True):
    
    if os.path.exists(f'{dst_dir}/B08_masked.tif') and not overwrite:
        return {
            band_name: f'{dst_dir}/{band_name}_masked.tif'
            for band_name in scene_dict
        }
    
    with rasterio.open(scene_dict['B03']) as green_src:
        green_data = green_src.read(1, masked=True)

    with rasterio.open(scene_dict['B04']) as red_src:
        red_data = red_src.read(1, masked=True)
    
    with rasterio.open(scene_dict['B08']) as nir_src:
        nir_data = nir_src.read(1, masked=True)
        
    with rasterio.open(scene_dict['SCL']) as scl_src:
        scl_data = scl_src.read(1, masked=True)
    
    bcy_cloud_mask = _get_bcy_cloud_mask(green_data, red_data) 
    scl_cloud_mask = _get_scl_cloud_mask(scl_data)
    cloud_mask = bcy_cloud_mask | scl_cloud_mask

    bad_mask = _get_scl_bad_pixel_mask(scl_data)

    meta = scene_dict['meta']
    cloud_shadow_mask = _get_cloud_shadow_mask(cloud_mask, meta["AZIMUTH_ANGLE"], meta["ZENITH_ANGLE"], nir_data, scl_data)

    mask = cloud_mask | bad_mask | cloud_shadow_mask
    mask = _buffer_mask(mask)

    masked_dict = {}
    for band_name in scene_dict:
        if band_name in ["meta", "SCL"]: continue

        band_path = scene_dict[band_name]
        masked_path = f'{dst_dir}/{band_name}_masked.tif'
        masked_dict[band_name] = masked_path
           
        with rasterio.open(band_path) as band_src:        
            band_data = band_src.read(1)           
            masked_data = ma.masked_array(band_data, mask=mask)
                
            zeroed_data = masked_data.data
            zeroed_data[masked_data.mask] = NODATA_UINT16
            
            with rasterio.open(masked_path, "w", **band_src.profile) as masked_src:
                masked_src.write(zeroed_data, 1)

    return masked_dict

