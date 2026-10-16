"""Create two demo tenants (A and B) with API keys, agents and end users.

    python -m scripts.seed              # creates tenants that don't exist yet, prints their keys once
    python -m scripts.seed --new-keys   # also mint an extra key for tenants that already exist

Keys are only stored as hashes, so they cannot be shown again. Run against the hosted DB with:
    DATABASE_URL=<your neon url> python -m scripts.seed
"""
import sys

from sqlalchemy import select

from app.db import _sessionmaker
from app.ids import new_id
from app.models import Agent, ApiKey, EndUser, Tenant
from app.security import generate_api_key

DEMO = {
    "tn_acme": {
        "name": "Acme Support",
        "agents": [("ag_104", "Priya S."), ("ag_105", "Dev K.")],
        "end_users": [("eu_55021", "Rahul M."), ("eu_55022", "Meera T.")],
    },
    "tn_globex": {
        "name": "Globex Care",
        "agents": [("ag_900", "Sam L.")],
        # same end user id as Acme on purpose: profiles are per tenant and never mix
        "end_users": [("eu_55021", "Another Person"), ("eu_77001", "Jo R.")],
    },
}


def main(new_keys: bool = False) -> None:
    db = _sessionmaker()()
    for tenant_id, spec in DEMO.items():
        exists = db.get(Tenant, tenant_id) is not None
        if not exists:
            db.add(Tenant(id=tenant_id, name=spec["name"]))
            db.flush()
            for aid, name in spec["agents"]:
                db.add(Agent(tenant_id=tenant_id, id=aid, name=name))
            for uid, name in spec["end_users"]:
                db.add(EndUser(tenant_id=tenant_id, id=uid, display_name=name))
        if not exists or new_keys:
            full, prefix, key_hash = generate_api_key()
            db.add(ApiKey(id=new_id("ak"), tenant_id=tenant_id, prefix=prefix, key_hash=key_hash))
            print(f"{tenant_id}  API key: {full}")
        else:
            print(f"{tenant_id}  already exists (use --new-keys for another key)")
    db.commit()


if __name__ == "__main__":
    main(new_keys="--new-keys" in sys.argv)
