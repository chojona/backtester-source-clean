# Source export boundary

This repository originated as a standalone source export with a new root commit. Its subsequent branches and pull requests contain reviewed source changes; they do not import the private research repository or its historical Git objects.

## What belongs here

- Reviewed implementation source and documentation.
- Dependency metadata and configuration templates without secrets.
- Source-level tests with constructed inputs.
- The local terminal's application source and tests that read an external, user-supplied sealed release.

## What stays outside Git

Historical market records, provider responses and acquisition records, real calendars, private evidence/manifests, fitted models or coefficients, empirical research outputs, generated fixtures/reports, market-data screenshots, browser traces, credentials, and build directories are excluded. This also applies to generated synthetic output files; keep the generator source, not its generated artifacts.

Do not import historical workflow modules without reviewing their contents. Source code and Markdown can themselves embed observed quotes, provider metadata, fitted coefficients, private paths, or credentials. A permitted file extension does not make its contents publishable.

The original private repository is separate and is not sanitized by this export. The approved production evidence registry remains empty, and the exploratory adapter does not grant strict certification.

## Verification

```sh
python scripts/check_source_boundary.py
git status --short
git diff --cached --stat
```

The checker inspects every blob in reachable committed history for allowed paths/file types, selected credential patterns, and unchanged empty trust-registry/template requirements. It does not inspect uncommitted changes or establish market-data licensing. Review new and staged contents before committing, then rerun it after the commit and before pushing.

Ignore rules do not protect files already tracked or files added with force. Never force-add an ignored dataset, `.env`, report, screenshot, trace, or build artifact to bypass the boundary.

See [data and provenance](docs/DATA_AND_PROVENANCE.md) for input and availability semantics and [development](docs/DEVELOPMENT.md) for the verification workflows.
