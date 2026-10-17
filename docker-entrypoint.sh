#!/bin/sh
# The volume is often root-owned. Make it writable, then drop privileges.
set -e
mkdir -p /data/clips /data/reels /data/posters /data/logs /data/bumpers /data/runs
if [ "$(id -u)" = "0" ]; then
  chown -R vidrot:vidrot /data
  exec runuser -u vidrot -- python console/server.py
fi
exec python console/server.py
