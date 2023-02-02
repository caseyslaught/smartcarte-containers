# Smart Carte | Containers and Notebooks

### The containers are run on AWS Fargate in us-west-2 in order to be co-located with Sentinel-2 COGs.

### Each folder in _containers_ corresponds to a Fargate task.

## Building

`docker build ./containers/monolith/ -t sc_monolith:latest`
`docker build ./notebooks -t sc_notebook:latest`

## Debugging

### Monolith

`docker run -it --entrypoint /bin/bash -v %cd%/src:/var/task/src sc_monolith:latest`
`docker run -it --entrypoint /bin/bash -v %cd%/src:/var/task/src -v %cd%/tmp:/tmp --env-file .env sc_monolith:latest`
`python handler.py`

### Notebook

#### run Jupyter Notebook in browser

`docker run -p 8888:8888 -v %cd%/src:/home/src -v %cd%/data:/home/src/data sc_notebook:latest`

#### develop with VSCode

`docker run -p 8888:8888 -it --entrypoint /bin/bash -v %cd%/src:/home/src -v %cd%/data:/home/src/data sc_notebook:latest`
`startJupyter.bat` or `startBash.bat`

- Then click the button in very bottom right and click _Attach to running container_
- Then develop in the new container that pops up.

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
