#!/usr/bin/env bash
# 429-wait: wait out an LLM/agent usage limit, then optionally resume work.
#
# Usage:
#   429-wait.sh --probe "claude -p ping" [--interval 1800] [--max-attempts 48] \
#                  [--resume "claude --continue -p continue"] [--tag default] \
#                  [--state-dir ~/.429-wait]
#
# While the probe exits non-zero or prints something matching the limit
# pattern, sleep and retry. On success: run --resume (if given) and exit 0.

set -u
PROBE=""
RESUME=""
INTERVAL=1800
MAX=48
TAG="default"
STATE_DIR="${HOME}/.429-wait"
PATTERN='usage limit|hit.*limit|rate.?limit|quota|429|403|overloaded|exceeded'

while [ $# -gt 0 ]; do
  case "$1" in
    --probe)        PROBE="$2"; shift 2;;
    --resume)       RESUME="$2"; shift 2;;
    --interval)     INTERVAL="$2"; shift 2;;
    --max-attempts) MAX="$2"; shift 2;;
    --tag)          TAG="$2"; shift 2;;
    --state-dir)    STATE_DIR="$2"; shift 2;;
    --pattern)      PATTERN="$2"; shift 2;;
    *) echo "unknown arg: $1" >&2; exit 64;;
  esac
done
[ -z "$PROBE" ] && { echo "--probe is required" >&2; exit 64; }

mkdir -p "$STATE_DIR"
LOG="$STATE_DIR/nanny-$TAG.log"
PIDF="$STATE_DIR/nanny-$TAG.pid"
OKF="$STATE_DIR/nanny-$TAG.ok"

log() { echo "$(date '+%F %T') [pid $$] $*" >> "$LOG"; }

# single instance per tag
if [ -f "$PIDF" ] && kill -0 "$(cat "$PIDF")" 2>/dev/null; then
  log "another nanny already running; exit"
  exit 0
fi
echo $$ > "$PIDF"
rm -f "$OKF"
trap 'rm -f "$PIDF"' EXIT

log "START tag=$TAG interval=${INTERVAL}s max=$MAX probe='$PROBE'"

attempt=0
while [ "$attempt" -lt "$MAX" ]; do
  attempt=$((attempt + 1))
  out=$(eval "$PROBE" 2>&1); code=$?
  if [ "$code" -ne 0 ] || echo "$out" | grep -Eiq "$PATTERN"; then
    log "attempt $attempt/$MAX: STILL LIMITED (exit=$code) :: $(echo "$out" | head -n2 | tr '\n' '|')"
    sleep "$INTERVAL"
  else
    log "attempt $attempt/$MAX: RECOVERED (exit=$code)"
    date -Iseconds > "$OKF"
    if [ -n "$RESUME" ]; then
      log "running resume: '$RESUME'"
      rout=$(eval "$RESUME" 2>&1); rcode=$?
      log "resume exit=$rcode :: $(echo "$rout" | head -n3 | tr '\n' '|')"
    fi
    log "SUCCESS - quota restored, nanny exiting"
    exit 0
  fi
done
log "GIVE UP after $MAX attempts"
exit 2
