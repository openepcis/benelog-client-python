<!-- SPDX-License-Identifier: Apache-2.0 -->
<!-- SPDX-FileCopyrightText: 2026 benelog GmbH & Co. KG -->

# Contributing

## Licence and sign-off

This library is Apache-2.0. Contributions are accepted under the
[Developer Certificate of Origin](https://developercertificate.org/): sign off
every commit with `git commit -s`. There is no CLA.

Two rules keep the licence honest:

1. Every dependency must carry a permissive licence. CI fails the build when a
   copyleft licence appears in the dependency tree. Justify every dependency you
   add, in the commit message.
2. Do not copy code from copyleft sources. In particular, OCA Odoo modules are
   AGPL-3; GS1 parsing must not be lifted from them. Reimplement from the GS1
   General Specifications instead, and say so in the file header.

## Style

- English for all code, comments, commits and documentation.
- Conventional Commits.
- `ruff format` (pinned version, see `pyproject.toml`), `ruff check`,
  `mypy --strict`, `reuse lint` all pass before a pull request.
- Every public function that implements a GS1 rule cites the relevant section of
  the GS1 General Specifications.
- Errors carry structured data, never finished sentences meant for end users.
  Host adapters phrase and translate.
