#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

BASE_COMPOSE="${BASE_COMPOSE:-docker-compose.yml}"
OBS_COMPOSE="${OBS_COMPOSE:-docker-compose.observability.yml}"

# Runtime services we actually want running (NO polytest here)
RUNTIME_SVCS=("prometheus" "tempo" "otel-collector" "grafana" "agent")
OBS_SVCS=("otel-collector" "tempo" "prometheus" "grafana")

EXTERNAL_NET="${EXTERNAL_NET:-strands-demo-net}"  # must match compose networks.stacknet.name

compose_files() {
  local args=()
  [[ -f "$BASE_COMPOSE" ]] || { echo "ERROR: $BASE_COMPOSE not found." >&2; exit 1; }
  args+=(-f "$BASE_COMPOSE")
  [[ -f "$OBS_COMPOSE" ]] && args+=(-f "$OBS_COMPOSE")
  printf '%s ' "${args[@]}"
}

compose_files_obs_only() {
  [[ -f "$OBS_COMPOSE" ]] || { echo "ERROR: $OBS_COMPOSE not found (obs-only request)." >&2; exit 1; }
  printf '%s ' -f "$OBS_COMPOSE"
}

# docker compose with profiles DISABLED (so 'polytest' profile won't sneak in)
dc() { COMPOSE_PROFILES= docker compose $(compose_files) "$@"; }
dc_obs() { COMPOSE_PROFILES= docker compose $(compose_files_obs_only) "$@"; }
# enable profiles only when explicitly building polytest
dc_with_profiles() { local p="$1"; shift; COMPOSE_PROFILES="$p" docker compose $(compose_files) "$@"; }

project_name() {
  dc config 2>/dev/null | awk '/^name:/ {print $2; exit}'
}

ensure_external_net() {
  if ! docker network inspect "$EXTERNAL_NET" >/dev/null 2>&1; then
    echo "Creating external network: $EXTERNAL_NET"
    docker network create "$EXTERNAL_NET" >/dev/null
  fi
}

ensure_polytest_removed() {
  dc rm -fsv polytest >/dev/null 2>&1 || true
  # Also scale to 0 in case compose tries to be "helpful"
  dc up -d --scale polytest=0 >/dev/null 2>&1 || true
}

nuke_networks() {
  local PNAME NETS
  PNAME="$(project_name)"
  # remove any compose-labeled networks
  NETS="$(docker network ls -q -f "label=com.docker.compose.project=${COMPOSE_PROJECT_NAME:-$PNAME}")"
  [[ -n "${NETS// }" ]] && docker network rm $NETS >/dev/null 2>&1 || true
  # also remove default-named network just in case
  local DEFNET="${COMPOSE_PROJECT_NAME:-${PNAME:-$(basename "$ROOT")}}_default"
  docker network rm "$DEFNET" >/dev/null 2>&1 || true
}

hard_clean() {
  local PNAME; PNAME="$(project_name)"
  # Stop/remove project containers
  ids="$(docker ps -aq -f "label=com.docker.compose.project=${COMPOSE_PROJECT_NAME:-$PNAME}")"
  [[ -n "${ids// }" ]] && docker stop $ids >/dev/null 2>&1 || true
  [[ -n "${ids// }" ]] && docker rm -fv $ids >/dev/null 2>&1 || true
  # Nuke networks
  nuke_networks
}

up_runtime() {
  ensure_external_net
  ensure_polytest_removed
  # bring up only the runtime services we want
  if ! dc up -d "${RUNTIME_SVCS[@]}"; then
    echo "Up failed; attempting network repair..." >&2
    nuke_networks || true
    ensure_external_net
    dc up -d "${RUNTIME_SVCS[@]}"
  fi
}

usage() {
  cat <<'EOF'
Usage: scripts/stack.sh <command>

Core:
  start            Up (detached) for runtime services (polytest excluded; profiles off)
  stop             Gracefully stop all services (keep containers)
  restart          Stop then start
  status           docker compose ps
  logs             Follow logs for all services
  build            Build images (base + obs if present)
  rebuild          Build (no cache) then up runtime
  build-start      Build everything (incl. polytest image) then start runtime services
  down             Stop & remove containers + network (keeps volumes)
  clean            down + remove local images (not volumes)
  hard-clean       Aggressively remove project containers & networks (use if down fails)

Observability only:
  obs:start        Up -d grafana prometheus tempo otel-collector
  obs:stop         Stop observability services
  obs:status       ps for observability services
  obs:logs         Follow logs for observability services

Polytest:
  polytest-build   Build strands/polytest:latest via 'builder' profile (does not run it)

Network helpers:
  nuke-net         Remove compose networks for this project
  start-fix        nuke-net then start
EOF
}

cmd="${1:-}"
case "$cmd" in
  start)        up_runtime ;;
  stop)         dc stop ;;
  restart)      dc stop; up_runtime ;;
  status)       dc ps ;;
  logs)         dc logs -f --tail=200 ;;
  build)        dc build ;;
  rebuild)      dc build --no-cache; up_runtime ;;
  build-start|up-all)
                dc build
                dc_with_profiles builder --profile builder build polytest || true
                up_runtime
                ;;
  down)         dc down --remove-orphans ;;
  clean)        dc down --remove-orphans --rmi local ;;
  hard-clean)   hard_clean ;;
  obs:start)    ensure_external_net; dc_obs up -d "${OBS_SVCS[@]}" ;;
  obs:stop)     dc_obs stop "${OBS_SVCS[@]}" ;;
  obs:status)   dc_obs ps ;;
  obs:logs)     dc_obs logs -f --tail=200 "${OBS_SVCS[@]}" ;;
  polytest-build)
                dc_with_profiles builder --profile builder build polytest ;;
  nuke-net)     nuke_networks ;;
  start-fix)    nuke_networks; up_runtime ;;
  ""|-h|--help|help) usage ;;
  *) echo "Unknown command: $cmd" >&2; usage; exit 1 ;;
esac
