import numpy as np
import rasterio
import torch


from common.constants import LANDCOVER_COLORS
from common.utilities.imagery import write_array_to_tif


    
def apply_landcover_classification(tif_path, dst_path, landcover_model_path):

    with rasterio.open(tif_path) as src:
        data = src.read(masked=True)
        saved_mask = data.mask
        saved_shape = data.shape
        data = data.filled(-1.0)
        bbox = list(src.bounds)

    height_pad = 32 - (data.shape[1] % 32)
    width_pad = 32 - (data.shape[2] % 32)
    padded_data = np.pad(data, ((0, 0), (0, height_pad), (0, width_pad)), mode='reflect')

    image = np.expand_dims(padded_data, 0)     
    image = torch.tensor(image)

    model = torch.load(landcover_model_path)
    prediction = model.predict(image)

    probabilities = torch.sigmoid(prediction)
    prediction = torch.argmax(probabilities, dim=1)

    prediction = (prediction.squeeze().cpu().numpy().round())
    prediction = prediction[:saved_shape[1], :saved_shape[2]]

    prediction = np.ma.array(prediction, mask=saved_mask[0, :, :])
    prediction.mask |= (prediction == 0)
    
    write_array_to_tif(prediction, dst_path, bbox, dtype=np.uint8, epsg=4326, nodata=255)


def calculate_landcover_statistics(landcover_path):

    with rasterio.open(landcover_path) as src:
        prediction = src.read(masked=True)

    statistics = {}
    for idx, info in LANDCOVER_COLORS.items():
        name = info[1]
        class_mask = (prediction == idx)
        statistics[name] = {
            "area_ha": np.sum(class_mask) * 0.01, # 100 m2 = 0.01 ha
            "percent_total": np.sum(class_mask) / prediction.data.size,
            "percent_masked": np.sum(class_mask) / prediction.count()   
        }

    return statistics
