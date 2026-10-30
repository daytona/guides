# Verify a migrated sandbox workflow (TypeScript)

Run one disposable Daytona v2 workflow: create a sandbox, write a file, run a command, read the result and request deletion of the owned sandbox. Use this as the target-side acceptance example when migrating sandbox execution from Vercel, Fly Machines, Blaxel, Modal, Cloudflare or E2B.

This example does not translate hosting, volumes, Functions, edge bindings or source images. Compare those requirements separately before moving an application.

## Requirements

- Node 22.4+ and `@daytona/sdk@2.0.0-alpha.4`.
- Organization access to Daytona v2 Linux sandboxes.
- A Daytona API key and an approved registered image containing `python3`.

The default SDK release channel can select stable 0.x. Keep the exact dependency pin. The [versioned package metadata](https://registry.npmjs.org/@daytona/sdk/2.0.0-alpha.4) links the tarball containing its README.

## Check offline

```sh
npm ci --ignore-scripts
npm test
```

These checks import the SDK and exercise acceptance logic with test doubles, without credentials. They reject failed commands and changed file contents, and check that cleanup requests deletion of the owned sandbox. They do not exercise the SDK's HTTP path or prove live deployment behavior.

## Run a live check

This step creates a billable sandbox and requests deletion of only that new sandbox. It does not access or delete source-provider resources.

Export `DAYTONA_API_KEY` through your usual secret-management mechanism. Export `DAYTONA_IMAGE` with the registered image name or ID. The script does not load `.env` automatically; `.env.example` lists the required names only.

```sh
npm run build
npm start
```

Expect JSON containing `"output": "migration ok\n"` and a zero exit code. The sandbox ID goes to stderr for recovery. The script rejects an unsuccessful process result or a changed file.

Creation waits up to 60 seconds, then an explicit startup wait allows up to 300 additional seconds. Guest operations begin only after the sandbox reaches `started`; a startup failure still triggers cleanup.

The process execution deadline is 30,000 milliseconds. The example requests deletion after a 600-second sandbox lifetime as a fallback. Normal cleanup requests deletion in `finally`; deletion returns before teardown finishes. A failed or uncertain create can require manual inspection; do not blindly create another resource. If cleanup fails, use the printed owned ID to inspect it. See the deletion caveat in the [package README](https://registry.npmjs.org/@daytona/sdk/-/sdk-2.0.0-alpha.4.tgz).

## Apply it to a migration

1. Inventory the source application's commands, arguments, working directory, file bytes, identity, auth and deadlines.
2. Run the reviewed migration linter against that application. Treat its snippets as examples, not automatic edits.
3. Adapt the application while preserving those requirements. Source IDs and snapshots are not portable.
4. Add acceptance checks for the application's actual outputs, failure cases, previews and recovery.
5. Re-lint and run offline tests. Authorize a live check separately before changing production traffic.
6. Keep the source service available until the migrated workflow passes its acceptance checks.

For async Python applications, use `AsyncDaytona` and await the matching operations; this TypeScript example does not establish parity for every source runtime. Keep source storage until the target's retention and recovery behavior is verified. An installed SDK does not establish storage availability.

## Changes from alpha.3

- The [alpha.4 package README](https://registry.npmjs.org/@daytona/sdk/-/sdk-2.0.0-alpha.4.tgz) makes image readiness explicit: `images.pull()` now waits by default; `images.build()` remains non-waiting. This workflow already requires a registered image, so it needs no image-import step.
- The same README clarifies asynchronous deletion. The example requests deletion in `finally`; a successful return does not prove teardown or image-reference release.
- The create, startup wait, file and process calls used here need no signature changes. Compare the public [alpha.3 metadata](https://registry.npmjs.org/@daytona/sdk/2.0.0-alpha.3) and [alpha.4 metadata](https://registry.npmjs.org/@daytona/sdk/2.0.0-alpha.4), including their linked tarball artifacts.

The alpha.4 update has not been executed against a live sandbox. Run the offline checks above before authorizing a live check.
