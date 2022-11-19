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
