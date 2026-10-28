# Security policy

## Supported versions

Security fixes are made on the latest release candidate and the `main` branch. Earlier tags are not maintained.

| Version | Supported |
|---|---|
| 0.9.x | Yes |
| Earlier than 0.9 | No |

## Reporting a vulnerability

Please do not open a public issue for a security problem. Use the private vulnerability reporting feature of the GitHub
repository (the Security tab, then "Report a vulnerability"). If that is not available, contact the maintainer through
the address on the GitHub profile of the repository owner.

Include what you found, the version or commit, the steps to reproduce it, and the impact as you understand it. Do not
include secrets or personal data in the report.

This is a research project maintained by one person. Reports are handled on a best effort basis, and there is no
guaranteed response time or fix time. Reporters are credited in the fix if they wish.

## Scope

In scope: the code in this repository, the read only API, the dashboard files, the build and workflow files, and the
published dataset files.

Things that deserve a private report:

- A way to recover aircraft identifiers or the keyed persistent emitter list from published files.
- A secret, token or key committed to the repository or exposed by a workflow.
- A vulnerability in the API that exposes files outside the release directory or allows code execution.
- A workflow change that would let untrusted input write to the `data` branch.

Not in scope: results that look wrong or a detector that misses an event (open a data quality issue instead), and
vulnerabilities in third party services or libraries (report those to their maintainers).

## Secrets

The incremental workflow uses a repository secret, `TASHWISH_STATE_KEY`. It must never appear in a file, a log, an issue
or a pull request. If you find it, report it privately.
