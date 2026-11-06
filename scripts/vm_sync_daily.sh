#!/bin/sh
# Run scripts/vm_sync.sh at most once a day. launchd calls this hourly (scripts/tw.twmedia.vmsync.plist), so a sync
# missed while offline or asleep is retried the next hour, while network egress from the VM stays at one copy a day.
cd "$(dirname "$0")/.."
export PATH="$HOME/google-cloud-sdk/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
STAMP=data/logs/vm_sync.last
mkdir -p data/logs
if [ -f "$STAMP" ] && [ $(( $(date +%s) - $(cat "$STAMP") )) -lt 72000 ]; then exit 0; fi  # synced in the last 20 h
if scripts/vm_sync.sh >> data/logs/vm_sync.log 2>&1; then
  date +%s > "$STAMP"
  echo "$(date '+%F %T') ok" >> data/logs/vm_sync.log
else
  echo "$(date '+%F %T') failed, retrying next hour" >> data/logs/vm_sync.log
fi
