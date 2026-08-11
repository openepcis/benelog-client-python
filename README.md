<!-- SPDX-License-Identifier: Apache-2.0 -->
<!-- SPDX-FileCopyrightText: 2026 benelog GmbH & Co. KG -->

# benelog-client-python

Client library for benelog's product data platform. It carries the parts of a
connector that are the same in every host system: transport and authentication,
GS1 identifier arithmetic, master data publication, and the GS1 key registry.
Host adapters (the Odoo addon, the ERPNext app) stay thin and framework
specific; this library holds no host dependency.

| | |
|---|---|
| Licence | Apache-2.0 |
| Python | 3.10 or newer |
| Dependencies | `requests` only |
| Consumers | `openepcis-odoo` (Odoo 18/19), ERPNext connector (planned) |

## Modules

```
benelog_client/
  core/        Identifiers, Digital Link URIs, transport, auth, errors
  masterdata/  Product and organization records, upsert, bulk, GPC
  registry/    GTIN/GLN allocation, credential deposit, Verified by GS1
```

The module layout mirrors `benelog-client-java` (planned) so the concepts carry
across languages. The wire contract both implement is recorded in the Odoo
repository under `docs/api/observed-contract.md` and is pinned against the
platform's live OpenAPI.

## Status

Extraction in progress. `core.gs1` and `core.errors` are complete and tested;
transport, masterdata and registry follow in that order. See the roadmap in the
Odoo repository: `docs/architecture/connector-roadmap.md`.

## Development

```bash
pip install -e ".[dev]"
pytest
mypy
ruff format --check . && ruff check .
reuse lint
```

Contributions are accepted under the Developer Certificate of Origin: sign off
your commits with `git commit -s`. There is no CLA.
