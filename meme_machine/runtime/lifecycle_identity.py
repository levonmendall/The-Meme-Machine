"""Native lifecycle identities require no campaign or human authority."""

def issue(identity):
    if not isinstance(identity,str) or not identity:
        raise ValueError("lifecycle_identity")
    return identity

def validate_new(identity,*,archived=None):
    issue(identity)
    if archived is not None:
        raise ValueError("archived_lifecycle_requires_new_epoch")

def parsed(identity):
    return None
