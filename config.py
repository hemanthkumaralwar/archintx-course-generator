"""
config.py

WHAT: Project-wide settings that stay the same from one course to the next:
      schema file, output folder, course structure (lessons per module,
      lesson length), retry limits, model, and API key.

WHY:  Course title, difficulty, and duration are NOT stored here. The user
      supplies them on each run (see user_input.py), so this file contains
      only values that do not change per course.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

from exceptions import ConfigurationError


# Load variables from a .env file (if present) into the environment.
# WHY: keeps the API key out of the source code.
load_dotenv()


# ------------------------------------------------------------
# Files and folders
# ------------------------------------------------------------

# The only input file. Every output must follow this schema.
SCHEMA_FILE = Path("course_schema.json")

# Each course gets its own subfolder inside this one.
OUTPUT_ROOT = Path("output")

# Optional overrides for the array locations. Leave as None to detect them
# automatically from the schema.
#   ARRAY_PATH:        path to the module list, such as "course.modules"
#   LESSON_ARRAY_PATH: path to the lesson list inside one module, such as "lessons"
ARRAY_PATH = None

# Set explicitly: automatic search would pick "moduleExplanation" first.
LESSON_ARRAY_PATH = "lessons"


# ------------------------------------------------------------
# Course structure
# ------------------------------------------------------------

# Accepted difficulty values. Anything else is rejected at input time.
DIFFICULTY_LEVELS = ("beginner", "intermediate", "advanced")

# Every module contains exactly this many lessons.
LESSONS_PER_MODULE = 8

# Numbered points inside each lesson's "objective" text, written as (1), (2), ...
OBJECTIVE_POINTS = 4

# Lines of code allowed in the syntax example.
SYNTAX_LINES_MIN = 2
SYNTAX_LINES_MAX = 6

# Exact item counts inside EACH lesson. Keys are paths inside a lesson.
# Card matching uses 12 cards that form 6 pairs (term and its description).
LESSON_ITEM_COUNTS = {
    "concepts": 8,                     # Core Concepts
    "quiz": 10,                        # Quiz questions
    "codereordering.codelines": 6,
    "codereordering.correctOrder": 6,
    "cardmatching.cards": 12,
    "cardmatching.matches": 6,
    "dragandropp.items": 6,
    "parts": 8,                        # Step 1 to Step 8
    "example": 5,                      # Example 1 to Example 5
    "hooklines": 2,
    "keyTakeaways": 6,
    "useCaseCards": 3,
    "lessonExplanation": 1,            # Exactly one topic block
}

# Target length of one lesson, in minutes. The prompt asks for this range.
LESSON_MINUTES_MIN = 25
LESSON_MINUTES_MAX = 30

# Minutes used to convert the requested hours into a module count.
# Using the top of the range means the course is never shorter than the
# requested hours. Shorter lessons would make the course a little shorter.
PLANNING_LESSON_MINUTES = LESSON_MINUTES_MAX

# Safety limits on the number of modules, so an accidental very large
# duration does not start hundreds of API calls.
MIN_MODULES = 2
MAX_MODULES = 30


# ------------------------------------------------------------
# Generation settings
# ------------------------------------------------------------

# Attempts per request before the run stops.
MAX_RETRIES = 3

# Base wait between attempts. It grows with each attempt.
RETRY_DELAY_SECONDS = 2

# Lower values give more predictable output. Gemini accepts 0 to 2.
TEMPERATURE = 0.3


# ------------------------------------------------------------
# Gemini credentials and model
# ------------------------------------------------------------

API_KEY = os.getenv("GEMINI_API_KEY")
MODEL = os.getenv("GEMINI_MODEL", "gemini-flash-latest")


def validate_config():
    """
    WHAT: Checks that every setting is usable before any API call is made.

    WHY:  A missing key or schema should stop the run in seconds, not after
          several paid requests.

    RAISES:
        ConfigurationError: if a setting or the schema file is invalid.
    """
    if not API_KEY:
        raise ConfigurationError(
            "GEMINI_API_KEY is missing. Add it to your .env file."
        )

    if not SCHEMA_FILE.is_file():
        raise ConfigurationError(f"Schema file not found: {SCHEMA_FILE}")

    for name, value in (("ARRAY_PATH", ARRAY_PATH), ("LESSON_ARRAY_PATH", LESSON_ARRAY_PATH)):
        if value is not None and not str(value).strip():
            raise ConfigurationError(f"{name} is set but empty. Use None or a path.")

    if not 1 <= SYNTAX_LINES_MIN <= SYNTAX_LINES_MAX:
        raise ConfigurationError(
            f"SYNTAX_LINES_MIN/MAX are invalid: {SYNTAX_LINES_MIN}-{SYNTAX_LINES_MAX}."
        )

    if LESSONS_PER_MODULE < 1:
        raise ConfigurationError(
            f"LESSONS_PER_MODULE must be at least 1 (got {LESSONS_PER_MODULE})."
        )

    for item_path, count in LESSON_ITEM_COUNTS.items():
        if not isinstance(count, int) or count < 1:
            raise ConfigurationError(
                f"LESSON_ITEM_COUNTS['{item_path}'] must be a whole number of at least 1."
            )

    if not 1 <= LESSON_MINUTES_MIN <= LESSON_MINUTES_MAX:
        raise ConfigurationError(
            f"Lesson length range is invalid: {LESSON_MINUTES_MIN}-{LESSON_MINUTES_MAX} minutes."
        )

    if not LESSON_MINUTES_MIN <= PLANNING_LESSON_MINUTES <= LESSON_MINUTES_MAX:
        raise ConfigurationError(
            "PLANNING_LESSON_MINUTES must be within the lesson length range."
        )

    if not 1 <= MIN_MODULES <= MAX_MODULES:
        raise ConfigurationError(
            f"Module limits are invalid: MIN_MODULES={MIN_MODULES}, "
            f"MAX_MODULES={MAX_MODULES}."
        )

    if MAX_RETRIES < 1:
        raise ConfigurationError(f"MAX_RETRIES must be at least 1 (got {MAX_RETRIES}).")

    if RETRY_DELAY_SECONDS < 0:
        raise ConfigurationError(
            f"RETRY_DELAY_SECONDS cannot be negative (got {RETRY_DELAY_SECONDS})."
        )

    if not 0 <= TEMPERATURE <= 2:
        raise ConfigurationError(
            f"TEMPERATURE must be between 0 and 2 (got {TEMPERATURE})."
        )
