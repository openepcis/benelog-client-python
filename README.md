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
| Consumers | `openepcis-odoo` (Odoo 18/19), which vendors this package |
| Source | https://github.com/openepcis/benelog-client-python |

## Modules

```
benelog_client/
  core/        Identifiers, Digital Link URIs, transport, auth, errors
  masterdata/  Product and organization records, upsert, bulk, GPC
  registry/    GTIN/GLN allocation, credential deposit, Verified by GS1
  events/      EPCIS 2.0 visibility events: building them, capturing them
```

`masterdata/` and `events/` address two different services. Master data goes to
the catalog behind the Digital Link resolver; events go to an EPCIS repository,
on its own host and behind its own permission — capture needs the `capture`
role, and a credential that publishes products perfectly well is refused there.
Build a second `Client` for it rather than reusing the resolver's.

The resolver endpoints this library depends on are recorded in the Odoo
repository as `doc/api-contract.json` — paths, verbs and status codes only —
and its `tools/check-contract.py` compares that file against a running
deployment.

## Installation

The package is not on PyPI yet. Install it from the repository:

```bash
pip install "benelog-client @ git+https://github.com/openepcis/benelog-client-python"
```

The `hash` extra adds the canonical CBV event hash used as the `eventID` of
every event this library builds; see `pyproject.toml` for why it is an extra
and what it pulls in. The Odoo addon does not install the package at all: it
carries a verbatim copy under `openepcis_connector/vendor/`, so it stays
installable on any Odoo without a Python package beyond what Odoo ships.

## Usage

One configured URL; the Keycloak realm and token endpoint are discovered from
it (RFC 9728). Authentication uses an OIDC offline token, which the host's
`TokenStore` persists — including the rotated replacement Keycloak may answer
with on every exchange.

```python
from benelog_client.core.auth import InMemoryTokenStore, OfflineTokenAuth
from benelog_client.core.client import Client
from benelog_client.core.config import ClientConfig
from benelog_client.masterdata import Masterdata
from benelog_client.registry import Registry

config = ClientConfig(base_url="https://id.epcis.cloud")
auth = OfflineTokenAuth(config, InMemoryTokenStore(offline_token), client_id="my-connector")
client = Client(config, auth)

gtin = Registry(client).draw_key("01")
Masterdata(client).upsert_product(gtin, {"productName": {"en": "Chair"}})
Registry(client).confirm_key("01", gtin)
```

A complete round trip, including release on failure and a Verified-by-GS1
check, is in `examples/publish_product.py`.

## Status

All four modules are in use by the Odoo addon and covered by the test suite.
The vocabulary manifest the master data payloads are checked against is pinned
in `masterdata/vocabulary.json`. The version number is pre-release: the API is
still allowed to move between minor versions, and a consumer should vendor or
pin a commit rather than track `main`.

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
