cd C:\Users\casey\Work\SmartCarteContainers\notebooks
docker run -p 8888:8888 -v %cd%/src:/home/src -v %cd%/data:/home/src/data sc_notebook:latest