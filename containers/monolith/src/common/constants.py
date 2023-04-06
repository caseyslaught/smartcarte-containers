
DAYS_BUFFER = 80

MAX_CLOUD_COVER = 80

NODATA_BYTE = 255
NODATA_FLOAT32 = -9999

S2_BANDS_TIFF_ORDER = ['B02', 'B03', 'B04', 'B08', 'SCL'] # make sure SCL last

S3_DATA_BUCKET = 'smartcarte-data'

API_BASE_URL = 'https://api.smartcarte.earth'

DATA_CDN_BASE_URL = 'https://data.smartcarte.earth'

LANDCOVER_COLORS = {
    1: [(6, 124, 214), "water"],
    2: [(176, 5, 31), "bare_artificial"],
    3: [(158, 158, 145), "bare_natural"],
    4: [(205, 221, 247), "snow_ice"],
    5: [(19, 92, 46), "woody"],
    6: [(217, 195, 10), "cultivated"],
    7: [(63, 204, 82), "semi_natural_vegetation"],
}
