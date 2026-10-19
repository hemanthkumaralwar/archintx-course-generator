"""
exceptions.py

WHAT: Custom exception classes used across the project.

WHY:  Each kind of expected failure has its own name. main.py can print a
      short message for known problems, while unexpected Python errors
      (real bugs) still show a full traceback.
"""


class CourseGenerationError(Exception):
    """Base class for every expected error in this project."""


class ConfigurationError(CourseGenerationError):
    """A setting, user input value, or required file is missing or invalid."""


class JSONFileError(CourseGenerationError):
    """A JSON file could not be found, read, parsed, or written."""


class DataPathError(CourseGenerationError):
    """A dot path such as 'course.modules' does not match the data."""


class SchemaError(CourseGenerationError):
    """course_schema.json is missing a required path or is not valid JSON Schema."""


class ValidationFailedError(CourseGenerationError):
    """Generated content does not match the schema.

    The `errors` list is sent back to Gemini on the next attempt, so the
    model can correct its own mistakes.
    """

    def __init__(self, message, errors=None):
        super().__init__(message)
        self.errors = list(errors or [])


class GenerationError(CourseGenerationError):
    """Gemini could not produce usable output, even after retries."""


class CheckpointError(CourseGenerationError):
    """The saved plan or output is incomplete or does not match this request."""
