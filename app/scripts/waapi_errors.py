"""
WAAPI Client Error Classes

Low-level errors for WAAPI connection, dispatcher, and transport.
These are infrastructure-level errors.
"""


class WaapiError(Exception):
    """Base exception for WAAPI client infrastructure"""
    pass


class WaapiConnectionError(WaapiError):
    """Failed to connect to or communicate with Wwise"""
    def __init__(self, message: str, url: str | None = None):
        super().__init__(message)
        self.url = url


class WaapiNotConnectedError(WaapiError):
    """WAAPI client is not connected"""
    pass


class WaapiReconnectingError(WaapiError):
    """WAAPI is currently reconnecting"""
    pass


class WaapiDispatcherError(WaapiError):
    """WAAPI dispatcher thread error"""
    pass


class WaapiQueueFullError(WaapiError):
    """WAAPI queue is full - backpressure limit reached"""
    def __init__(self, message: str, queue_size: int, max_size: int):
        super().__init__(message)
        self.queue_size = queue_size
        self.max_size = max_size


class WaapiTimeoutError(WaapiError):
    """WAAPI call timed out"""
    def __init__(self, message: str, uri: str, timeout: float):
        super().__init__(message)
        self.uri = uri
        self.timeout = timeout


class WaapiCallError(WaapiError):
    """WAAPI call failed at transport level"""
    def __init__(self, message: str, uri: str, original_error: Exception | None = None):
        super().__init__(message)
        self.uri = uri
        self.original_error = original_error