#!/usr/bin/env bash
set -Eeuo pipefail

readonly CURSOR_AGENT_VERSION="2026.08.25-3e8eec8"
readonly CURSOR_AGENT_URL="https://downloads.cursor.com/lab/2026.08.25-3e8eec8/linux/x64/agent-cli-package.tar.gz"
readonly CURSOR_AGENT_BLAKE2="cd5485f7524688e1a688daa2b64669c76bedcdd9ab87638bac78f9b42c2442bd5000559920a2f5171e00b5eb7fcf737f9111ef296f1eba40369cebf3279ee0a9"
readonly CURSOR_AGENT_ROOT="/opt/cursor-agent"
readonly CLONE_HOOK_DESTINATION="/usr/local/bin/clone-cursor-byom-repos"
readonly WORKSPACE="/home/daytona/workspace"
temporary_directory=""

cleanup() {
    if [[ -n $temporary_directory ]]; then
        rm -rf -- "$temporary_directory"
    fi
}
trap cleanup EXIT


fail() {
    printf 'provision_linux_vm: %s\n' "$*" >&2
    exit 1
}

if [[ $# -eq 0 ]]; then
    readonly MODE="Install"
elif [[ $# -eq 1 && $1 == "VerifyOnly" ]]; then
    readonly MODE="VerifyOnly"
else
    fail "usage: provision_linux_vm.sh [VerifyOnly]"
fi

readonly SCRIPT_DIRECTORY="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
readonly CLONE_HOOK_SOURCE="${SCRIPT_DIRECTORY}/clone_repos.py"

[[ $(uname -s) == "Linux" ]] || fail "requires Linux"
[[ $(uname -m) == "x86_64" ]] || fail "requires x86_64; found $(uname -m)"
[[ $(id -un) == "daytona" ]] || fail "must run as the daytona user"
[[ -r "$CLONE_HOOK_SOURCE" && -f "$CLONE_HOOK_SOURCE" ]] || \
    fail "missing uploaded clone_repos.py"
command -v sudo >/dev/null 2>&1 || fail "sudo is not installed"
sudo -n true >/dev/null 2>&1 || fail "daytona does not have passwordless sudo"

install_snapshot_contents() {
    command -v apt-get >/dev/null 2>&1 || fail "apt-get is not available"

    sudo -n env DEBIAN_FRONTEND=noninteractive apt-get update
    sudo -n env DEBIAN_FRONTEND=noninteractive apt-get install \
        --yes --no-install-recommends ca-certificates curl git python3
    sudo -n rm -rf /var/lib/apt/lists/*

    local archive staging_root downloaded_version
    temporary_directory="$(mktemp -d /tmp/cursor-agent-download.XXXXXX)"
    archive="${temporary_directory}/agent-cli-package.tar.gz"
    staging_root="${CURSOR_AGENT_ROOT}.new"

    curl \
        --fail \
        --location \
        --silent \
        --show-error \
        --proto '=https' \
        --tlsv1.2 \
        --retry 3 \
        --retry-all-errors \
        --connect-timeout 30 \
        "$CURSOR_AGENT_URL" \
        --output "$archive"

    printf '%s  %s\n' "$CURSOR_AGENT_BLAKE2" "$archive" \
        | b2sum --check --status \
        || fail "Cursor package BLAKE2 digest mismatch"

    sudo -n rm -rf -- "$staging_root"
    sudo -n install -d --owner=root --group=root --mode=0755 "$staging_root"
    sudo -n tar \
        --extract \
        --gzip \
        --file "$archive" \
        --directory "$staging_root" \
        --strip-components=1 \
        --no-same-owner
    sudo -n chown -R root:root "$staging_root"
    [[ -x "${staging_root}/cursor-agent" ]] \
        || fail "verified package does not contain executable cursor-agent"

    downloaded_version="$("${staging_root}/cursor-agent" --version)"
    [[ $downloaded_version == "$CURSOR_AGENT_VERSION" ]] || fail \
        "verified package reports version '${downloaded_version}', expected '${CURSOR_AGENT_VERSION}'"

    sudo -n rm -rf -- "$CURSOR_AGENT_ROOT"
    sudo -n mv -- "$staging_root" "$CURSOR_AGENT_ROOT"
    sudo -n ln --symbolic --force \
        "${CURSOR_AGENT_ROOT}/cursor-agent" /usr/local/bin/agent
    sudo -n ln --symbolic --force \
        "${CURSOR_AGENT_ROOT}/cursor-agent" /usr/local/bin/cursor-agent
    sudo -n install --owner=root --group=root --mode=0755 \
        "$CLONE_HOOK_SOURCE" "$CLONE_HOOK_DESTINATION"
    sudo -n install -d --owner=daytona --group=daytona --mode=0755 "$WORKSPACE"
    rm -rf -- "$temporary_directory"
    temporary_directory=""
}

verify_snapshot_contents() {
    local package status agent_version worker_help write_probe

    for package in ca-certificates curl git python3; do
        status="$(dpkg-query --show --showformat='${Status}' "$package" 2>/dev/null || true)"
        [[ $status == "install ok installed" ]] \
            || fail "required package '${package}' is not installed"
    done

    [[ -x "${CURSOR_AGENT_ROOT}/cursor-agent" ]] \
        || fail "Cursor agent executable is missing"
    [[ $(readlink -f /usr/local/bin/agent 2>/dev/null || true) == \
        "${CURSOR_AGENT_ROOT}/cursor-agent" ]] \
        || fail "/usr/local/bin/agent does not target the pinned Cursor agent"
    [[ $(readlink -f /usr/local/bin/cursor-agent 2>/dev/null || true) == \
        "${CURSOR_AGENT_ROOT}/cursor-agent" ]] \
        || fail "/usr/local/bin/cursor-agent does not target the pinned Cursor agent"

    agent_version="$(/usr/local/bin/agent --version)"
    [[ $agent_version == "$CURSOR_AGENT_VERSION" ]] \
        || fail "agent reports version '${agent_version}', expected '${CURSOR_AGENT_VERSION}'"

    worker_help="$(/usr/local/bin/agent worker --help 2>&1)" \
        || fail "Cursor worker CLI is unavailable"
    grep --quiet --fixed-strings -- '--pool' <<<"$worker_help" \
        || fail "Cursor worker CLI does not expose --pool"

    git --version >/dev/null 2>&1 || fail "git is unavailable"
    python3 --version >/dev/null 2>&1 || fail "python3 is unavailable"
    [[ -x "$CLONE_HOOK_DESTINATION" ]] \
        || fail "installed clone hook is not executable"
    cmp --silent "$CLONE_HOOK_SOURCE" "$CLONE_HOOK_DESTINATION" \
        || fail "installed clone hook does not match the uploaded recipe"
    "$CLONE_HOOK_DESTINATION" --help >/dev/null \
        || fail "installed clone hook cannot execute"

    [[ -d "$WORKSPACE" && -w "$WORKSPACE" ]] \
        || fail "workspace is not writable by daytona"
    [[ $(stat --format='%U:%G' "$WORKSPACE") == "daytona:daytona" ]] \
        || fail "workspace is not owned by daytona"
    write_probe="$(mktemp "${WORKSPACE}/.cursor-byom-write-test.XXXXXX")" \
        || fail "workspace write probe failed"
    rm -f -- "$write_probe"
}

if [[ $MODE == "Install" ]]; then
    install_snapshot_contents
fi
verify_snapshot_contents
printf 'Cursor Linux VM snapshot verified: %s\n' "$CURSOR_AGENT_VERSION"
