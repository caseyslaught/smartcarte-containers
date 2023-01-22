from datetime import datetime as dt
from datetime import timedelta as td
from matplotlib import pyplot as plt
import os
import rasterio
from shapely.geometry import shape
import sys

from common import exceptions
from common.constants import DAYS_BUFFER
from common.utilities import api, download, imagery, indices, prediction, upload



def _plot_and_save(data, image_path, task_uid, subdir):
    plt.imshow(data, cmap="RdYlGn")
    plt.savefig(image_path)
    plt.clf()
    upload.save_task_file_to_s3(image_path, subdir, task_uid)


def handle():

    print(sys.argv)
    #task_uid = sys.argv[1]
    #task_type = sys.argv[2]

    task_uid = "c65c1f3a-ff8d-4c80-be9f-04355de64fa4"
    task_type = "forest_change"

    base_dir = f"/tmp/{task_uid}"

    print("task_uid:", task_uid)
    print("task_type:", task_type)

    api.update_task_status(task_uid, task_type, "running")

    if task_type == "forest_change":

        # prepare directories

        os.makedirs(f'{base_dir}/before', exist_ok=True)
        os.makedirs(f'{base_dir}/after', exist_ok=True)
        os.makedirs(f'{base_dir}/results', exist_ok=True)


        # prepare parameters

        params = api.get_forest_change_task_params(task_uid)

        start_date_end = dt.strptime(params['start_date'], '%Y-%m-%d')
        start_date_begin = start_date_end - td(days=DAYS_BUFFER)

        end_date_end = dt.strptime(params['end_date'], '%Y-%m-%d')
        end_date_begin = end_date_end - td(days=DAYS_BUFFER)

        geojson = params['region']['geojson']
        if geojson['type'] == 'FeatureCollection':
            region = shape(geojson['features'][0]['geometry'])
        elif geojson['type'] == 'Polygon':
            region = shape(geojson)
        else:
            raise ValueError("invalid geojson type") # TODO: figure out proper logging!

        bbox = region.bounds

        print("bbox:", bbox)


        # get collections

        try:
            start_collection = download.get_collection(start_date_begin, start_date_end, bbox, "before", max_cloud_cover=30)
        except exceptions.EmptyCollectionException:
            print("before collection is empty")
            api.update_task_status(task_uid, task_type, "failed")
            return

        try:
            after_collection = download.get_collection(end_date_begin, end_date_end, bbox, "after", max_cloud_cover=24)
        except exceptions.EmptyCollectionException:
            print("after collection is empty")
            api.update_task_status(task_uid, task_type, "failed")
            return 


        ### prepare imagery ###
        
        # before

        before_composites = download.get_processed_imagery(start_collection, bbox, "before")
        before_all_band_paths = list(before_composites.values())
        before_rgb_band_paths = [before_composites['B04'], before_composites['B03'], before_composites['B02']]
        
        before_all_uint16_vrt_path = f'{base_dir}/before/all_uint16.vrt'
        imagery.create_vrt(before_all_band_paths, before_all_uint16_vrt_path)

        before_all_uint16_cog_path = f'{base_dir}/before/all_uint16_cog.tif'
        imagery.create_tif(before_all_uint16_vrt_path, before_all_uint16_cog_path, isCog=True)

        before_rgb_uint16_vrt_path = f'{base_dir}/before/rgb_uint16.vrt'
        imagery.create_vrt(before_rgb_band_paths, before_rgb_uint16_vrt_path)

        before_rgb_byte_vrt_path = f'{base_dir}/before/rgb_byte.vrt'
        imagery.create_byte_vrt(before_rgb_uint16_vrt_path, before_rgb_byte_vrt_path)

        before_rgb_byte_cog_path = f'{base_dir}/before/rgb_byte_cog.tif'
        imagery.create_tif(before_rgb_byte_vrt_path, before_rgb_byte_cog_path, isCog=True)

        before_tiles_dir = f'{base_dir}/before/rgb_byte_tiles'
        imagery.create_map_tiles(before_rgb_byte_vrt_path, before_tiles_dir)



        # after

        after_composites = download.get_processed_imagery(after_collection, bbox, "after")
        after_all_band_paths = list(after_composites.values())
        after_rgb_band_paths = [after_composites['B04'], after_composites['B03'], after_composites['B02']]

        after_all_uint16_vrt_path = f'{base_dir}/after/all_uint16.vrt'
        imagery.create_vrt(after_all_band_paths, after_all_uint16_vrt_path)

        after_all_uint16_cog_path = f'{base_dir}/after/all_uint16_cog.tif'
        imagery.create_tif(after_all_uint16_vrt_path, after_all_uint16_cog_path, isCog=True)

        after_rgb_uint16_vrt_path = f'{base_dir}/after/rgb_uint16.vrt'
        imagery.create_vrt(after_rgb_band_paths, after_rgb_uint16_vrt_path)

        after_rgb_byte_vrt_path = f'{base_dir}/after/rgb_byte.vrt'
        imagery.create_byte_vrt(after_rgb_uint16_vrt_path, after_rgb_byte_vrt_path)

        after_rgb_byte_cog_path = f'{base_dir}/after/rgb_byte_cog.tif'
        imagery.create_tif(after_rgb_byte_vrt_path, after_rgb_byte_cog_path, isCog=True)

        after_tiles_dir = f'{base_dir}/after/rgb_byte_tiles'
        imagery.create_map_tiles(after_rgb_byte_vrt_path, after_tiles_dir)


        ### upload assets to S3 ###

        upload.save_task_file_to_s3(before_rgb_byte_cog_path, "before", task_uid)
        upload.save_task_file_to_s3(before_all_uint16_cog_path, "before", task_uid)

        upload.save_task_file_to_s3(after_rgb_byte_cog_path, "after", task_uid)
        upload.save_task_file_to_s3(after_all_uint16_cog_path, "after", task_uid)

        upload.save_task_tiles_to_s3(before_tiles_dir, "before", task_uid)
        upload.save_task_tiles_to_s3(after_tiles_dir, "after", task_uid)



        ### feature engineering ###

        # NDVI

        before_ndvi_path = f'{base_dir}/before/ndvi.tif'
        indices.create_ndvi(before_composites['B04'], before_composites['B08'], before_ndvi_path)
        before_composites['NDVI'] = before_ndvi_path

        after_ndvi_path = f'{base_dir}/after/ndvi.tif'
        indices.create_ndvi(after_composites['B04'], after_composites['B08'], after_ndvi_path)
        after_composites['NDVI'] = after_ndvi_path



        ### model predictions ###

        before_prediction_path = f'{base_dir}/before/forest.tif'
        prediction.predict_forest(before_composites, before_prediction_path)

        after_prediction_path = f'{base_dir}/after/forest.tif'
        prediction.predict_forest(after_composites, after_prediction_path)

        change_path = f'{base_dir}/results/change.tif'
        prediction.predict_forest_change(before_prediction_path, after_prediction_path, change_path)

        change_tiles_dir = f'{base_dir}/results/change_tiles'
        imagery.create_map_tiles(after_rgb_byte_vrt_path, after_tiles_dir)


        


        # TODO: create tiles for change



        # TODO: save and upload...


        ### update task in database ###

        api.update_forest_change_task_results(task_uid, 100, 80, 520)

        # TODO: update paths to COGs and tiles dir


    elif task_type == "burn_areas":
        pass

    elif task_type == "lulc_change":
        pass

    else:
        raise ValueError()


    # update status

    api.update_task_status(task_uid, task_type, "complete")



if __name__ == "__main__":
    handle()

