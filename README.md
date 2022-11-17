# Smart Carte | Lambda Containers

### These containers are run on AWS Lambda.

### Each folder in _containers_ corresponds to a Lambda function.

### Each Lambda function is run on a custom Docker container.

## Set up

### 1. Go into each container function

`cd containers/monolith'`

### 2. Create a Python virtual environment?

`py -m venv venv`

### 3. Build the Docker containers

`docker build ./containers/monolith/ --build-arg VERSION=2.1.0 --build-arg PYVERSION=3.9.13 -t sc_monolith:latest`
