#!/bin/sh

# Check if all env variables are available and set
if [[ -z $MARIA_DB_HOST || -z $MARIA_DB_USER || -z $MARIA_DB_DATABASE || -z $MARIA_DB_PASSWORD || -z $MARIA_DB_PORT ]]; then
  if [ -f "/etc/endtoend-mariadb" ]; then
    set -a
    source /etc/endtoend-mariadb
    set +a
    env
  else
    echo 'DB Configuration file not available. exiting.'
    exit 1
  fi
fi

# Overwrite MariaDB port if it is not default 3306
if [[ "$MARIA_DB_PORT" != "3306" && -n "$MARIA_DB_PORT" ]]; then
    cp /etc/my.cnf.d/server.cnf /etc/my.cnf.d/server.cnf.bak
    if grep -q "^port=" /etc/my.cnf.d/server.cnf; then
        echo "MariaDB Port is already defined in /etc/my.cnf.d/server.cnf"
    else
        echo "port=${MARIA_DB_PORT}" >> /etc/my.cnf.d/server.cnf
        echo "Port ${MARIA_DB_PORT} added to /etc/my.cnf.d/server.cnf."
    fi
fi

# Clean up any stale lock files
rm -f /opt/end-to-end-tester/mysql/ibtmp1
rm -f /opt/end-to-end-tester/mysql/aria_log.*
rm -f /opt/end-to-end-tester/mysql/*.pid

if [ ! -f /opt/end-to-end-tester/mysql/db-initialization ]; then
  # First time start of mysql, ensure dirs are present
  mkdir -p /opt/end-to-end-tester/mysql/
  mkdir -p /var/log/mariadb
  chown -R mysql:mysql /opt/end-to-end-tester/mysql/
  chown mysql:mysql /var/log/mariadb

  # Initialize the mysql data directory and create system tables
  mysql_install_db --user mysql > /dev/null
else
  echo "Seems this is not the first time start."
  chown -R mysql:mysql /opt/end-to-end-tester/mysql/
fi

# Start MariaDB in the foreground using exec
exec mysqld_safe --user=mysql
