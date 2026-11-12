#!/bin/sh
# Runs ONCE, when the mysql_data volume is empty (the MySQL image's first start). It makes:
#   - the data schema (AI_GOLD_DATABASE, default ai_gold) - filled later by the loader service
#   - the app's own schema (APP_DB_NAME: chats, history, users) with its user (all rights there, nowhere else)
#   - the read-only AI user (SELECT on the data schema only)
# The users are made for any host ('%'): the app's containers are not 'localhost' for MySQL. The MySQL port is
# only open inside the compose network (and on 127.0.0.1 of this PC). Names and passwords come from .env.
set -e

GOLD="${AI_GOLD_DATABASE:-ai_gold}"

# a value inside a single-quoted SQL string: \ and ' escaped
quote() { printf '%s' "$1" | sed -e 's/\/\\/g' -e "s/'/''/g"; }
# only letters, digits and _ in a schema or user name
name_ok() { case "$1" in *[!A-Za-z0-9_]*|"") return 1 ;; *) return 0 ;; esac; }

name_ok "$GOLD" || { echo "AI_GOLD_DATABASE has a character that is not allowed"; exit 1; }
SQL="CREATE DATABASE IF NOT EXISTS \`$GOLD\` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"

if [ -n "$APP_DB_NAME" ] && [ -n "$APP_DB_USER" ]; then
    name_ok "$APP_DB_NAME" && name_ok "$APP_DB_USER" || { echo "APP_DB_NAME / APP_DB_USER: a character is not allowed"; exit 1; }
    SQL="$SQL
CREATE DATABASE IF NOT EXISTS \`$APP_DB_NAME\` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS '$APP_DB_USER'@'%' IDENTIFIED BY '$(quote "$APP_DB_PASSWORD")';
GRANT ALL PRIVILEGES ON \`$APP_DB_NAME\`.* TO '$APP_DB_USER'@'%';"
    echo "App schema $APP_DB_NAME with its user $APP_DB_USER"
else
    echo "APP_DB_NAME / APP_DB_USER not set: no app schema (the History then goes to SQLite)"
fi

if [ -n "$AI_DB_USER" ] && [ -n "$AI_DB_PASSWORD" ]; then
    name_ok "$AI_DB_USER" || { echo "AI_DB_USER has a character that is not allowed"; exit 1; }
    SQL="$SQL
CREATE USER IF NOT EXISTS '$AI_DB_USER'@'%' IDENTIFIED BY '$(quote "$AI_DB_PASSWORD")';
GRANT SELECT ON \`$GOLD\`.* TO '$AI_DB_USER'@'%';"
    echo "Read-only AI user $AI_DB_USER: SELECT on $GOLD only"
else
    echo "AI_DB_USER / AI_DB_PASSWORD not set: no read-only AI user (data questions will not work)"
fi

# the statements go in on stdin, so no password shows in the process list or in the log
printf '%s\nFLUSH PRIVILEGES;\n' "$SQL" | MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql --protocol=socket -uroot
