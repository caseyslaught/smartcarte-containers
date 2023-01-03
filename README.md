# Smart Carte | Containers and Notebooks

### The containers are run on AWS Lambda.

### Each folder in _containers_ corresponds to a Lambda function.

### Each Lambda function is run on a custom Docker container.

### Jupyter Notebooks run on a Docker container locally.

## Set up

### 1. Go into each container function

`cd containers/monolith'`

### 2. Build the Docker containers

- #### Jupyter

  `docker build ./notebooks/ -t sc_jupyter:latest`

- #### Monolith
  `docker build ./containers/monolith/ -t sc_monolith:latest`

### 3. Start Jupyter Notebooks container

`docker run ... 0.0.0.0:8888 ???`

## Debugging

`docker run -p 9000:8080 -v %cd%/src:/var/task/src sc_monolith:latest`

Invoke HTTP request with Postman (Smart Carte/containers/monolith) or...

`curl -XPOST "http://localhost:9000/2015-03-31/functions/function/invocations" -d {}`

Stop container and restart run _docker run..._ again after code changes

Or run functions directly from Docker command line after starting with docker run above...
`cd /var/task`
`python -c "from src.common.utilities.imagery import _debug; _debug()"`

## Miscellaneous

### Prune dangling images

`docker image prune`
