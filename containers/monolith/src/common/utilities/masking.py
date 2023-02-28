import numpy as np
import rasterio
from scipy.ndimage import maximum_filter
import torch


from common.constants import NODATA_FLOAT32
from common.utilities.imagery import write_array_to_tif


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


def _get_cloud_shadow_mask(cloud_mask, azimuth, zenith):

    # solar azimuth is opposite of illumination direction plus another 90 for the S2 instrument
    azimuth = azimuth - 270   
    azimuth_rad = np.deg2rad(azimuth)
    zenith_rad = np.deg2rad(zenith)
        
    cloud_heights = np.arange(400, 1600, 200) 
    potential_shadow = np.array([
        _get_potential_shadow(cloud_height, azimuth_rad, zenith_rad, cloud_mask) 
        for cloud_height in cloud_heights
    ])

    potential_shadow = np.sum(potential_shadow, axis=0) > 0
        
    return potential_shadow


### SCL masking ###

def _get_scl_bad_pixel_mask(scl):
    
    bad_values = [0, 1, 11]
    mask = np.isin(scl, bad_values)
    return mask
    

def _get_scl_cloud_mask(scl):

    cloud_values = [8, 9, 10]
    mask = np.isin(scl, cloud_values)    
    return mask


### cloud masking coordinator ###

def apply_nn_cloud_mask(stack_tif_path, meta, dst_path, model_path):
    
    with rasterio.open(stack_tif_path) as src:
        stack_data = src.read(masked=True)
        bbox = list(src.bounds)
                        
    scl_data = stack_data[-1, :, :]
        
    image = stack_data[:-1, :, :]
    saved_shape = image.shape

    height_pad = 32 - (image.shape[1] % 32)
    width_pad = 32 - (image.shape[2] % 32)
    image = np.pad(image, ((0, 0), (0, height_pad), (0, width_pad)), mode='reflect')
        
    image = np.expand_dims(image, 0)
    image = torch.tensor(image)
        
    # sometimes it is crashing here...
    model = torch.load(model_path)
    prediction = model.predict(image)
    
    print('\t\tprediction done')
    probabilities = torch.sigmoid(prediction).cpu().numpy()
    probabilities = probabilities[0, 0, :, :]
    binary_prediction = (probabilities >= 0.50).astype(bool)
    nn_cloud_mask = binary_prediction[:saved_shape[1], :saved_shape[2]]
    
    scl_cloud_mask = _get_scl_cloud_mask(scl_data)
    cloud_mask = nn_cloud_mask | scl_cloud_mask
    
    # calculate dark pixel masks
    bad_mask = _get_scl_bad_pixel_mask(scl_data)
    cloud_shadow_mask = _get_cloud_shadow_mask(cloud_mask, meta["AZIMUTH_ANGLE"], meta["ZENITH_ANGLE"])
        
    # this is also taking a long time...but not too long
    full_mask = cloud_mask | bad_mask | cloud_shadow_mask
    full_mask = _buffer_mask(full_mask, radius=20)
    
    stack_data.mask = full_mask    
    stack_data = stack_data[:-1, :, :]
    stack_data = stack_data.transpose((1, 2, 0))
    
    write_array_to_tif(stack_data, dst_path, bbox, dtype=np.float32, epsg=4326, nodata=NODATA_FLOAT32)
    
    pct_masked = full_mask.sum() / full_mask.size
    print(pct_masked)
    return pct_masked < 0.90

