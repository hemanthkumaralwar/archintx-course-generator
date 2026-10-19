"""
generate_schema.py

WHAT: Reads one or more existing course JSON files and writes a JSON Schema
      that describes their structure and data types.

WHY:  A schema written by hand has to be rewritten for every subject. This
      script infers it from an example course, so the same schema workflow
      works for any subject. The schema can then be used by validate_json.py.

HOW:  Every value in the example is checked for its type. Objects get their
      keys as properties. A key that appears in every object is required. Arrays
      get an "items" schema built from all of their elements. A value that is
      sometimes a string and sometimes null becomes a schema that allows both.

USAGE:
    python generate_schema.py javascript_beginner.json
    python generate_schema.py javascript_beginner.json -o course_schema.json
    python generate_schema.py course_a.json course_b.json        # merge examples
    python generate_schema.py javascript_beginner.json --fix-counts
    python generate_schema.py javascript_beginner.json --open

OPTIONS:
    -o, --output     Where to save the schema. Default: <first_input>.schema.json
    --title          Title stored in the schema. Default: first input's file name.
    --fix-counts     Lock array sizes to the sizes seen in the examples (for example,
                     exactly 8 lessons). Off by default, so the schema stays general.
    --open           Allow keys that are not in the examples. By default, unknown
                     keys are rejected (additionalProperties: false).

EXIT CODES:
    0  schema written
    2  an input file could not be read or is not valid JSON
"""

import argparse
import json
import sys
from pathlib import Path

SCHEMA_DRAFT = "https://json-schema.org/draft/2020-12/schema"

# Kinds that have no nested structure.
SCALAR_KINDS = ("null", "boolean", "integer", "number", "string")

# Order used when listing several scalar types, so output is stable.
SCALAR_ORDER = ("null", "boolean", "integer", "number", "string")


class Options:
    """
    WHAT: The settings that control how the schema is built.

    WHY:  Passing one object keeps the recursive functions short.
    """

    def __init__(self, fix_counts=False, closed=True):
        self.fix_counts = fix_counts   # Lock array sizes to the observed size.
        self.closed = closed           # Reject keys that were not in the examples.


def kind_of(value):
    """
    WHAT: Return the JSON type name of a value (object, array, string, and so on).

    WHY:  JSON Schema uses these names. Python's own names (dict, list, str)
          are different, so they are converted here.

    RAISES:
        TypeError: if the value is not a JSON type (not expected from json.load).
    """
    if value is None:
        return "null"
    if isinstance(value, bool):
        # Checked before int, because bool is a subclass of int in Python.
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    raise TypeError(f"Unsupported value type: {type(value).__name__}")


def infer(values, options):
    """
    WHAT: Build a schema that describes every value in a list of examples.

    WHY:  Several examples of the same field can disagree (for example, one
          lesson has a string where another has null). The schema must allow
          all of them, so the types are combined here.

    RETURNS:
        A schema dict. An empty dict means "any value" (no examples were given).
    """
    groups = {}

    for value in values:
        groups.setdefault(kind_of(value), []).append(value)

    # 1 and 1.5 are both numbers in JSON Schema, so the two kinds are merged.
    if "integer" in groups and "number" in groups:
        groups["number"] = groups.pop("integer") + groups["number"]

    if not groups:
        return {}

    schemas = []

    scalar_types = [kind for kind in SCALAR_ORDER if kind in groups]

    if scalar_types:
        schemas.append(
            {"type": scalar_types[0]} if len(scalar_types) == 1 else {"type": scalar_types}
        )

    if "object" in groups:
        schemas.append(infer_object(groups["object"], options))

    if "array" in groups:
        schemas.append(infer_array(groups["array"], options))

    return schemas[0] if len(schemas) == 1 else {"anyOf": schemas}


def infer_object(objects, options):
    """
    WHAT: Build the schema for a group of objects.

    WHY:  Each key becomes a property. A key is required only if it appears in
          every object, so optional fields (such as a diagram that some lessons
          have and others do not) are not required.

    RETURNS:
        An object schema with "properties", "required", and, unless --open is
        used, "additionalProperties": false.
    """
    keys = []

    for obj in objects:
        for key in obj:
            if key not in keys:
                keys.append(key)

    properties = {
        key: infer([obj[key] for obj in objects if key in obj], options)
        for key in keys
    }

    required = [key for key in keys if all(key in obj for obj in objects)]

    schema = {"type": "object", "properties": properties}

    if required:
        schema["required"] = required

    if options.closed:
        schema["additionalProperties"] = False

    return schema


def infer_array(arrays, options):
    """
    WHAT: Build the schema for a group of arrays.

    WHY:  The "items" schema is built from every element of every array, so a
          list of lessons, for example, describes the typical lesson. With
          --fix-counts, the size is fixed only if every example has the same size.

    RETURNS:
        An array schema. An empty "items" dict means the elements are not
        described, because no example elements were available.
    """
    elements = [item for array in arrays for item in array]

    schema = {"type": "array"}
    schema["items"] = infer(elements, options) if elements else {}

    if options.fix_counts:
        lengths = {len(array) for array in arrays}

        if len(lengths) == 1:
            size = lengths.pop()
            schema["minItems"] = size
            schema["maxItems"] = size

    return schema


def generate_schema(documents, title, options):
    """
    WHAT: Build the complete schema from one or more example documents.

    WHY:  With several examples, the schema is the one that all of them satisfy.
          A key that is missing from any example becomes optional.

    RETURNS:
        A complete JSON Schema dict with $schema and title.
    """
    schema = {"$schema": SCHEMA_DRAFT, "title": title}
    schema.update(infer(documents, options))
    return schema


def load_json_file(path):
    """
    WHAT: Read and parse one JSON file.

    RAISES:
        SystemExit: with a readable message and exit code 2, if the file cannot
                    be read or is not valid JSON.
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


def parse_arguments(argv=None):
    """
    WHAT: Read the command-line options.
    """
    parser = argparse.ArgumentParser(
        description="Generate a JSON Schema from one or more example course JSON files."
    )
    parser.add_argument("inputs", nargs="+", help="Example course JSON file(s)")
    parser.add_argument("-o", "--output", help="Where to save the schema")
    parser.add_argument("--title", help="Title to store in the schema")
    parser.add_argument(
        "--fix-counts",
        action="store_true",
        help="Lock array sizes to the sizes seen in the examples",
    )
    parser.add_argument(
        "--open",
        action="store_true",
        help="Allow keys that are not in the examples",
    )
    return parser.parse_args(argv)


def main(argv=None):
    """
    WHAT: Read the inputs, build the schema, and write it to a file.

    RETURNS:
        An exit code: 0 on success, 2 if an input could not be read.
    """
    args = parse_arguments(argv)

    documents = [load_json_file(path) for path in args.inputs]

    first = Path(args.inputs[0])
    output = Path(args.output) if args.output else first.with_name(first.stem + ".schema.json")
    title = args.title or first.stem

    options = Options(fix_counts=args.fix_counts, closed=not args.open)
    schema = generate_schema(documents, title, options)

    output.parent.mkdir(parents=True, exist_ok=True)

    with output.open("w", encoding="utf-8") as file:
        json.dump(schema, file, indent=2, ensure_ascii=False)
        file.write("\n")

    print(f"Schema written to: {output.resolve()}")
    print(f"Built from {len(documents)} example file(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
