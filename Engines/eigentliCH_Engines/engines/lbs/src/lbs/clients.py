"""Typed callers for upstream engines: none.

lbs consumes client data only (the request) and calls no other engine, so this module holds no client. It
exists because the Engine Building Guide's anatomy names it, and so that the absence is stated rather than
discovered. Downstream, ``lbsim`` (8014) and ``report`` (8015) read the published sheets; the Optimizer's
``pcp`` (8007) is where a curator-finalised mandate proposal goes.
"""

UPSTREAM: dict[str, str] = {}
