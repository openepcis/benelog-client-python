# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 benelog GmbH & Co. KG
"""Publish one product, end to end, with nothing but this library.

Configuration comes from the environment::

    BENELOG_BASE_URL       e.g. https://id.epcis.cloud
    BENELOG_CLIENT_ID      the OIDC client the connector authenticates as
    BENELOG_OFFLINE_TOKEN  an offline token issued to that client
    BENELOG_GTIN           optional; when absent, a key is drawn from the pool

Everything else — the Keycloak realm, the token endpoint — is discovered.
"""

import os
import sys

from benelog_client.core.auth import InMemoryTokenStore, OfflineTokenAuth
from benelog_client.core.client import Client
from benelog_client.core.config import ClientConfig
from benelog_client.masterdata import Masterdata
from benelog_client.masterdata.payload import place, quantity
from benelog_client.registry import Registry


def main() -> int:
    config = ClientConfig(base_url=os.environ["BENELOG_BASE_URL"])
    auth = OfflineTokenAuth(
        config,
        InMemoryTokenStore(os.environ["BENELOG_OFFLINE_TOKEN"]),
        client_id=os.environ["BENELOG_CLIENT_ID"],
    )
    client = Client(config, auth)
    masterdata = Masterdata(client)
    registry = Registry(client)

    gtin = os.environ.get("BENELOG_GTIN", "")
    drawn = not gtin
    if drawn:
        gtin = registry.draw_key("01")
        print(f"drew {gtin} from the pool")

    document: dict = {}
    place(document, "productName", {"en": "Example chair", "de": "Beispielstuhl"})
    place(document, "brand.brandName", "Example")
    place(document, "countryOfOrigin.countryCode", "276")
    net_weight = quantity(4.5, "KGM")
    if net_weight:
        place(document, "netWeight", net_weight)

    try:
        masterdata.upsert_product(gtin, document)
    except Exception:
        if drawn:
            registry.release_key("01", gtin)  # do not strand the number
        raise
    if drawn:
        registry.confirm_key("01", gtin)
    print(f"published {gtin}")

    verification = registry.verified_by_gs1(gtin)
    print(f"verified by GS1: {verification.verified}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
