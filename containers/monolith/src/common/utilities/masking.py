import numpy as np
import rasterio
from scipy.ndimage import maximum_filter
import torch


from common.constants import NODATA_FLOAT32
from common.utilities.imagery import write_array_to_tif, create_rgb_byte_tif_from_composite


### buffer around masked values ###

def __get_circular_mask(size):
    
    radius = int(size/2)
    center = (radius, radius)
    Y, X = np.ogrid[:size, :size]
    dist_from_center = np.sqrt((X - center[0])**2 + (Y-center[1])**2)

    mask = dist_from_center <= radius
    return mask


def __buffer_mask(mask, radius=12):
    
    kernel = __get_circular_mask(radius)
    mask = maximum_filter(mask, footprint=kernel, mode='constant', cval=0)
    return mask


### cloud shadow and directional masking ###

def __get_potential_shadow(cloud_height, azimuth_rad, zenith_rad, cloud_mask, scale=10):

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


def __get_cloud_shadow_mask(cloud_mask, azimuth, zenith):

    # solar azimuth is opposite of illumination direction plus another 90 for the S2 instrument
    azimuth = azimuth - 270   
    azimuth_rad = np.deg2rad(azimuth)
    zenith_rad = np.deg2rad(zenith)
        
    cloud_heights = np.arange(400, 1600, 200) 
    potential_shadow = np.array([
        __get_potential_shadow(cloud_height, azimuth_rad, zenith_rad, cloud_mask) 
        for cloud_height in cloud_heights
    ])

    potential_shadow = np.sum(potential_shadow, axis=0) > 0
    
    shadow = potential_shadow
    
    return shadow


### SCL masking ###

def __get_scl_bad_pixel_mask(scl):
    
    bad_values = [0, 1, 11]
    mask = np.isin(scl, bad_values)
    return mask
    

def __get_scl_cloud_mask(scl):

    cloud_values = [8, 9, 10]
    mask = np.isin(scl, cloud_values)    
    return mask


### deprecated ###

def apply_scl_cloud_mask(stack_tif_path, meta, dst_path):
    
    with rasterio.open(stack_tif_path) as src:
        stack_data = src.read(masked=True)
        bbox = list(src.bounds)
                    
    nir_data = stack_data[3, :, :]
    scl_data = stack_data[-1, :, :]
    
    # calculate cloud mask
    # bcy_cloud_mask = _get_bcy_cloud_mask(green_data, red_data) 
    scl_cloud_mask = __get_scl_cloud_mask(scl_data)
    cloud_mask = scl_cloud_mask # | bcy_cloud_mask

    # calculate dark pixel masks
    bad_mask = __get_scl_bad_pixel_mask(scl_data)
    cloud_shadow_mask = __get_cloud_shadow_mask(cloud_mask, meta["AZIMUTH_ANGLE"], meta["ZENITH_ANGLE"], nir_data, scl_data)
    mask = cloud_mask | bad_mask | cloud_shadow_mask
    
    # add a buffer to the mask
    mask = __buffer_mask(mask)
    
    # apply full mask to stack
    full_mask = stack_data.mask | mask    
    stack_data.mask = full_mask    
    stack_data = stack_data[:-1, :, :]
    stack_data = stack_data.transpose((1, 2, 0))

    write_array_to_tif(stack_data, dst_path, bbox, dtype=np.float32, nodata=NODATA_FLOAT32)
    
    return dst_path


def apply_cloud_mask(stack_tif_path, meta, dst_path, model_path):

    with rasterio.open(stack_tif_path) as src:
        stack_data = src.read(masked=True)
        bbox = list(src.bounds)

    if stack_data.size > 12000000:
        stack_data = __apply_nn_cloud_mask_chunks(stack_data, meta, model_path)
    else:
        stack_data = __apply_nn_cloud_mask(stack_data, meta, model_path)

    stack_data = stack_data.transpose((1, 2, 0))
    write_array_to_tif(stack_data, dst_path, bbox, dtype=np.float32, epsg=4326, nodata=NODATA_FLOAT32)

    # rgb_path = dst_path.replace('.tif', '_rgb.tif')
    # create_rgb_byte_tif_from_composite(dst_path, rgb_path, is_cog=True, use_alpha=False)

    pct_masked = stack_data.mask.sum() / stack_data.mask.size
    return pct_masked < 0.90


def __apply_nn_cloud_mask_chunks(stack_data, meta, model_path):

    dim_index = 1 if stack_data.shape[1] > stack_data.shape[2] else 2

    dim_size = stack_data.shape[dim_index]
    if dim_size % 2 == 1:
        split_index = dim_size // 2 + 1
    else:
        split_index = dim_size // 2

    stack_data_1, stack_data_2 = np.split(stack_data, [split_index], axis=dim_index)

    masked_data_1 = __apply_nn_cloud_mask(stack_data_1, meta, model_path)
    masked_data_2 = __apply_nn_cloud_mask(stack_data_2, meta, model_path)

    masked_data = np.ma.concatenate((masked_data_1, masked_data_2), axis=dim_index)

    return masked_data


def __apply_nn_cloud_mask(stack_data, meta, model_path):

    scl_data = stack_data[-1, :, :]
        
    image = stack_data[:-1, :, :]
    image = image.filled(-1.0) # convert to ndarray and fills masked values with -1.0
    saved_shape = image.shape

    height_pad = 32 - (image.shape[1] % 32)
    width_pad = 32 - (image.shape[2] % 32)
    image = np.pad(image, ((0, 0), (0, height_pad), (0, width_pad)), mode='reflect')
            
    image = np.expand_dims(image, 0)
    image = torch.tensor(image)
        
    model = torch.load(model_path)
    prediction = model.predict(image)
    
    probabilities = torch.sigmoid(prediction).cpu().numpy()
    probabilities = probabilities[0, 0, :, :]
    binary_prediction = (probabilities >= 0.50).astype(bool)
    nn_cloud_mask = binary_prediction[:saved_shape[1], :saved_shape[2]]
    
    scl_cloud_mask = __get_scl_cloud_mask(scl_data)
    cloud_mask = nn_cloud_mask | scl_cloud_mask
    
    # calculate dark pixel masks
    bad_mask = __get_scl_bad_pixel_mask(scl_data)
    cloud_shadow_mask = __get_cloud_shadow_mask(cloud_mask, meta["AZIMUTH_ANGLE"], meta["ZENITH_ANGLE"])
        
    full_mask = cloud_mask | bad_mask | cloud_shadow_mask
    full_mask = __buffer_mask(full_mask, radius=20)
    
    stack_data.mask = full_mask | stack_data.mask 
    stack_data = stack_data[:-1, :, :]
    
    return stack_data
