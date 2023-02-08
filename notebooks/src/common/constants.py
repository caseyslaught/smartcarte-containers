
DAYS_BUFFER = 70

MAX_CLOUD_COVER = 50

NODATA_BYTE = 0 # 255
NODATA_FLOAT32 = -9999
NODATA_FLOAT64 = -9999
NODATA_INT8 = 0 # 127
NODATA_UINT16 = 0 # 65535

S2_BANDS = ['SCL', 'B02', 'B03', 'B04', 'B08', 'B8A'] # make sure SCL first
S2_BANDS_TIFF_ORDER = ['B02', 'B03', 'B04', 'B08', 'B8A', 'SCL'] # make sure SCL last

S3_DATA_BUCKET = 'smartcarte-data'
S3_TASKS_BUCKET = 'smartcarte-tasks'

DATA_CDN_BASE_URL = 'https://data.smartcarte.earth'
