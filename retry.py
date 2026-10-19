"""
retry.py

WHAT: One reusable retry loop for every Gemini step (outline, details, modules).

WHY:  Gemini sometimes returns invalid JSON, breaks a rule, or a request
      fails. Retrying with the previous problems listed in the prompt often
      fixes the result. Writing the loop once means every step gets the same
      behaviour.
"""

import time

from config import MAX_RETRIES, RETRY_DELAY_SECONDS
from exceptions import GenerationError, ValidationFailedError


def run_with_retries(label, attempt_fn):
    """
    WHAT: Call attempt_fn until it succeeds or the attempts run out.

    HOW:  attempt_fn(previous_errors, attempt_number) is called each time.
          If it fails, its errors (or the exception text) become
          previous_errors for the next attempt. The wait grows with each
          attempt to ease rate limits.

    WHY:  The function receives the errors as an argument, not from shared
          state, so each attempt starts clean.

    RETURNS:
        Whatever attempt_fn returns on success.

    RAISES:
        GenerationError: after the last attempt fails.
    """
    previous_errors = []

    for attempt_number in range(1, MAX_RETRIES + 1):
        try:
            return attempt_fn(previous_errors, attempt_number)

        except Exception as exc:
            print(f"{label}: attempt {attempt_number}/{MAX_RETRIES} failed: {exc}")

            if attempt_number == MAX_RETRIES:
                raise GenerationError(
                    f"{label} failed after {MAX_RETRIES} attempts. "
                    f"Last error: {exc}"
                ) from exc

            # Validation failures carry a detailed list; anything else is
            # described by its message.
            if isinstance(exc, ValidationFailedError) and exc.errors:
                previous_errors = list(exc.errors)
            else:
                previous_errors = [str(exc)]

            time.sleep(RETRY_DELAY_SECONDS * attempt_number)

    # The loop always returns or raises above. This is a safety net only.
    raise GenerationError(f"{label}: retry loop ended unexpectedly.")
