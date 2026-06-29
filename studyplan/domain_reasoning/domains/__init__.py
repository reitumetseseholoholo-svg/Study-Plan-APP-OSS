# Domain modules are imported here to trigger their register_domain() calls.
# Each module registers itself with the global DomainRegistry hub.
from studyplan.domain_reasoning.domains import pmp  # noqa: F401
