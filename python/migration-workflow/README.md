# Verify a migrated sandbox workflow (Python)

Run one disposable Daytona v2 workflow: create a sandbox, write a file, run a command, read the result and delete the owned sandbox. Cleanup waits for deletion to complete. Use this as the target-side acceptance example when migrating sandbox execution from Vercel, Fly Machines, Blaxel, Modal, Cloudflare or E2B.

This example does not translate hosting, volumes, Functions, edge bindings or source images. Compare those requirements separately before moving an application.

## Requirements

- Python 3.10+ and `daytona==2.0.0a13`.
- Organization access to Daytona v2 Linux sandboxes.
- A Daytona API key and an approved registered image containing `python3`.

The default SDK release channel can select stable 0.x. `pip install --pre daytona` can select an older release candidate instead. Keep the exact dependency pin. The [versioned package metadata](https://pypi.org/pypi/daytona/2.0.0a13/json) includes the public README in `info.description` and links its wheel artifacts.

## Check offline

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
python -m unittest -v
```

These checks import the SDK and exercise acceptance logic with test doubles, without credentials. They reject failed commands and changed file contents, and check that cleanup requests deletion of the owned sandbox. They do not exercise the SDK's HTTP path or prove live deployment behavior.

## Run a live check

This step creates a billable sandbox and deletes only that new sandbox. It does not access or delete source-provider resources.

Export `DAYTONA_API_KEY` through your usual secret-management mechanism. Export `DAYTONA_IMAGE` with the registered image name or ID. The script does not load `.env` automatically; `.env.example` lists the required names only.

Set `DAYTONA_V2_API_URL` only when you need a non-default v2 API endpoint. SDK 2.x ignores `DAYTONA_API_URL` for routing. This example omits `region` and uses the endpoint's default placement. Set an approved explicit `region` when adapting the application if geography matters.

```sh
python workflow.py --run
```

Expect JSON containing `"output": "migration ok\n"` and a zero exit code. The sandbox ID goes to stderr for recovery. The script rejects an unsuccessful process result or a changed file.

Creation waits up to 60 seconds, then an explicit startup wait allows up to 300 additional seconds. Guest operations begin only after the sandbox reaches `started`; a startup failure still triggers cleanup.

The process execution deadline is 30 seconds (`execution_timeout=30`). The example requests deletion after a 600-second lifecycle timeout as a fallback. Normal cleanup calls `sandbox.delete()` in `finally`. In a13, deletion waits up to 60 seconds for `destroyed`; a 404 during deletion also counts as completion. It raises `RequestTimeoutError` if the wait expires, or `SandboxTerminalStateError` for a reported terminal error. Cleanup errors propagate instead of reporting success. Completion does not guarantee that an image's references have already been released; this example does not delete its registered input image.

A failed or uncertain create can require manual inspection; do not blindly create another resource. The example does not retry create automatically. If cleanup fails, inspect only the printed owned ID. See the create-recovery and deletion contracts in `info.description` in the [a13 package metadata](https://pypi.org/pypi/daytona/2.0.0a13/json).

## Apply it to a migration

1. Inventory the source application's commands, arguments, working directory, file bytes, identity, auth and deadlines.
2. Run the reviewed migration linter against that application. Treat its snippets as examples, not automatic edits.
3. Adapt the application while preserving those requirements. Source IDs and snapshots are not portable.
4. Add acceptance checks for the application's actual outputs, failure cases, previews and recovery.
5. Re-lint and run offline tests. Authorize a live check separately before changing production traffic.
6. Keep the source service available until the migrated workflow passes its acceptance checks.

For async Python applications, use `AsyncDaytona` and await the matching operations; this Python example does not establish parity for every source runtime. Keep source storage until the target's retention and recovery behavior is verified. An installed SDK does not establish storage availability.

## Changes from a6 to a13

- `LifecyclePolicyConfig` becomes `LifecyclePolicyOptions`, a public `TypedDict` from `daytona.v2`. The example keeps `timeout_seconds=600` and `on_timeout="delete"`.
- Python's `process.run(argv=..., execution_timeout=30)` still uses seconds. Its optional `timeout=` is a caller wait budget, not a process deadline. This example leaves that wait unbounded and sets the server execution deadline.
- `ProcessResult` includes collected `logs` and a normalized, required `reason`. Unknown reasons become `"unknown"` with the original value in `raw_reason`. `exit_code` and `signal` remain absent (`None`) unless reported. Success still requires `reason == "exited"` and `exit_code == 0`, followed by an exact file-content match.
- `Daytona` remains a root import. Resource types, `LifecyclePolicyOptions` and v2-specific errors come from `daytona.v2`. Shared categories such as `DaytonaError` and `DaytonaTimeoutError` come from `daytona`. The workflow lets SDK errors propagate and still attempts owned-resource cleanup after create succeeds.
- `sandbox.delete()` now waits for deletion completion instead of only requesting asynchronous teardown. The workflow uses that built-in wait without adding another polling loop.
- The example remains unnamed and disposable. Named creates now have get-or-create semantics; do not add a shared name and then delete the returned sandbox as if it were newly owned.

Compare the public [a6 metadata](https://pypi.org/pypi/daytona/2.0.0a6/json) and [a13 metadata](https://pypi.org/pypi/daytona/2.0.0a13/json), including their linked wheels. These artifacts establish the contracts above; they do not prove live deployment behavior.

The a13 update has not been executed against a live sandbox. Run the offline checks above before authorizing a live check.

