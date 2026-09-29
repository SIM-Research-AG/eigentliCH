"""The refusals of spec 3.7, each with its HTTP status and a plain sentence for people."""

from __future__ import annotations


class LbsimError(Exception):
    status = 500

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class NotFound(LbsimError):
    """404: an unknown sheet, allocation, artefact or run."""

    status = 404


class Conflict(LbsimError):
    """409: a client mismatch, fmre moved on, the sheet and the Allocation not matching, a run in another state."""

    status = 409


class InvalidRequest(LbsimError):
    """422: an invalid request, a currency other than CHF, a hard-currency fallback, a scenario as the base."""

    status = 422


class UpstreamDown(LbsimError):
    """503: an upstream engine does not answer."""

    status = 503
