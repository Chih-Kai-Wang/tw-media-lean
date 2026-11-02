#!/bin/sh
# Pull the historical backfill from the cloud VM into this machine's data/.
# The VM runs `twmedia history --wayback skip` as a systemd service. Its name, zone, project and gcloud
# configuration come from .env (TWM_VM_NAME, TWM_VM_ZONE, TWM_GCP_PROJECT, TWM_GCLOUD_CONFIG).
# Its hist_* files and history tables are a superset of what was copied to it, so they replace ours.
# The Wayback part runs here instead (hist_*_wb, scripts/history.sh) and is left untouched.
#   scripts/vm_sync.sh
set -e
cd "$(dirname "$0")/.."
set -a; . ./.env; set +a
G="gcloud --configuration=$TWM_GCLOUD_CONFIG"
VM="$TWM_VM_NAME --zone=$TWM_VM_ZONE --project=$TWM_GCP_PROJECT --quiet"
TMP=$(mktemp -d)

$G compute ssh $VM --command='cd tw-media-lean && rm -f /tmp/hist.tgz /tmp/hist.sqlite &&
  sqlite3 data/state.sqlite ".backup /tmp/hist.sqlite" &&
  tar -czf /tmp/hist.tgz data/raw/hist_* data/cache /tmp/hist.sqlite 2>/dev/null; ls -la /tmp/hist.tgz'
$G compute scp "$TWM_VM_NAME:/tmp/hist.tgz" "$TMP/" --zone="$TWM_VM_ZONE" --project="$TWM_GCP_PROJECT" --quiet
tar -xzf "$TMP/hist.tgz" -C "$TMP"
mkdir -p data/raw data/cache
for d in "$TMP"/data/raw/hist_*; do case "$d" in *_wb) ;; *) cp -R "$d" data/raw/ ;; esac; done
cp -R "$TMP"/data/cache/. data/cache/ 2>/dev/null || true
sqlite3 data/state.sqlite "
  ATTACH '$TMP/tmp/hist.sqlite' AS vm;
  CREATE TABLE IF NOT EXISTS history_progress (source TEXT, month TEXT, political INT, attempts INT, PRIMARY KEY (source, month));
  CREATE TABLE IF NOT EXISTS history_anchor (source TEXT, stream INT, day TEXT, id INT);
  BEGIN;
  DELETE FROM seen WHERE source LIKE 'hist_%' AND source NOT LIKE '%\_wb' ESCAPE '\';
  INSERT INTO seen SELECT * FROM vm.seen WHERE source LIKE 'hist_%' AND source NOT LIKE '%\_wb' ESCAPE '\';
  DELETE FROM history_progress WHERE source NOT LIKE '%\_wb' ESCAPE '\';
  INSERT INTO history_progress SELECT * FROM vm.history_progress WHERE source NOT LIKE '%\_wb' ESCAPE '\';
  DELETE FROM history_anchor WHERE source NOT LIKE '%\_wb' ESCAPE '\';
  INSERT INTO history_anchor SELECT * FROM vm.history_anchor WHERE source NOT LIKE '%\_wb' ESCAPE '\';
  COMMIT;
  SELECT 'political articles so far: ' || SUM(political) FROM history_progress;"
rm -rf "$TMP"
