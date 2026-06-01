"""Domain exceptions for CAflow AI."""


class CAflowError(Exception):
    """Base exception."""


class NotFoundError(CAflowError):
    def __init__(self, entity: str, id: str):
        super().__init__(f"{entity} not found: {id}")
        self.entity = entity
        self.id = id


class PermissionDeniedError(CAflowError):
    def __init__(self, action: str, resource: str):
        super().__init__(f"Permission denied: cannot {action} {resource}")
        self.action = action
        self.resource = resource


class ValidationError(CAflowError):
    def __init__(self, field: str, message: str):
        super().__init__(f"Validation error on {field}: {message}")
        self.field = field
