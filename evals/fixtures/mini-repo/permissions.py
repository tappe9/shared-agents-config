"""Synthetic record permission check; no real service or identity is involved."""


def may_edit(actor, owner_id, locked=False):
    if locked:
        return False
    if actor.get("id") == owner_id:
        return True
    return bool(actor.get("is_admin", False))
