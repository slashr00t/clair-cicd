#!/usr/bin/env bash
#
# this script automates the process of building a postgress docker
# image that runs postgres and contains a fully populated database
# of current vulnerabilities.
#

TAG=latest

while true
do
    case "${1,,}" in
        -t)
            shift
            TAG=${1:-latest}
            shift
            ;;
        *)
            break
            ;;
    esac
done

if [ $# != 1 ] && [ $# != 2 ]; then
    echo "usage: $(basename "$0") [-t <tag>] <dockerhub-username> [<dockerhub-password>]" >&2
    exit 1
fi

DOCKERHUB_USERNAME=${1:-}
DOCKERHUB_PASSWORD=${2:-}

CLAIR_DATABASE_IMAGE_NAME=$DOCKERHUB_USERNAME/clair-database:$TAG
# https://quay.io/repository/coreos/clair?tab=tags
CLAIR_BRANCH=v1.2.2
CLAIR_IMAGE_NAME=quay.io/coreos/clair:$CLAIR_BRANCH
CLAIR_CONTAINER_NAME=clair-$(openssl rand -hex 8)
CLAIR_DATABASE_CONTAINER_NAME=clair-database-$(openssl rand -hex 8)

DATABASE_SERVER_DOCKER_IMAGE=postgres:9.5.2

echo "pulling database server docker image $DATABASE_SERVER_DOCKER_IMAGE"

if ! docker pull $DATABASE_SERVER_DOCKER_IMAGE >& /dev/null; then
    echo "error pulling database server docker image $DATABASE_SERVER_DOCKER_IMAGE" >&2
    exit 1
fi

echo "successfully pulled database server docker image"

echo "starting database server container '$CLAIR_DATABASE_CONTAINER_NAME'"
docker \
    run \
    --name "$CLAIR_DATABASE_CONTAINER_NAME" \
    -e 'PGDATA=/var/lib/postgresql/data-non-volume' \
    -d \
    $DATABASE_SERVER_DOCKER_IMAGE \
    > /dev/null
echo "successfully started database server container"

echo -n "waiting for database server in container '$CLAIR_DATABASE_CONTAINER_NAME' to start "
for i in $(seq 1 10)
do
    if ! docker logs "$CLAIR_DATABASE_CONTAINER_NAME" |& grep "database system is ready to accept connections" > /dev/null; then
        break
    fi
    echo -n "."
    sleep 3
done
echo ''

echo "successfully started database server from docker image '$DATABASE_SERVER_DOCKER_IMAGE'"

echo "creating database"

MAX_NUM_DATABASE_CREATE_ATTEMPTS=10
for i in $(seq 1 $MAX_NUM_DATABASE_CREATE_ATTEMPTS)
do
    docker \
        exec \
        "$CLAIR_DATABASE_CONTAINER_NAME" \
        sh -c 'echo "create database clair" | psql -U postgres' \
        >& /dev/null

    if docker \
        exec \
         "$CLAIR_DATABASE_CONTAINER_NAME" \
         sh -c 'echo "\list" | psql -U postgres' |& \
         grep '^\s*clair' \
         >& /dev/null;
    then
         break
    fi

    sleep 3
done
if [ "$i" == "$MAX_NUM_DATABASE_CREATE_ATTEMPTS" ]; then
    echo "error creating database" >&2
    exit 1
fi

echo "successfully created database"

#
# get clair running
#
echo "pulling clair image '$CLAIR_IMAGE_NAME'"
if ! docker pull $CLAIR_IMAGE_NAME > /dev/null; then
    echo "error pulling clair image '$CLAIR_IMAGE_NAME'" >&2
    exit 1
fi
echo "pulled clair image '$CLAIR_IMAGE_NAME'"

#
# create clair configuration that will point clair @ the database we just created
#
CLAIR_CONFIG_DIR=$(mktemp -d 2> /dev/null || mktemp -d -t DAS)
CLAIR_CONFIG_YAML=$CLAIR_CONFIG_DIR/config.yaml

echo "creating clair configuration @ '$CLAIR_CONFIG_YAML'"

curl \
    -s \
    -o "$CLAIR_CONFIG_YAML" \
    -L \
    https://raw.githubusercontent.com/coreos/clair/$CLAIR_BRANCH/config.example.yaml

# postgres connection string details
# http://www.postgresql.org/docs/9.5/static/libpq-connect.html#LIBPQ-CONNSTRING
sed \
    -i \
    -e 's|source:|source: postgresql://postgres@clair-database:5432/clair?sslmode=disable|g' \
    "$CLAIR_CONFIG_YAML"

echo "created clair configuration"

echo "creating clair container '$CLAIR_CONTAINER_NAME'"
if ! docker \
    run \
    -d \
    --name "$CLAIR_CONTAINER_NAME" \
    --link "$CLAIR_DATABASE_CONTAINER_NAME":clair-database \
    -v /tmp:/tmp \
    -v "$CLAIR_CONFIG_DIR":/config \
    "$CLAIR_IMAGE_NAME" \
    -config=/config/config.yaml \
    > /dev/null;
then
    echo "error creating clair container '$CLAIR_CONTAINER_NAME'" >&2
    exit 1
fi
echo "successfully created clair container"

echo -n "waiting for vulnerabilities database update to finish "
while true
do
    if docker logs "$CLAIR_CONTAINER_NAME" | grep "updater: update finished" >& /dev/null; then
        break
    fi

    if docker logs "$CLAIR_CONTAINER_NAME" | grep "updater: an error occured" >& /dev/null; then
        echo ""
        echo "error during vulnerabilities database update" >&2
        exit 1
    fi

    echo -n "."
    sleep 15
done
echo ""

docker kill "$CLAIR_CONTAINER_NAME" > /dev/null
docker rm "$CLAIR_CONTAINER_NAME" > /dev/null

docker rmi "$CLAIR_DATABASE_IMAGE_NAME" >& /dev/null

docker \
    commit \
    --change 'ENV PGDATA /var/lib/postgresql/data-non-volume' \
    --change='CMD ["postgres"]' \
    --change='EXPOSE 5432' \
    --change='ENTRYPOINT ["/docker-entrypoint.sh"]' \
    "$CLAIR_DATABASE_CONTAINER_NAME" \
    "$CLAIR_DATABASE_IMAGE_NAME" \
    > /dev/null

if [ "$DOCKERHUB_PASSWORD" != "" ]; then
    echo "logging in to dockerhub"
    docker login --username="$DOCKERHUB_USERNAME" --password="$DOCKERHUB_PASSWORD"
    echo "logged in to dockerhub"

    echo "pushing vulnerabilities database ($CLAIR_DATABASE_IMAGE_NAME) to dockerhub"
    docker push "$CLAIR_DATABASE_IMAGE_NAME" > /dev/null
    echo "pushed vulnerabilities database to dockerhub"
fi

docker kill "$CLAIR_DATABASE_CONTAINER_NAME" > /dev/null
docker rm "$CLAIR_DATABASE_CONTAINER_NAME" > /dev/null

echo "done!"

exit 0
