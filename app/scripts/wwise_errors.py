"""
Wwise Python Library Error Classes

High-level errors for Wwise business logic, object manipulation,
validation, and transaction management.
"""


class WwisePyLibError(Exception):
    """Base exception for all WwisePythonLibrary operations."""
    pass


class WwiseValidationError(WwisePyLibError):
    """Raised when input validation fails."""
    def __init__(self, message: str, field: str | None = None, value=None):
        super().__init__(message)
        self.field = field
        self.value = value


class WwiseObjectError(WwisePyLibError):
    """Base for object-related errors."""
    pass


class WwiseObjectNotFoundError(WwiseObjectError):
    """Raised when a Wwise object path cannot be resolved."""
    def __init__(self, message: str, path: str | None = None):
        super().__init__(message)
        self.path = path


class WwiseObjectAlreadyExistsError(WwiseObjectError):
    """Raised when attempting to create an object that already exists."""
    def __init__(self, message: str, path: str | None = None, object_id: str | None = None):
        super().__init__(message)
        self.path = path
        self.object_id = object_id


class WwiseApiError(WwisePyLibError):
    """
    Raised when WAAPI call fails at application/business logic level.
    
    Attributes:
        operation: The WAAPI operation that failed (if known).
        details: Additional context about the failure.
    """
    def __init__(
        self, 
        message: str, 
        operation: str | None = None, 
        details: dict | None = None
    ):
        super().__init__(message)
        self.operation = operation
        self.details = details or {}
    
    def __str__(self):
        """Include operation in string representation if available."""
        base = super().__str__()
        if self.operation:
            return f"[{self.operation}] {base}"
        return base


class WwiseTransactionError(WwisePyLibError):
    """Raised when partial creation occurs and cleanup is needed."""
    def __init__(self, message: str, created_objects: list[str] | None = None, failed_at: str | None = None):
        super().__init__(message)
        self.created_objects = created_objects or []
        self.failed_at = failed_at


class WwisePropertyError(WwisePyLibError):
    """Raised when property get/set operations fail."""
    def __init__(self, message: str, property_name: str | None = None, object_path: str | None = None):
        super().__init__(message)
        self.property_name = property_name
        self.object_path = object_path


class WwiseImportError(WwisePyLibError):
    """Raised when audio/asset import operations fail."""
    def __init__(self, message: str, file_path: str | None = None, import_operation: str | None = None):
        super().__init__(message)
        self.file_path = file_path
        self.import_operation = import_operation