# Smart Carte | Containers and Notebooks

### The containers are run on AWS Fargate in us-west-2 in order to be co-located with Sentinel-2 COGs.

### Each folder in _containers_ corresponds to a Fargate task.

## Building

`docker build ./containers/monolith/ -t sc_monolith:latest`
`docker build ./notebooks -t sc_notebook:latest`

## Debugging

### Monolith

`docker run -it --entrypoint /bin/bash -v %cd%/src:/var/task/src sc_monolith:latest`
`docker run -it --entrypoint /bin/bash -v %cd%/src:/var/task/src -v %cd%/tmp:/tmp sc_monolith:latest`
`python handler.py`

### Notebook

#### make sure in notebooks/

`docker run -p 8888:8888 -v %cd%/src:/home/src -v %cd%/data:/home/src/data sc_notebook:latest`

## Deploying everything to ECS

Tag the image, login, upload the image to ECR, update ECS service - every time.

`docker build . -t sc_monolith:latest`
`docker tag sc_monolith 981763725120.dkr.ecr.us-west-2.amazonaws.com/sc_monolith:latest`
`aws ecr get-login-password --region us-west-2 --profile smartcarte | docker login -u AWS --password-stdin 981763725120.dkr.ecr.us-west-2.amazonaws.com`
`docker push 981763725120.dkr.ecr.us-west-2.amazonaws.com/sc_monolith:latest`
`aws ecs update-service --profile smartcarte --cluster default --service sc-monolith-service --force-new-deployment --region us-west-2`

## Miscellaneous

### Prune dangling images

`docker image prune`

### Copy a file from Docker container to host

`docker cp hardcore_chandrasekhar:/tmp/before/S2A_35MRU_20210825_0_L2A/B02_masked.tif C:\Users\casey\Desktop\B02_masked.tif`  
`docker cp admiring_khorana:/tmp/before/tiles C:\Users\casey\Work\SmartCarteContainers\tiles`
`docker cp hardcore_chandrasekhar:/tmp C:\Users\casey\Work\SmartCarteContainers\tmp`

### Location of _src_ directory

/var/task

### Create Slippy tiles

gdalbuildvrt -separate RGB.vrt B04_composite.tif B03_composite.tif B02_composite.tif
gdal_translate -of VRT -ot Byte -scale RGB.vrt RGB_Byte.vrt
gdal2tiles.py --zoom=2-14 --exclude RGB_Byte.vrt tiles/

--- right now the output RGB VRT is really dark
--- maybe when it gets scaled to byte (255) it loses something
or the remaining clouds are taking up all the high values
