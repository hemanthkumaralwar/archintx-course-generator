"""
validation.py

WHAT: Checks generated data against a JSON Schema and raises a
      ValidationFailedError containing readable error messages.

WHY:  Validation is needed in several places (course details, each module,
      and the final course). One shared helper keeps the error format the
      same everywhere, so retry feedback to Gemini is consistent.
"""

from exceptions import ValidationFailedError

# How many errors appear in the on-screen message. All errors are still
# kept in the exception so they can be saved and sent back to Gemini.
MAX_ERRORS_SHOWN = 20


def format_error(error):
    """
    WHAT: Turn a jsonschema error into "path: message".

    WHY:  The path shows where the problem is, for example
          "course/modules/0/title: is a required property".
          An empty path is shown as "(root)".
    """
    location = "/".join(str(part) for part in error.absolute_path) or "(root)"
    return f"{location}: {error.message}"


def collect_errors(validator, data):
    """
    WHAT: Return every validation problem as a list of strings.

    WHY:  An empty list means the data is valid.
    """
    return [format_error(error) for error in validator.iter_errors(data)]


def ensure_valid(validator, data, label):
    """
    WHAT: Raise if the data does not match the schema.

    WHY:  Raising (rather than returning a flag) means callers cannot
          forget to check. The error carries the full list of problems
          for the retry logic.

    PARAMETERS:
        validator: a jsonschema validator for the expected shape.
        data:      the parsed JSON to check.
        label:     a short name for the message, such as "Module 3".

    RAISES:
        ValidationFailedError: if any schema rule is broken.
    """
    errors = collect_errors(validator, data)

    if not errors:
        return

    shown = errors[:MAX_ERRORS_SHOWN]
    summary = "\n  ".join(shown)

    if len(errors) > MAX_ERRORS_SHOWN:
        summary += f"\n  ...and {len(errors) - MAX_ERRORS_SHOWN} more problem(s)."

    raise ValidationFailedError(
        f"{label} failed schema validation:\n  {summary}",
        errors=errors,
    )
