#!/bin/sh
mkdir -p "$(pwd)/opt/mysql/"
docker run \
  -dit --name end-to-end-tester \
  -v "$(pwd)/../:/opt/code/:rw" \
  -v "$(pwd)/opt/end-to-end-tester/:/opt/end-to-end-tester/" \
  -v "/Users/jbalcas/.sense-o-auth.yaml:/etc/sense-o-auth.yaml:ro" \
  -v "$(pwd)/endtoend-test-l3.yaml:/etc/endtoend.yaml:ro" \
  --restart always \
  --env-file endtoend-environment \
  sdnsense/sense-endtoend:dev
