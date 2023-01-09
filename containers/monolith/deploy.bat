docker build . -t sc_monolith:latest
docker tag sc_monolith 981763725120.dkr.ecr.us-west-2.amazonaws.com/sc_monolith:latest
aws ecr get-login-password --region us-west-2 --profile smartcarte | docker login -u AWS --password-stdin 981763725120.dkr.ecr.us-west-2.amazonaws.com
docker push 981763725120.dkr.ecr.us-west-2.amazonaws.com/sc_monolith:latest
aws ecs update-service --profile smartcarte --cluster default --service sc-monolith-service --force-new-deployment --region us-west-2