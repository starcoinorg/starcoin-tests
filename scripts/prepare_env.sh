#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" >/dev/null 2>&1 && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." >/dev/null 2>&1 && pwd)"

DO_INSTALL=0
ASSUME_YES=0
SUDO_MODE="auto" # auto|always|never
STARCOIN_BIN="${STARCOIN_BIN:-}"

OK=0
WARN=0
ERR=0

usage() {
  cat <<'USAGE'
Usage: ./scripts/prepare_env.sh [options]

Options:
  --install              Install missing dependencies when possible.
  --check-only           Only check environment (default).
  --yes                  Non-interactive package-manager install flags.
  --with-sudo            Force using sudo for install commands.
  --without-sudo         Never use sudo for install commands.
  --starcoin-bin <path>  Optional starcoin binary path to validate.
  -h, --help             Show this help.

Examples:
  ./scripts/prepare_env.sh
  ./scripts/prepare_env.sh --install --yes
  ./scripts/prepare_env.sh --check-only --starcoin-bin ../starcoin/target/debug/starcoin
USAGE
}

log_ok() {
  echo "[OK] $*"
  OK=$((OK + 1))
}

log_warn() {
  echo "[WARN] $*"
  WARN=$((WARN + 1))
}

log_err() {
  echo "[ERR] $*"
  ERR=$((ERR + 1))
}

cmd_exists() {
  command -v "$1" >/dev/null 2>&1
}

detect_os() {
  local os
  os="$(uname -s)"
  case "$os" in
    Linux) echo "linux" ;;
    Darwin) echo "darwin" ;;
    *) echo "unknown" ;;
  esac
}

detect_pkg_manager() {
  if cmd_exists brew; then
    echo "brew"
    return
  fi
  if cmd_exists apt-get; then
    echo "apt"
    return
  fi
  if cmd_exists dnf; then
    echo "dnf"
    return
  fi
  if cmd_exists yum; then
    echo "yum"
    return
  fi
  if cmd_exists pacman; then
    echo "pacman"
    return
  fi
  if cmd_exists apk; then
    echo "apk"
    return
  fi
  echo "none"
}

sudo_prefix() {
  case "$SUDO_MODE" in
    always)
      echo "sudo"
      ;;
    never)
      echo ""
      ;;
    auto)
      if [ "${EUID:-$(id -u)}" -eq 0 ]; then
        echo ""
      elif cmd_exists sudo; then
        echo "sudo"
      else
        echo ""
      fi
      ;;
    *)
      echo ""
      ;;
  esac
}

run_install() {
  local pm="$1"
  shift
  local pkgs=("$@")
  local s
  s="$(sudo_prefix)"
  local yflag=""
  if [ "$ASSUME_YES" -eq 1 ]; then
    yflag="-y"
  fi

  case "$pm" in
    brew)
      brew install "${pkgs[@]}"
      ;;
    apt)
      # shellcheck disable=SC2086
      $s apt-get update
      # shellcheck disable=SC2086
      $s apt-get install $yflag "${pkgs[@]}"
      ;;
    dnf)
      # shellcheck disable=SC2086
      $s dnf install $yflag "${pkgs[@]}"
      ;;
    yum)
      # shellcheck disable=SC2086
      $s yum install $yflag "${pkgs[@]}"
      ;;
    pacman)
      local pflag="-S"
      if [ "$ASSUME_YES" -eq 1 ]; then
        pflag="-S --noconfirm"
      fi
      # shellcheck disable=SC2086
      $s pacman $pflag "${pkgs[@]}"
      ;;
    apk)
      # shellcheck disable=SC2086
      $s apk add ${pkgs[*]}
      ;;
    *)
      return 1
      ;;
  esac
}

check_or_install_cmd() {
  local bin="$1"
  local pm="$2"
  local install_pkg="$3"
  if cmd_exists "$bin"; then
    log_ok "Found command: $bin"
    return
  fi

  if [ "$DO_INSTALL" -eq 1 ] && [ "$pm" != "none" ] && [ -n "$install_pkg" ]; then
    log_warn "Missing $bin, trying to install package: $install_pkg"
    if run_install "$pm" "$install_pkg"; then
      if cmd_exists "$bin"; then
        log_ok "Installed and found command: $bin"
      else
        log_err "Installed package for $bin, but command still missing"
      fi
    else
      log_err "Failed to install package for $bin with package manager: $pm"
    fi
  else
    log_warn "Missing command: $bin"
  fi
}

install_artillery_if_needed() {
  if cmd_exists artillery; then
    log_ok "Found command: artillery"
    return
  fi
  if ! cmd_exists npm; then
    log_warn "npm is missing, cannot install artillery"
    return
  fi
  if [ "$DO_INSTALL" -eq 0 ]; then
    log_warn "artillery is missing (run with --install to auto-install via npm)"
    return
  fi

  local s
  s="$(sudo_prefix)"
  log_warn "Installing artillery via npm -g"
  if [ -n "$s" ]; then
    if $s npm install -g artillery@latest; then
      :
    else
      log_err "Failed to install artillery with sudo npm"
      return
    fi
  else
    if npm install -g artillery@latest; then
      :
    else
      log_err "Failed to install artillery with npm"
      return
    fi
  fi

  if cmd_exists artillery; then
    log_ok "Installed and found command: artillery"
  else
    log_warn "npm install completed but artillery command is not in PATH"
  fi
}

check_docker_compose() {
  if docker compose version >/dev/null 2>&1; then
    log_ok "Found command: docker compose"
    return
  fi
  if cmd_exists docker-compose; then
    log_ok "Found command: docker-compose"
    return
  fi
  log_warn "Missing docker compose (docker compose or docker-compose)"
}

check_starcoin_bin() {
  local target="$1"
  if [ -z "$target" ]; then
    if [ -x "${ROOT_DIR}/../starcoin/target/debug/starcoin" ]; then
      target="${ROOT_DIR}/../starcoin/target/debug/starcoin"
    else
      log_warn "starcoin binary path not provided and default ../starcoin/target/debug/starcoin not found"
      return
    fi
  fi

  if [ -x "$target" ]; then
    log_ok "starcoin binary is executable: $target"
  else
    log_warn "starcoin binary not executable or not found: $target"
  fi
}

check_network_fault_backend() {
  local os="$1"
  if [ "$os" = "linux" ]; then
    if cmd_exists tc; then
      log_ok "Linux net impairment backend available: tc"
    else
      log_warn "Linux net impairment backend missing: tc (install iproute2)"
    fi
  elif [ "$os" = "darwin" ]; then
    if cmd_exists dnctl && cmd_exists pfctl; then
      log_ok "macOS net impairment backend available: dnctl + pfctl"
    else
      log_warn "macOS net impairment backend missing: dnctl/pfctl"
    fi
  else
    log_warn "Unsupported OS for net impairment backend auto-check"
  fi

  if [ "${EUID:-$(id -u)}" -eq 0 ]; then
    log_ok "Current user is root (network fault injection can run directly)"
  else
    if cmd_exists sudo; then
      if sudo -n true >/dev/null 2>&1; then
        log_ok "sudo is available without password prompt"
      else
        log_warn "sudo requires password (net_delay/net_loss may prompt for password)"
      fi
    else
      log_warn "sudo not found and current user is non-root"
    fi
  fi
}

parse_args() {
  while [ $# -gt 0 ]; do
    case "$1" in
      --install)
        DO_INSTALL=1
        ;;
      --check-only)
        DO_INSTALL=0
        ;;
      --yes)
        ASSUME_YES=1
        ;;
      --with-sudo)
        SUDO_MODE="always"
        ;;
      --without-sudo)
        SUDO_MODE="never"
        ;;
      --starcoin-bin)
        shift
        if [ $# -eq 0 ]; then
          log_err "--starcoin-bin requires a value"
          exit 2
        fi
        STARCOIN_BIN="$1"
        ;;
      -h|--help)
        usage
        exit 0
        ;;
      *)
        log_err "Unknown option: $1"
        usage
        exit 2
        ;;
    esac
    shift
  done
}

main() {
  parse_args "$@"

  local os
  os="$(detect_os)"
  local pm
  pm="$(detect_pkg_manager)"

  echo "== starcoin-nettest environment preparation =="
  echo "OS: ${os}"
  echo "Package manager: ${pm}"
  echo "Install mode: $([ "$DO_INSTALL" -eq 1 ] && echo install || echo check-only)"
  echo "Sudo mode: ${SUDO_MODE}"
  echo

  check_or_install_cmd "python3" "$pm" "python3"

  if [ "$os" = "darwin" ]; then
    check_or_install_cmd "node" "$pm" "node"
    check_or_install_cmd "npm" "$pm" "node"
  else
    check_or_install_cmd "node" "$pm" "nodejs"
    check_or_install_cmd "npm" "$pm" "npm"
  fi
  check_or_install_cmd "docker" "$pm" "docker"
  check_docker_compose
  install_artillery_if_needed

  if [ "$os" = "linux" ]; then
    check_or_install_cmd "tc" "$pm" "iproute2"
  fi

  check_starcoin_bin "$STARCOIN_BIN"
  check_network_fault_backend "$os"

  echo
  echo "Summary: ok=${OK}, warn=${WARN}, err=${ERR}"
  if [ "$ERR" -gt 0 ]; then
    exit 1
  fi
}

main "$@"
