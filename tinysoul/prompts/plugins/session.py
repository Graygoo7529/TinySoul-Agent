"""Model-visible text owned by plugins.session.

Consumers listed below decide visibility, role, data and failure semantics.
"""


# Local model feedback. Used by plugins/session/annotations/models.py:_text.
def bounded_text_required(*, name: str, limit: int) -> str:
    return f"{name} must be text within {limit} characters"


# Local model feedback. Used by plugins/session/annotations/models.py:_refs.
def bounded_references_required(*, name: str) -> str:
    return f"{name} must be a bounded list of references"


# Local model feedback. Used by plugins/session/annotations/models.py:_refs.
def distinct_references_required(*, name: str) -> str:
    return f"{name} must contain distinct references"


# Local model feedback. Used by plugins/session/annotations/models.py:_object.
INVALID_ANNOTATION_FIELDS = "Annotation fields do not match the declared object"

# Local model feedback. Used by plugins/session/annotations/models.py:_identity.
USE_AN_EXISTING_ANNOTATION_REF_OR_LOCAL_KEY_FOR_A = (
    "Use an existing annotation ref or local:<key> for a new object"
)

# Local model feedback. Used by plugins/session/annotations/models.py:__post_init__.
NODE_REQUIRES_A_TYPED_KIND_AND_STATUS = "Node requires a typed kind and status"

# Local model feedback. Used by plugins/session/annotations/models.py:parse.
INVALID_ANNOTATION_KIND_OR_STATUS = "Invalid annotation kind or status"

# Local model feedback. Used by plugins/session/annotations/models.py:__post_init__.
EDGE_REQUIRES_A_TYPED_RELATION_AND_STATUS = "Edge requires a typed relation and status"

# Local model feedback. Used by plugins/session/annotations/models.py:parse.
INVALID_RELATION_OR_STATUS = "Invalid relation or status"

# Local model feedback. Used by plugins/session/annotations/models.py:__post_init__.
ORGANIZE_REQUIRES_A_BOUNDED_NON_EMPTY_CHANGE = (
    "Organize requires a bounded non-empty change"
)

# Local model feedback. Used by plugins/session/annotations/models.py:__post_init__.
ORGANIZE_REQUIRES_TYPED_OBJECTS = "Organize requires typed objects"

# Local model feedback. Used by plugins/session/annotations/models.py:__post_init__.
AN_OBJECT_MAY_ONLY_BE_CHANGED_ONCE_PER_CALL = (
    "An object may only be changed once per call"
)

# Local model feedback. Used by plugins/session/annotations/models.py:parse.
UPSERTS_MUST_BE_LISTS = "Upserts must be lists"

# Local model feedback. Used by plugins/session/annotations/models.py:__post_init__.
INVALID_STORED_ANNOTATION_IDENTITIES = (
    "Stored annotations require distinct stable identities"
)

# Local model feedback. Used by plugins/session/annotations/models.py:__post_init__.
RETRACTED_NODES_CANNOT_RETAIN_ACTIVE_RELATIONS = (
    "Retracted nodes cannot retain active relations"
)

# Local model feedback. Used by plugins/session/annotations/models.py:__post_init__.
INVALID_RELATION_ENDPOINTS = "Relations must link semantic nodes or history facts"

# Local model feedback. Used by plugins/session/annotations/models.py:__post_init__.
COVERS_LINKS_A_THREAD_TO_A_HISTORY_FACT = "covers links a thread to a history fact"

# Local model feedback. Used by plugins/session/annotations/models.py:identity.
UNKNOWN_ANNOTATION_USE_LOCAL_KEY_TO_CREATE_IT = (
    "Unknown annotation; use local:<key> to create it"
)

# Local model feedback. Used by plugins/session/annotations/models.py:apply.
AN_EXISTING_NODE_CANNOT_CHANGE_KIND = "An existing node cannot change kind"

# Local model feedback. Used by plugins/session/annotations/models.py:apply.
UNKNOWN_ANNOTATION_TO_RETRACT = "Unknown annotation to retract"

# Local model feedback. Used by plugins/session/engine.py:organize.
THERE_ARE_NO_COMPLETED_TURNS_TO_ORGANIZE_YET = (
    "There are no completed Turns to organize yet"
)

# Local model feedback. Used by plugins/session/views/inspection.py:fact_ref.
UNAVAILABLE_EVIDENCE_REFERENCE = (
    "Reference must identify an available history fact or accepted current evidence"
)
