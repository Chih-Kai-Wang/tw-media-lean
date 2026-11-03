#!/bin/sh
# Historical backfill, detached from the terminal.
# Resumable: progress lives in data/state.sqlite, so just run it again after a reboot.
#   nohup scripts/history.sh >/dev/null 2>&1 &
# Since 2026-11-02 the outlets' own sites are sampled on the cloud VM (`--wayback skip`; scripts/vm_sync.sh
# pulls that data back). web.archive.org refuses cloud IPs, so this machine does only the Wayback part, under
# separate source names (hist_<outlet>_wb). Never run the non-Wayback part here while the VM runs.
cd "$(dirname "$0")/.." || exit 1
mkdir -p data/logs
# Liberty Times refuses data-centre IPs, so it is sampled from here too (1 request/s, like everywhere else).
( for pass in $(seq 1 48); do
    uv run twmedia history ltn --first 2012-01 --last 2026-09 --per-month 300 >> data/logs/history-ltn.log 2>&1
    sleep 1800
  done ) &
# A pass ends when every month is full or has failed 20 times (the CDX index is often down): rest, then retry.
for pass in $(seq 1 48); do
  uv run twmedia history cna udn ftv mirror --wayback only \
    --first 2012-01 --last 2026-09 --per-month 300 >> data/logs/history-wayback.log 2>&1
  sleep 1800
done
