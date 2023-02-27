import numpy as np
import pyproj
from shapely.geometry import box, shape
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


def get_collection_bbox_coverage(collection, bbox):

    collection_poly_ea = None
    for item in collection:
        item_ll = shape(item.geometry)
        item_ea = reproject_shape(item_ll, "EPSG:4326", "EPSG:3857")

        if collection_poly_ea is None:
            collection_poly_ea = item_ea
        else:
            collection_poly_ea = collection_poly_ea.union(item_ea)

    bbox_poly_ll = box(*bbox)    
    bbox_poly_ea = reproject_shape(bbox_poly_ll, "EPSG:4326", "EPSG:3857")

    intersection_poly_ea = bbox_poly_ea.intersection(collection_poly_ea)
    intersection_pct = (intersection_poly_ea.area * 100) / bbox_poly_ea.area

    return np.around(intersection_pct)

