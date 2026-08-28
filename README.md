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
  events/      EPCIS 2.0 visibility events: building them, capturing them
```

`masterdata/` and `events/` address two different services. Master data goes to
the catalog behind the Digital Link resolver; events go to an EPCIS repository,
on its own host and behind its own permission — capture needs the `capture`
role, and a credential that publishes products perfectly well is refused there.
Build a second `Client` for it rather than reusing the resolver's.

The module layout mirrors `benelog-client-java` (planned) so the concepts carry
across languages. The wire contract both implement is recorded in the Odoo
repository under `docs/api/observed-contract.md` and is pinned against the
platform's live OpenAPI.

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

config = ClientConfig(base_url="https://id.dev.epcis.cloud")
auth = OfflineTokenAuth(config, InMemoryTokenStore(offline_token), client_id="my-connector")
client = Client(config, auth)

gtin = Registry(client).draw_key("01")
Masterdata(client).upsert_product(gtin, {"productName": {"en": "Chair"}})
Registry(client).confirm_key("01", gtin)
```

A complete round trip, including release on failure and a Verified-by-GS1
check, is in `examples/publish_product.py`.

## Status

`core`, `masterdata` and `registry` are extracted and tested; the vocabulary
manifest is pinned in `masterdata/vocabulary.json`. `resolver` (linkset
management) and `epcis` (event capture) are planned. See the roadmap in the
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
