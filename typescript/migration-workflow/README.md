# Verify a migrated sandbox workflow (TypeScript)

Run one disposable Daytona v2 workflow with `@daytona/sdk@2.2.0`: create a sandbox, write a file, run a command, read the result and delete the owned sandbox. Cleanup waits for deletion to complete. Use this as the target-side acceptance example when migrating sandbox execution from Vercel, Fly Machines, Blaxel, Modal, Cloudflare or E2B.

This example does not translate hosting, volumes, Functions, edge bindings or source images. Compare those requirements separately before moving an application.

## Requirements

- Node 22.15.0+ and `@daytona/sdk@2.2.0`.
- Organization access to Daytona v2 Linux sandboxes.
- A Daytona API key and an approved registered image containing `python3`.

The default SDK release channel is now 2.x. Keep the exact dependency pin. The [2.2.0 package metadata](https://registry.npmjs.org/@daytona/sdk/2.2.0) links the tarball containing its public README and API declarations.

## Check offline

```sh
npm ci --ignore-scripts
npm test
```

These checks import the SDK and exercise acceptance logic with test doubles, without credentials. They require startup before guest access, reject failed commands and changed file contents, and check cleanup of the owned sandbox. They do not exercise the SDK's HTTP path or prove live deployment behavior.

## Run a live check

This step creates a billable sandbox and deletes only that new sandbox. It does not access or delete source-provider resources.

Export `DAYTONA_API_KEY` through your usual secret-management mechanism. Export `DAYTONA_IMAGE` with the registered image name or ID. The script does not load `.env` automatically; `.env.example` lists the required names only.

Set `DAYTONA_V2_API_URL` only when you need a non-default v2 API endpoint. SDK 2.x ignores `DAYTONA_API_URL` for routing. This example omits `region` and uses the endpoint's default placement. Set an approved explicit `region` when adapting the application if geography matters.

```sh
npm run build
npm start
```

Expect JSON containing `"output": "migration ok\n"` and a zero exit code. The sandbox ID goes to stderr for recovery. The script rejects an unsuccessful process result or a changed file.

Creation waits up to 60 seconds, then an explicit startup wait allows up to 300 additional seconds. Guest operations begin only after the sandbox reaches `started`; a startup failure still triggers cleanup.

The process execution deadline is 30 seconds (`executionTimeoutSeconds: 30`). The example requests deletion after a 600-second lifecycle timeout as a fallback. Normal cleanup awaits `sandbox.delete()` in `finally`. In 2.2.0, deletion waits up to 60 seconds for `destroyed`; a 404 during deletion also counts as completion. It throws `RequestTimeoutError` if the wait expires, or `SandboxTerminalStateError` for a reported terminal error. Cleanup errors propagate instead of reporting success. Completion does not guarantee that an image's references have already been released; this example does not delete its registered input image.

A failed or uncertain create can require manual inspection; do not blindly create another resource. The example does not retry create automatically. If cleanup fails, inspect only the printed owned ID. See the create-recovery and deletion contracts in the [2.2.0 public README](https://registry.npmjs.org/@daytona/sdk/-/sdk-2.2.0.tgz).

## Apply it to a migration

1. Inventory the source application's commands, arguments, working directory, file bytes, identity, auth and deadlines.
2. Run the reviewed migration linter against that application. Treat its snippets as examples, not automatic edits.
3. Adapt the application while preserving those requirements. Source IDs and snapshots are not portable.
4. Add acceptance checks for the application's actual outputs, failure cases, previews and recovery.
5. Re-lint and run offline tests. Authorize a live check separately before changing production traffic.
6. Keep the source service available until the migrated workflow passes its acceptance checks.

This example does not establish parity for every source runtime. Keep source storage until the target's retention and recovery behavior is verified. An installed SDK does not establish storage availability.

## Historical changes: alpha.6 to alpha.13

These changes were introduced between the alpha releases; they are not new changes in 2.2.0.

- Process durations changed to seconds and explicit option names. Replace `executionTimeout: 30_000` with `executionTimeoutSeconds: 30`. A caller wait uses `timeoutSeconds`, not the old millisecond `timeout`. That wait does not kill the process; this example leaves it unbounded and sets the server execution deadline.
- `sandbox.wait()` also renamed `timeout` to `timeoutSeconds`. Its value remains `300` because the sandbox startup wait already used seconds. The create-time `waitSeconds`, `createTimeoutSeconds` and lifecycle `timeoutSeconds` remain in seconds.
- `process.run()` returns `ProcessResult`, replacing `RunResult`. It includes collected `logs` and a normalized, required `reason`. Unknown reasons become `'unknown'` with the original value in `rawReason`. `exitCode` and `signal` are omitted unless reported. Success still requires `reason === 'exited'` and `exitCode === 0`, followed by an exact file-content match.
- `Daytona` remains a root import. Resource types and v2-specific errors come from `@daytona/sdk/v2`. Shared categories such as `DaytonaError` and `DaytonaTimeoutError` come from `@daytona/sdk`. The workflow lets SDK errors propagate and still attempts owned-resource cleanup after create succeeds.
- `sandbox.delete()` began waiting for deletion completion instead of only requesting asynchronous teardown. The workflow uses that built-in wait without adding another polling loop.
- Named creates gained get-or-create semantics. The example remains unnamed and disposable; do not add a shared name and then delete the returned sandbox as if it were newly owned.
- The SDK raised its minimum Node version to 22.15.0. The package engine and offline CI still use that minimum.

Compare the public [alpha.6 metadata](https://registry.npmjs.org/@daytona/sdk/2.0.0-alpha.6) and [alpha.13 metadata](https://registry.npmjs.org/@daytona/sdk/2.0.0-alpha.13), including their linked tarballs. These artifacts establish the contracts above; they do not prove live deployment behavior.

The 2.2.0 update has not been executed against a live sandbox. Run the offline checks above before authorizing a live check.

