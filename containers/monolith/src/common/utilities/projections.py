from functools import partial
import pyproj
from shapely.ops import transform as shapely_transform



def reproject_shape(polygon, init_proj, target_proj):
    """
    EPSG: 4326, World Geodetic System 1984, degrees
    EPSG: 3857, Pseudo-Mercator / Google Maps, meters
    """

    init_crs = pyproj.CRS(init_proj)
    target_crs = pyproj.CRS(target_proj)
    project = pyproj.Transformer.from_crs(init_crs, target_crs, always_xy=True).transform

    return shapely_transform(project, polygon)
