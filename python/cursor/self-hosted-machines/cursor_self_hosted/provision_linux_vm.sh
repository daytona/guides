#!/usr/bin/env bash
set -Eeuo pipefail

readonly CURSOR_AGENT_VERSION="2026.09.02-e3e9343"
readonly CURSOR_AGENT_URL="https://downloads.cursor.com/lab/2026.09.02-e3e9343/linux/x64/agent-cli-package.tar.gz"
readonly CURSOR_AGENT_BLAKE2="a29694895b3b5d90e7d751eddfd2682e4872c9db6c2a3dee9eb3940a74d58c1cd498be3cc5ddf22bc7a22f2e8011e7430e5392149d1704ce952b368fa105d484"
readonly CURSOR_AGENT_ROOT="/opt/cursor-agent"
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


[[ $(uname -s) == "Linux" ]] || fail "requires Linux"
[[ $(uname -m) == "x86_64" ]] || fail "requires x86_64; found $(uname -m)"
[[ $(id -un) == "daytona" ]] || fail "must run as the daytona user"
command -v sudo >/dev/null 2>&1 || fail "sudo is not installed"
sudo -n true >/dev/null 2>&1 || fail "daytona does not have passwordless sudo"

install_snapshot_contents() {
    command -v apt-get >/dev/null 2>&1 || fail "apt-get is not available"

    sudo -n env DEBIAN_FRONTEND=noninteractive apt-get update
    sudo -n env DEBIAN_FRONTEND=noninteractive apt-get install \
        --yes --no-install-recommends ca-certificates curl git
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
    sudo -n install -d --owner=daytona --group=daytona --mode=0755 "$WORKSPACE"
    rm -rf -- "$temporary_directory"
    temporary_directory=""
}

verify_snapshot_contents() {
    local package status agent_version worker_help write_probe

    for package in ca-certificates curl git; do
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
    grep --quiet --fixed-strings -- '--clone-git-repos' <<<"$worker_help" \
        || fail "Cursor worker CLI does not expose --clone-git-repos"

    git --version >/dev/null 2>&1 || fail "git is unavailable"

    [[ -d "$WORKSPACE" && -w "$WORKSPACE" ]] \
        || fail "workspace is not writable by daytona"
    [[ $(stat --format='%U:%G' "$WORKSPACE") == "daytona:daytona" ]] \
        || fail "workspace is not owned by daytona"
    write_probe="$(mktemp "${WORKSPACE}/.cursor-self-hosted-write-test.XXXXXX")" \
        || fail "workspace write probe failed"
    rm -f -- "$write_probe"
}

if [[ $MODE == "Install" ]]; then
    install_snapshot_contents
fi
verify_snapshot_contents
printf 'Cursor Linux VM snapshot verified: %s\n' "$CURSOR_AGENT_VERSION"
