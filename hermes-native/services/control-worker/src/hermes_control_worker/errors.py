"""Public errors use fixed messages and never echo request contents."""


class ControlError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


INVALID_PARAMS = ("INVALID_PARAMS", "Request parameters do not match this operation.")
INVALID_PROFILE = ("INVALID_PROFILE", "The load profile is invalid or exceeds service limits.")
STATE_INVALID = ("STATE_INVALID", "The explicit control state directory is unavailable or invalid.")
