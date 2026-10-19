"""
main.py

WHAT: The entry point. Run it with either:
        python main.py
        python main.py --title "Intro to AI Engineering" --difficulty beginner --duration 31

WHY:  Keeping this file small makes the program start in one obvious place.
      It also decides how errors are shown: a short message for expected
      problems, and a full traceback only for unexpected bugs.
"""

import sys

from exceptions import CourseGenerationError
from pipeline import run_pipeline
from user_input import read_course_request


def main(argv=None):
    """
    WHAT: Collect input, run the pipeline, and return an exit code.

    WHY:  Exit codes let scripts detect failure.
          0   success
          1   an expected error (shown as a short message)
          130 the user pressed Ctrl+C (progress is kept, so rerun to resume)

    RETURNS:
        An integer exit code.
    """
    try:
        request = read_course_request(argv)
        run_pipeline(request)
        return 0

    except CourseGenerationError as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        return 1

    except KeyboardInterrupt:
        print(
            "\nInterrupted. Saved modules are kept; rerun with the same "
            "title, difficulty, and duration to resume.",
            file=sys.stderr,
        )
        return 130


if __name__ == "__main__":
    sys.exit(main())
