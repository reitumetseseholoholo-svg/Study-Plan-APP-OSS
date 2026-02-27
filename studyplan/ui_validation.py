"""Professional form validation and error handling system for StudyPlan UI.

Provides:
- Field validation with custom rules
- Error state management
- Input sanitization
- Type-safe form builders
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable, Generic, TypeVar

T = TypeVar("T")


@dataclass(frozen=True)
class ValidationRule:
    """A single validation rule with error message."""
    
    name: str
    predicate: Callable[[Any], bool]
    message: str
    
    def validate(self, value: Any) -> tuple[bool, str]:
        """Validate value and return (is_valid, error_message)."""
        try:
            is_valid = self.predicate(value)
            return (is_valid, "" if is_valid else self.message)
        except Exception as e:
            return (False, f"{self.message} (validation error: {str(e)})")


@dataclass(frozen=True)
class ValidationResult:
    """Result of validation for a field."""
    
    is_valid: bool
    errors: list[str]
    warnings: list[str] = None
    
    def __post_init__(self):
        if self.warnings is None:
            object.__setattr__(self, "warnings", [])
    
    @property
    def has_errors(self) -> bool:
        """Check if there are any errors."""
        return len(self.errors) > 0
    
    @property
    def has_warnings(self) -> bool:
        """Check if there are any warnings."""
        return len(self.warnings) > 0
    
    def first_error(self) -> str:
        """Get first error message or empty string."""
        return self.errors[0] if self.errors else ""
    
    @staticmethod
    def valid() -> ValidationResult:
        """Create a valid result."""
        return ValidationResult(is_valid=True, errors=[])
    
    @staticmethod
    def invalid(message: str) -> ValidationResult:
        """Create an invalid result with single error."""
        return ValidationResult(is_valid=False, errors=[message])


class FieldValidator:
    """Fluent validator builder for form fields."""
    
    def __init__(self, value: Any = None, name: str = "field"):
        self._value = value
        self._name = name
        self._rules: list[ValidationRule] = []
    
    def required(self, message: str = "This field is required") -> FieldValidator:
        """Add required validation."""
        self._rules.append(ValidationRule(
            "required",
            lambda v: v is not None and str(v).strip() != "",
            message,
        ))
        return self
    
    def min_length(self, length: int, message: str | None = None) -> FieldValidator:
        """Validate minimum string length."""
        msg = message or f"Minimum {length} characters required"
        self._rules.append(ValidationRule(
            "min_length",
            lambda v: str(v) if v else "" and len(str(v)) >= length,
            msg,
        ))
        return self
    
    def max_length(self, length: int, message: str | None = None) -> FieldValidator:
        """Validate maximum string length."""
        msg = message or f"Maximum {length} characters allowed"
        self._rules.append(ValidationRule(
            "max_length",
            lambda v: len(str(v)) <= length,
            msg,
        ))
        return self
    
    def email(self, message: str = "Invalid email address") -> FieldValidator:
        """Validate email format."""
        pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        self._rules.append(ValidationRule(
            "email",
            lambda v: re.match(pattern, str(v)) is not None,
            message,
        ))
        return self
    
    def numeric(self, message: str = "Must be a number") -> FieldValidator:
        """Validate numeric value."""
        self._rules.append(ValidationRule(
            "numeric",
            lambda v: str(v).replace("-", "").replace(".", "").isdigit(),
            message,
        ))
        return self
    
    def min_value(self, min_val: float, message: str | None = None) -> FieldValidator:
        """Validate minimum numeric value."""
        msg = message or f"Minimum value {min_val} required"
        self._rules.append(ValidationRule(
            "min_value",
            lambda v: float(v) >= min_val,
            msg,
        ))
        return self
    
    def max_value(self, max_val: float, message: str | None = None) -> FieldValidator:
        """Validate maximum numeric value."""
        msg = message or f"Maximum value {max_val} allowed"
        self._rules.append(ValidationRule(
            "max_value",
            lambda v: float(v) <= max_val,
            msg,
        ))
        return self
    
    def pattern(self, regex: str, message: str = "Invalid format") -> FieldValidator:
        """Validate against regex pattern."""
        self._rules.append(ValidationRule(
            "pattern",
            lambda v: re.match(regex, str(v)) is not None,
            message,
        ))
        return self
    
    def custom(self, predicate: Callable[[Any], bool], message: str) -> FieldValidator:
        """Add custom validation rule."""
        self._rules.append(ValidationRule(
            "custom",
            predicate,
            message,
        ))
        return self
    
    def validate(self) -> ValidationResult:
        """Run all validation rules."""
        if not self._rules:
            return ValidationResult.valid()
        
        errors: list[str] = []
        for rule in self._rules:
            is_valid, error_msg = rule.validate(self._value)
            if not is_valid:
                errors.append(error_msg)
        
        return ValidationResult(
            is_valid=len(errors) == 0,
            errors=errors,
        )


class FormState:
    """Manages validation state for an entire form."""
    
    def __init__(self):
        self._fields: dict[str, ValidationResult] = {}
        self._touched: set[str] = set()
        self._submitted = False
    
    def set_field_result(self, field_name: str, result: ValidationResult) -> None:
        """Set validation result for a field."""
        self._fields[field_name] = result
    
    def mark_touched(self, field_name: str) -> None:
        """Mark field as touched (user has interacted with it)."""
        self._touched.add(field_name)
    
    def mark_submitted(self) -> None:
        """Mark form as submitted."""
        self._submitted = True
    
    def is_touched(self, field_name: str) -> bool:
        """Check if field was touched."""
        return field_name in self._touched
    
    def is_submitted(self) -> bool:
        """Check if form was submitted."""
        return self._submitted
    
    def get_field_result(self, field_name: str) -> ValidationResult | None:
        """Get validation result for field."""
        return self._fields.get(field_name)
    
    def get_field_error(self, field_name: str) -> str:
        """Get first error message for field."""
        result = self._fields.get(field_name)
        return result.first_error() if result else ""
    
    def should_show_error(self, field_name: str) -> bool:
        """Check if error should be shown for field."""
        # Show error if: field was touched OR form was submitted
        if not self._submitted and not self.is_touched(field_name):
            return False
        
        result = self._fields.get(field_name)
        return result and result.has_errors
    
    def is_valid(self) -> bool:
        """Check if all fields are valid."""
        return all(result.is_valid for result in self._fields.values())
    
    def get_all_errors(self) -> dict[str, str]:
        """Get all errors indexed by field name."""
        return {
            name: result.first_error()
            for name, result in self._fields.items()
            if result.has_errors
        }
    
    def reset(self) -> None:
        """Reset form state."""
        self._fields.clear()
        self._touched.clear()
        self._submitted = False


class InputSanitizer:
    """Sanitize user input to prevent injection attacks."""
    
    @staticmethod
    def sanitize_text(text: str, max_length: int = 10000) -> str:
        """Sanitize plain text input."""
        if not isinstance(text, str):
            return ""
        
        # Limit length
        text = text[:max_length]
        
        # Remove control characters but keep newlines/tabs
        text = "".join(
            c for c in text
            if c.isprintable() or c in ("\n", "\t", "\r")
        )
        
        # Strip leading/trailing whitespace
        return text.strip()
    
    @staticmethod
    def sanitize_email(email: str) -> str:
        """Sanitize email address."""
        if not isinstance(email, str):
            return ""
        
        return email.strip().lower()
    
    @staticmethod
    def sanitize_filename(filename: str) -> str:
        """Sanitize filename (remove dangerous characters)."""
        if not isinstance(filename, str):
            return ""
        
        # Remove path separators and control characters
        dangerous_chars = r'[\\/\0\n\r\t]'
        safe = re.sub(dangerous_chars, "", filename)
        
        # Remove leading dots and spaces
        safe = safe.lstrip(". ")
        
        # Limit length
        return safe[:255] if safe else "file"
    
    @staticmethod
    def escape_xml(text: str) -> str:
        """Escape XML special characters."""
        if not isinstance(text, str):
            return ""
        
        escapes = {
            "&": "&amp;",
            "<": "&lt;",
            ">": "&gt;",
            '"': "&quot;",
            "'": "&apos;",
        }
        
        return "".join(escapes.get(c, c) for c in text)


# ──────────────────────────────────────────────────────────────────────────────
# Common Validator Presets
# ──────────────────────────────────────────────────────────────────────────────

class CommonValidators:
    """Pre-configured validators for common field types."""
    
    @staticmethod
    def create_email_validator(value: str, field_name: str = "Email") -> ValidationResult:
        """Create email field validator."""
        return (
            FieldValidator(value, field_name)
            .required(f"{field_name} is required")
            .email(f"{field_name} must be a valid email address")
            .validate()
        )
    
    @staticmethod
    def create_password_validator(value: str, field_name: str = "Password") -> ValidationResult:
        """Create password field validator."""
        return (
            FieldValidator(value, field_name)
            .required(f"{field_name} is required")
            .min_length(8, f"{field_name} must be at least 8 characters")
            .validate()
        )
    
    @staticmethod
    def create_username_validator(value: str, field_name: str = "Username") -> ValidationResult:
        """Create username field validator."""
        return (
            FieldValidator(value, field_name)
            .required(f"{field_name} is required")
            .min_length(3, f"{field_name} must be at least 3 characters")
            .max_length(32, f"{field_name} must not exceed 32 characters")
            .pattern(r'^[a-zA-Z0-9_-]+$', f"{field_name} can only contain letters, numbers, underscores, and hyphens")
            .validate()
        )
    
    @staticmethod
    def create_url_validator(value: str, field_name: str = "URL") -> ValidationResult:
        """Create URL field validator."""
        return (
            FieldValidator(value, field_name)
            .required(f"{field_name} is required")
            .pattern(
                r'^https?://',
                f"{field_name} must start with http:// or https://"
            )
            .validate()
        )
    
    @staticmethod
    def create_number_validator(
        value: str | float,
        min_val: float = 0,
        max_val: float = 100,
        field_name: str = "Number"
    ) -> ValidationResult:
        """Create numeric field validator."""
        return (
            FieldValidator(value, field_name)
            .required(f"{field_name} is required")
            .numeric(f"{field_name} must be a valid number")
            .min_value(min_val, f"{field_name} must be at least {min_val}")
            .max_value(max_val, f"{field_name} must not exceed {max_val}")
            .validate()
        )
