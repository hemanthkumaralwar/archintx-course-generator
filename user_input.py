"""
user_input.py

WHAT: Collects the three values the user supplies (course title, difficulty
      level, and total duration in hours). They can be passed as command-line
      flags, or the program asks for any that are missing. The values are
      validated and packed into a CourseRequest, which also works out the
      module count and file paths.

WHY:  Validating once, at the entrance, means the rest of the code can
      trust the values. The hours-to-modules calculation lives in one place
      so the rules are easy to find and change.
"""

import argparse
import math
import re
from dataclasses import dataclass

from config import (
    DIFFICULTY_LEVELS,
    LESSON_MINUTES_MAX,
    LESSON_MINUTES_MIN,
    LESSONS_PER_MODULE,
    MAX_MODULES,
    MIN_MODULES,
    OUTPUT_ROOT,
    PLANNING_LESSON_MINUTES,
)
from exceptions import ConfigurationError


# Titles longer than this are rejected. Very long titles make awkward file names.
MAX_TITLE_LENGTH = 120


def slugify(text):
    """
    WHAT: Turn a course title into a safe name for folders and files.

    WHY:  Spaces and punctuation cause problems in paths on some systems.
          "AI Engineer: Beginner" becomes "ai_engineer_beginner".

    RAISES:
        ConfigurationError: if the text contains no letters or digits.
    """
    slug = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")

    if not slug:
        raise ConfigurationError(
            f"Title '{text}' must contain at least one letter or digit."
        )

    return slug


@dataclass(frozen=True)
class CourseRequest:
    """
    WHAT: The validated user input for one course, plus derived values and paths.

    WHY:  frozen=True prevents accidental changes after validation. The
          properties mean every part of the program gets the module count,
          lesson count, and file paths from one source.
    """

    title: str
    difficulty: str
    duration_hours: float
    course_id_override: object = None   # Optional --course-id value (None = build from title).

    @property
    def lessons_per_module(self):
        """Fixed number of lessons in every module (from config.py)."""
        return LESSONS_PER_MODULE

    @property
    def module_count(self):
        """
        Number of modules needed to fill the requested hours.

        HOW:  Each module lasts lessons × planned lesson minutes. The hours
              are converted to minutes and divided by that length. The result
              is rounded UP, so the course is never shorter than requested.

        EXAMPLE: 31 hours, 8 lessons, 30 minutes each.
                 31 × 60 = 1860 minutes; 8 × 30 = 240 minutes per module;
                 1860 / 240 = 7.75, which rounds up to 8 modules.
        """
        minutes_per_module = self.lessons_per_module * PLANNING_LESSON_MINUTES
        total_minutes = round(self.duration_hours * 60, 6)  # avoids float noise
        return math.ceil(total_minutes / minutes_per_module)

    @property
    def slug(self):
        """Safe name used for this course's folder and file names."""
        return slugify(self.title)

    @property
    def course_id(self):
        """
        WHAT: The course identifier in the sample's format, such as
              "javascript-beginner-v1".

        WHY:  The code sets this ID (and the module and lesson IDs built from
              it), so IDs are always consistent instead of depending on the model.
        """
        if self.course_id_override:
            return self.course_id_override

        return f"{self.slug.replace('_', '-')}-{self.difficulty}-v1"

    @property
    def level_display(self):
        """The level as shown in the course, such as "Beginner"."""
        return self.difficulty.capitalize()

    @property
    def total_duration_text(self):
        """The total duration as shown in the course, such as "31 hours"."""
        return f"{self.duration_hours:g} hours"

    @property
    def output_dir(self):
        """Folder that holds every file for this course."""
        return OUTPUT_ROOT / self.slug

    @property
    def output_file(self):
        """The course JSON that is built and validated."""
        return self.output_dir / f"{self.slug}.json"

    @property
    def plan_file(self):
        """Saved module titles, so a resumed run keeps the same outline."""
        return self.output_dir / f"{self.slug}_plan.json"

    @property
    def error_dir(self):
        """Folder for module attempts that failed validation."""
        return self.output_dir / "errors"

    def as_dict(self):
        """
        WHAT: Return the user-supplied values as a plain dictionary.

        WHY:  The plan file stores these values, so a resume can confirm it
              is continuing the same course.
        """
        return {
            "title": self.title,
            "difficulty": self.difficulty,
            "duration_hours": self.duration_hours,
        }


def make_request(title, difficulty, duration, course_id=None):
    """
    WHAT: Validate raw input and return a CourseRequest.

    WHY:  Checks every value before any API call. Each rule has its own
          message so the user knows exactly what to fix.

    RAISES:
        ConfigurationError: if a value is empty, unknown, or out of range.
    """
    clean_title = str(title or "").strip()

    if not clean_title:
        raise ConfigurationError("Course title cannot be empty.")

    if len(clean_title) > MAX_TITLE_LENGTH:
        raise ConfigurationError(
            f"Course title is too long (maximum {MAX_TITLE_LENGTH} characters)."
        )

    # Raises if the title has no usable characters.
    slugify(clean_title)

    clean_difficulty = str(difficulty or "").strip().lower()

    if clean_difficulty not in DIFFICULTY_LEVELS:
        raise ConfigurationError(
            "Difficulty must be one of: "
            + ", ".join(DIFFICULTY_LEVELS)
            + f" (got '{difficulty}')."
        )

    # float() accepts whole and decimal numbers, such as 31 or 31.5.
    try:
        hours = float(str(duration).strip())
    except (TypeError, ValueError) as exc:
        raise ConfigurationError(
            f"Duration must be a number of hours, for example 31 (got '{duration}')."
        ) from exc

    if not math.isfinite(hours) or hours <= 0:
        raise ConfigurationError("Duration must be a positive number of hours.")

    request = CourseRequest(
        title=clean_title,
        difficulty=clean_difficulty,
        duration_hours=hours,
        course_id_override=(str(course_id).strip() or None) if course_id else None,
    )

    if not MIN_MODULES <= request.module_count <= MAX_MODULES:
        raise ConfigurationError(
            f"{hours:g} hours gives {request.module_count} modules. "
            f"Choose a duration that gives between {MIN_MODULES} and "
            f"{MAX_MODULES} modules."
        )

    return request


def parse_arguments(argv=None):
    """
    WHAT: Read optional command-line flags.

    WHY:  Flags let the user skip the prompts, which is useful for scripts
          and repeated runs. Values that are not given are asked for later.
    """
    parser = argparse.ArgumentParser(
        description=(
            "Generate a course that follows course_schema.json. "
            "Any value you leave out will be asked for."
        )
    )
    parser.add_argument("--title", help="Course title")
    parser.add_argument(
        "--difficulty",
        help=f"Difficulty level: {', '.join(DIFFICULTY_LEVELS)}",
    )
    parser.add_argument(
        "--course-id",
        help="Optional course ID, for example javascript-beginner-v1",
    )
    parser.add_argument(
        "--duration",
        help="Total course duration in hours, for example 31",
    )
    return parser.parse_args(argv)


def ask(question, value):
    """
    WHAT: Return the value if it was supplied, otherwise ask the user.

    WHY:  Lets flags and prompts work together. If input is not available
          (for example, a closed input stream), the error explains the
          alternative.

    RAISES:
        ConfigurationError: if the program needs input but none is available.
    """
    if value is not None:
        return value

    try:
        return input(question)
    except EOFError as exc:
        raise ConfigurationError(
            "No input available. Pass --title, --difficulty, and "
            "--duration on the command line."
        ) from exc


def read_course_request(argv=None):
    """
    WHAT: Gather the three inputs and return a validated CourseRequest.

    WHY:  This is the single entry point for user input. main.py calls only
          this function.

    RETURNS:
        A validated CourseRequest.

    RAISES:
        ConfigurationError: if any value is invalid or input is unavailable.
    """
    args = parse_arguments(argv)

    title = ask("Course title: ", args.title)
    difficulty = ask(f"Difficulty ({'/'.join(DIFFICULTY_LEVELS)}): ", args.difficulty)
    duration = ask("Total duration in hours: ", args.duration)

    return make_request(title, difficulty, duration, args.course_id)
