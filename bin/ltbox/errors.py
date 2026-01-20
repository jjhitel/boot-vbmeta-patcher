class LTBoxError(Exception):
    def __init__(self, message: str, original_error: Exception = None):
        super().__init__(message)
        self.original_error = original_error


class ToolError(LTBoxError):
    pass


class DeviceError(LTBoxError):
    pass


class DeviceConnectionError(DeviceError):
    pass


class DeviceCommandError(DeviceError):
    pass


class DependencyError(LTBoxError):
    pass


class ConfigError(LTBoxError):
    pass


class ValidationError(LTBoxError):
    pass


class MissingFileError(LTBoxError):
    pass


class UserCancelError(LTBoxError):
    pass
