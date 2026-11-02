#!/bin/zsh
# One collection pass; called hourly by launchd (scripts/tw.twmedia.collect.plist).
set -euo pipefail
cd "${0:A:h}/.."
mkdir -p data/logs
exec "$HOME/.local/bin/uv" run twmedia collect >> "data/logs/collect-$(date +%Y-%m).log" 2>&1
