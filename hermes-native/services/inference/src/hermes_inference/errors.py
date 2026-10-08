"""Stable, non-secret-bearing errors at the application boundary."""


class InferenceControlError(RuntimeError):
    code = "INFERENCE_CONTROL_ERROR"


class ProfileValidationError(ValueError):
    code = "INVALID_LOAD_PROFILE"


class AdmissionClosed(InferenceControlError):
    code = "ADMISSION_CLOSED"


class StaleAdmission(InferenceControlError):
    code = "STALE_ADMISSION"


class ProtocolError(InferenceControlError):
    code = "ENGINE_PROTOCOL_ERROR"


class RemoteOperationError(InferenceControlError):
    code = "ENGINE_OPERATION_FAILED"


class OperationUncertain(InferenceControlError):
    code = "OPERATION_UNCERTAIN"


class IdentityMismatch(InferenceControlError):
    code = "MODEL_IDENTITY_MISMATCH"


class EffectiveSettingsMismatch(InferenceControlError):
    code = "EFFECTIVE_SETTINGS_MISMATCH"


class UnsupportedManagedRuntime(InferenceControlError):
    code = "UNSUPPORTED_MANAGED_RUNTIME"
