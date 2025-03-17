#!/bin/sh

db_sleep () {
  while true; do
      sleep 3600
    done
} &> /dev/null

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

# Replace variables in /root/mariadb.sql with vars from ENV (docker file)
sed -i "s/##ENV_MARIA_DB_PASSWORD##/$MARIA_DB_PASSWORD/" /root/mariadb.sql
sed -i "s/##ENV_MARIA_DB_USER##/$MARIA_DB_USER/" /root/mariadb.sql
sed -i "s/##ENV_MARIA_DB_HOST##/$MARIA_DB_HOST/" /root/mariadb.sql
sed -i "s/##ENV_MARIA_DB_DATABASE##/$MARIA_DB_DATABASE/" /root/mariadb.sql

# Execute /root/mariadb.sql
while true; do
    mysql -v < /root/mariadb.sql
    if [ $? -eq 0 ]; then
        break
    fi
    echo "Retrying mysql sql in 5 seconds..."
    sleep 5
done

# Create/Update all databases needed for SiteRM
python3 /usr/local/sbin/dbstart.py

# Process is over, sleep long
db_sleep
