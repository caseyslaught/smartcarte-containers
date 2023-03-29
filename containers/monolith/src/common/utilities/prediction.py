import numpy as np
import rasterio


from common.constants import NODATA_BYTE
from common.utilities.imagery import write_array_to_tif


    
LANDCOVER_COLORS = {
    1: [(156, 212, 255), "clouds"],
    2: [(158, 158, 145), "bare_ground"],
    3: [(176, 5, 31), "built"],
    4: [(19, 92, 46), "trees"],
    5: [(209, 135, 8), "burned"],
    6: [(63, 204, 82), "semi_natural_vegetation"],
    7: [(217, 195, 0), "agriculture"],
    8: [(6, 124, 214), "water"]
}


def apply_landcover_classification(tif_path, dst_path):

    with rasterio.open(tif_path) as src:
        data = src.read(masked=True)
        saved_mask = data.mask
        data = og_image.filled(-1.0)
        saved_shape = data.shape
        bbox = list(src.bounds)

    height_pad = 32 - (data.shape[1] % 32)
    width_pad = 32 - (data.shape[2] % 32)
    padded_data = np.pad(data, ((0, 0), (0, height_pad), (0, width_pad)), mode='reflect')

    image = np.expand_dims(padded_data, 0)     
    image = torch.tensor(image)

    model = torch.load(model_path)

    prediction = model.predict(image)

    probabilities = torch.sigmoid(prediction)
    prediction = torch.argmax(probabilities, dim=1)

    prediction = (prediction.squeeze().cpu().numpy().round())
    prediction = np.ma.array(prediction, mask=(prediction==0))

    og_image = og_image[:, :saved_shape[1], :saved_shape[2]]
    prediction = prediction[:saved_shape[1], :saved_shape[2]]
    
    prediction = np.ma(prediction, mask=saved_mask)
    prediction.mask |= (prediction == 0)
    prediction.mask |= (prediction == 1)
    
    write_array_to_tif(prediction, dst_path, bbox, dtype=np.uint8, epsg=4326, nodata=255)
    
    statistics = {}
    colored_landcover = np.zeros((prediction.shape[0], prediction.shape[1], 3), dtype=np.uint8)
    for idx, info in LANDCOVER_COLORS.items():
        rgb, name = info
        mask = (prediction == idx)
        colored_landcover[mask] = rgb
        statistics[name] = {
            "area_ha": np.sum(mask) * 0.01, # 100 m2 = 0.01 ha
            "percent_total": np.sum(mask) / prediction.data.size,
            "percent_masked": np.sum(mask) / prediction.count()   
        }

    prediction_color_path = f'{base_dir}/prediction_color.tif'
    write_array_to_tif(prediction, prediction_color_path, bbox_sb, dtype=np.uint8, epsg=4326, nodata=255)
    
    return statistics