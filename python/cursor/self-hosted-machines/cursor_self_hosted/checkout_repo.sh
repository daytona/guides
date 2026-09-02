#!/bin/sh
# Cursor sessionStart hook: check out the claimed repository into the workspace.
#
# The spawn command already configured `origin` in the workspace, which is what
# makes Cursor route the request to this worker. Cursor runs this hook after the
# claim with the sessionStart payload on stdin and CURSOR_WORKER_WORKSPACE_DIR
# set. The fetch authenticates with the short-lived GitHub token that Cursor
# writes to the worker's git configuration (--mint-github-token).
set -eu

workspace="${CURSOR_WORKER_WORKSPACE_DIR:?CURSOR_WORKER_WORKSPACE_DIR is required}"
# The hook has no terminal; a missing token must fail fast instead of prompting.
export GIT_TERMINAL_PROMPT=0

ref="$(python3 -c '
import json, sys
repos = json.load(sys.stdin).get("repos") or []
primary = [repo for repo in repos if repo.get("primary")] or repos
print((primary[0].get("ref") or "") if primary else "")
')"
if [ -z "$ref" ]; then
    echo "error: sessionStart payload has no repository ref" >&2
    exit 1
fi

# A follow-up session on the same worker already has the checkout.
if git -C "$workspace" rev-parse --verify --quiet HEAD >/dev/null; then
    printf '{"status":"ok"}\n'
    exit 0
fi

# The minted token can arrive moments after the session starts.
delay=1
for attempt in 1 2 3 4 5; do
    if git -C "$workspace" fetch --quiet origin "$ref" \
        && git -C "$workspace" checkout --quiet -B "$ref" FETCH_HEAD; then
        printf '{"status":"ok"}\n'
        exit 0
    fi
    sleep "$delay"
    delay=$((delay * 2))
done

echo "error: could not fetch '$ref' from origin; confirm GitHub token minting and repository access" >&2
exit 1
