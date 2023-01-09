# Smart Carte | Containers and Notebooks

### The containers are run on AWS Fargate in us-west-2 in order to be co-located with Sentinel-2 COGs.

### Each folder in _containers_ corresponds to a Fargate task.

## Building

`docker build ./containers/monolith/ -t sc_monolith:latest`

## Debugging

`docker run -it --entrypoint /bin/bash -v %cd%/src:/var/task/src sc_monolith:latest`
`python handler.py`

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

`docker cp hardcore_keller:/tmp/before/S2A_35MRU_20210825_0_L2A/B02_masked.tif C:\Users\casey\Desktop\B02_masked.tif`  
`docker cp hardcore_keller:/tmp/before/B08_composite.tif C:\Users\casey\Desktop\B08_composite.tif`

### Location of _src_ directory

/var/task
