#!/bin/sh

echo "${EAG_CRON_SCHEDULE:-0 0 * * *} /usr/src/app/sync.sh" | crontab -
/usr/src/app/sync.sh
exec "$@"
