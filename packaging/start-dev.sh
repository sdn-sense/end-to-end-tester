#!/bin/sh
mkdir -p "$(pwd)/opt/mysql/"
docker run \
  -dit --name end-to-end-tester \
  -v "$(pwd)/../:/opt/code/:rw" \
  -v "$(pwd)/opt/end-to-end-tester/:/opt/end-to-end-tester/" \
  -v ~/.sense-o-auth.yaml:/root/.sense-o-auth.yaml:ro" \
  -v "$(pwd)/endtoend.yaml:/etc/endtoend.yaml:ro" \
  --restart always \
  --env-file endtoend-environment \
  end-to-end-tester
