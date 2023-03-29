
DAYS_BUFFER = 90

MAX_CLOUD_COVER = 80

NODATA_BYTE = 255
NODATA_FLOAT32 = -9999

S2_BANDS_TIFF_ORDER = ['B02', 'B03', 'B04', 'B08', 'SCL'] # make sure SCL last

S3_DATA_BUCKET = 'smartcarte-data'

API_BASE_URL = 'https://api.smartcarte.earth'

DATA_CDN_BASE_URL = 'https://data.smartcarte.earth'

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