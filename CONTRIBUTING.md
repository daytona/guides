# Contributing to Daytona Guides

This repository is a collection of runnable **example guides** showing how to build AI agents,
data analysts, model-serving endpoints, and reinforcement-learning workflows on
[Daytona](https://www.daytona.io) sandboxes. Each guide lives in its own folder under
[`python/`](python/) or [`typescript/`](typescript/), self-contained with its own README,
dependencies, and `.env.example`. Contributions are welcome! ❤️

> If you like the project but don't have time to contribute, you can still help by starring
> the repo, telling others about it, or referencing it in your own project's README.

## Code of Conduct

This project is governed by the [Daytona Code of Conduct](./CODE_OF_CONDUCT.md). By
participating, you are expected to uphold it. Please report unacceptable behavior to
[codeofconduct@daytona.io](mailto:codeofconduct@daytona.io).

## Provide feedback

Found a bug or have an idea? Please
[open an issue](https://github.com/daytona/guides/issues/new/choose) — but first check that a
matching issue doesn't already exist.

## What you can contribute

- Bug fixes and improvements to an existing guide under [`python/`](python/) or
  [`typescript/`](typescript/).
- New guides (please open an issue first to discuss the fit).
- Documentation improvements.

## Submitting a pull request

1. [Fork](https://help.github.com/articles/working-with-forks/) the repository and create a
   branch for your change.
2. Keep each PR scoped to **a single guide** (docs-only or repo-wide changes are fine).
3. Use a clear, descriptive PR title following
   [Conventional Commits](https://www.conventionalcommits.org/) — e.g.
   `fix(codex-sdk): handle empty prompt`, `docs(readme): correct clone URL`.
4. **Sign off every commit** with `git commit -s` to comply with the DCO (see
   [Licensing](#licensing)).
5. Develop within the guide's own folder — each is self-contained, with its own dependencies
   and README. Make sure the guide still runs end to end before opening the PR.
6. Open the pull request (a
   [draft PR](https://help.github.com/en/articles/about-pull-requests#draft-pull-requests) is
   welcome for early feedback). A Daytona team member will review it, and once approved and
   green it will be merged into `main`.

The first time you open a PR, our CLA assistant will also comment with a link to the
[Contributor License Agreement](./CLA.md) and a one-line instruction to sign it (see
[Licensing](#licensing)).

## Licensing

This repository is made available under [Apache-2.0](./LICENSE). Contributing involves two
steps:

1. **DCO sign-off (per commit).** Sign off every commit with `git commit -s` to certify, under
   the [Developer Certificate of Origin](https://developercertificate.org/) v1.1, that you have
   the right to submit the code. The sign-off email must match the commit author's email. A
   DCO check runs on every pull request.

2. **CLA signature (once).** You must also sign the
   [Daytona Contributor License Agreement](./CLA.md) — it covers both individual and
   entity/corporate contributors. You (or, for entity contributors, your organization) retain
   copyright in your contributions, but you grant Daytona Platforms, Inc. a perpetual,
   irrevocable, sublicensable license to them — **including the right to relicense and
   redistribute the software under any terms (open source, proprietary, or closed source) and
   to change the license or visibility of the project at any time.** A CLA assistant bot will
   comment on your first pull request with a link and a one-line instruction to sign; a single
   signature covers all your future contributions to this repository.

Your PR cannot be merged until both the DCO check and the CLA check are green.
