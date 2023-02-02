cd C:\Users\casey\Work\SmartCarteContainers\containers\monolith
docker run -it --entrypoint /bin/bash -v %cd%/src:/var/task/src -v %cd%/tmp:/tmp --env-file .env sc_monolith:latest