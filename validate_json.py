"""
validate_json.py

WHAT: Checks a course JSON file against a JSON Schema and reports every place
      where the structure, keys, or data types do not match.

WHY:  The validator contains no subject-specific code. Any course that has a
      matching schema can be checked, so one script serves every subject.

USAGE:
    python validate_json.py javascript_beginner.json course_schema.json
    python validate_json.py my_course.json schema.json --max-errors 20

OPTIONS:
    --max-errors   How many problems to print. Default: 50. The total is always shown.

EXIT CODES:
    0  the course matches the schema
    1  the course does not match (problems are listed)
    2  a file could not be read, or the schema itself is invalid

REQUIRES:
    jsonschema (listed in requirements.txt)
"""

import argparse
import json
import sys
from pathlib import Path

from jsonschema import validators
from jsonschema.exceptions import SchemaError


def load_json_file(path):
    """
    WHAT: Read and parse one JSON file.

    RAISES:
        SystemExit: with exit code 2, if the file is missing or not valid JSON.
    """
    try:
        with Path(path).open("r", encoding="utf-8") as file:
            return json.load(file)
    except FileNotFoundError:
        print(f"ERROR: file not found: {path}", file=sys.stderr)
        raise SystemExit(2)
    except json.JSONDecodeError as exc:
        print(f"ERROR: {path} is not valid JSON (line {exc.lineno}): {exc.msg}", file=sys.stderr)
        raise SystemExit(2)


def build_validator(schema):
    """
    WHAT: Create a validator for the schema, using the draft it declares.

    WHY:  Schemas state their draft in "$schema". Using that draft means the
          rules match what the schema author intended. Draft 2020-12 is used
          when no draft is given.

    RAISES:
        SystemExit: with exit code 2, if the schema itself is invalid.
    """
    validator_class = validators.validator_for(schema, default=validators.Draft202012Validator)

    try:
        validator_class.check_schema(schema)
    except SchemaError as exc:
        print(f"ERROR: the schema is not valid: {exc.message}", file=sys.stderr)
        raise SystemExit(2)

    return validator_class(schema)


def format_location(error):
    """
    WHAT: Turn the path to a problem into a readable location.

    WHY:  "course.modules[0].lessons[2].title" points to the exact field. A
          problem at the top of the file is shown as "(top level)".
    """
    location = ""

    for part in error.absolute_path:
        if isinstance(part, int):
            location += f"[{part}]"
        else:
            location += f".{part}" if location else str(part)

    return location or "(top level)"


def collect_errors(validator, data):
    """
    WHAT: Find every problem in the data, sorted by location.

    WHY:  Sorting by location groups related problems together, which makes
          them easier to read and fix.

    RETURNS:
        A list of jsonschema error objects.
    """
    errors = list(validator.iter_errors(data))
    return sorted(errors, key=lambda error: format_location(error))


def report(errors, max_errors):
    """
    WHAT: Print the problems, up to max_errors, and the total count.

    RETURNS:
        Nothing. The caller decides the exit code.
    """
    for number, error in enumerate(errors[:max_errors], start=1):
        print(f"{number:>3}. {format_location(error)}")
        print(f"      {error.message}")

    if len(errors) > max_errors:
        print(f"... and {len(errors) - max_errors} more problem(s). Use --max-errors to see more.")

    print(f"\nTotal problems: {len(errors)}")


def parse_arguments(argv=None):
    """
    WHAT: Read the command-line options.
    """
    parser = argparse.ArgumentParser(
        description="Check a course JSON file against a JSON Schema."
    )
    parser.add_argument("course", help="The course JSON file to check")
    parser.add_argument("schema", help="The JSON Schema file to check against")
    parser.add_argument(
        "--max-errors",
        type=int,
        default=50,
        help="How many problems to print (default: 50)",
    )
    return parser.parse_args(argv)


def main(argv=None):
    """
    WHAT: Validate the course against the schema and report the result.

    RETURNS:
        0 if valid, 1 if problems were found, 2 if a file could not be used.
    """
    args = parse_arguments(argv)

    schema = load_json_file(args.schema)
    course = load_json_file(args.course)

    validator = build_validator(schema)
    errors = collect_errors(validator, course)

    if not errors:
        print(f"VALID: {args.course} matches {args.schema}.")
        return 0

    print(f"INVALID: {args.course} does not match {args.schema}.\n")
    report(errors, args.max_errors)
    return 1


if __name__ == "__main__":
    sys.exit(main())
