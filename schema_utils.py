"""
schema_utils.py

WHAT: Works only from course_schema.json. It builds one schema for each
      kind of generation step:
        - course details: the course with an empty module list,
        - module overview: one module with an empty lesson list,
        - one lesson: the lesson item schema with exact item counts.

WHY:  Lessons are generated one at a time, so each request needs a schema
      for one small piece. Gemini is sent versions without fixed counts,
      because large fixed counts make the request too complex. Exact counts
      are enforced locally by the validators, and retries carry the errors
      back to Gemini.
"""

from collections import deque
from copy import deepcopy
from dataclasses import dataclass

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError as JsonSchemaError

from exceptions import SchemaError
from json_utils import parse_path


@dataclass(frozen=True)
class SchemaSet:
    """
    WHAT: Every schema, request version, and validator needed for one run.

    WHY:  The pipeline passes one object instead of many separate values.
          Each "request" schema is sent to Gemini. Each "validator" checks
          the result locally, with the full counts applied.
    """

    array_path: str                        # Module list location, e.g. "course.modules".
    lesson_path: str                       # Lesson list location inside a module, e.g. "lessons".

    course_validator: Draft202012Validator # Whole course, checked at the end.

    details_request: dict                  # Course details, module list empty.
    details_validator: Draft202012Validator

    overview_request: dict                 # One module overview, lesson list empty.
    overview_validator: Draft202012Validator

    lesson_request: dict                   # One lesson, no fixed counts (sent to Gemini).
    lesson_validator: Draft202012Validator # One lesson, with exact counts (validation only).

    course_id_path: object = None          # Where courseId sits in the course, e.g. "course.courseId".
    course_field_paths: object = None      # Paths of courseTitle, level, totalDuration, courseId (or None if absent).


def schema_node_at(root, parts, path_text):
    """
    WHAT: Follow a list of names through a schema's 'properties' and return
          the schema node at the end.

    RAISES:
        SchemaError: if a name is missing from the schema.
    """
    current = root

    for part in parts:
        properties = current.get("properties") if isinstance(current, dict) else None

        if not isinstance(properties, dict) or part not in properties:
            raise SchemaError(f"Schema path '{path_text}' not found at '{part}'.")

        current = properties[part]

    return current


def find_array_path(schema, label):
    """
    WHAT: Search a schema for the first array whose items are objects, and
          return its dot path.

    WHY:  Finds the module and lesson lists without manual paths. The search
          is breadth-first, so the shallowest array wins.

    NOTE: For modules, this can pick the wrong array, such as
          'moduleExplanation'. config.py sets LESSON_ARRAY_PATH to avoid this.

    RAISES:
        SchemaError: if no array of objects exists in the schema.
    """
    if not isinstance(schema, dict):
        raise SchemaError(f"The {label} must be a JSON object.")

    queue = deque([(schema, [])])

    while queue:
        node, prefix = queue.popleft()
        properties = node.get("properties") if isinstance(node, dict) else None

        if not isinstance(properties, dict):
            continue

        for name, child in properties.items():
            if not isinstance(child, dict):
                continue

            items = child.get("items")
            is_object_array = (
                child.get("type") == "array"
                and isinstance(items, dict)
                and (items.get("type") == "object" or "properties" in items)
            )

            if is_object_array:
                return ".".join(prefix + [name])

            queue.append((child, prefix + [name]))

    raise SchemaError(
        f"No array of objects was found in the {label}. "
        "Set the matching path override in config.py."
    )


def get_array_schema(schema, path_text):
    """
    WHAT: Return the 'items' schema of the array at path_text.

    RAISES:
        SchemaError: if the path is missing, is not an array, or has no items.
    """
    node = schema_node_at(schema, parse_path(path_text), path_text)

    if not isinstance(node, dict) or node.get("type") != "array":
        raise SchemaError(f"'{path_text}' does not point to an array in the schema.")

    if "items" not in node:
        raise SchemaError(f"The array at '{path_text}' has no 'items' schema.")

    return node["items"]


def find_property_path(schema, name):
    """
    WHAT: Find the dot path of the first property with this name, searching
          breadth-first through objects (not into array items).

    WHY:  courseId is a course-level field, so it sits inside the "course"
          object, not at the top of the file. Searching the schema avoids
          hard-coding that location.

    RETURNS:
        The dot path such as "course.courseId", or None if the schema has no
        such property.
    """
    if not isinstance(schema, dict):
        return None

    queue = deque([(schema, [])])

    while queue:
        node, prefix = queue.popleft()
        properties = node.get("properties") if isinstance(node, dict) else None

        if not isinstance(properties, dict):
            continue

        if name in properties:
            return ".".join(prefix + [name])

        for key, child in properties.items():
            if isinstance(child, dict):
                queue.append((child, prefix + [key]))

    return None


def fix_array_count(array_node, label, count):
    """
    WHAT: Change an array schema in place so it must contain exactly count items.

    WHY:  minItems and maxItems set to the same value fix the size.

    RAISES:
        SchemaError: if the node is not an array schema.
    """
    if not isinstance(array_node, dict) or array_node.get("type") != "array":
        raise SchemaError(f"'{label}' does not point to an array in the schema.")

    array_node["minItems"] = count
    array_node["maxItems"] = count


def set_array_length(schema, path_text, count):
    """
    WHAT: Return a copy of the schema where the array at path_text must
          contain exactly count items.

    WHY:  Used to set a list to 0 (for example the module list in the details
          step, or the lesson list in the module overview step).
    """
    result = deepcopy(schema)
    node = schema_node_at(result, parse_path(path_text), path_text)
    fix_array_count(node, path_text, count)
    return result


def strip_array_counts(schema):
    """
    WHAT: Return a copy of the schema with every minItems and maxItems removed.

    WHY:  Fixed counts make the schema too complex for Gemini, which then
          rejects the request with 400 INVALID_ARGUMENT. The counts are still
          enforced by the local validators.
    """
    if isinstance(schema, dict):
        return {
            key: strip_array_counts(value)
            for key, value in schema.items()
            if key not in ("minItems", "maxItems")
        }

    if isinstance(schema, list):
        return [strip_array_counts(item) for item in schema]

    return schema


def apply_item_counts(item_schema, item_counts):
    """
    WHAT: Fix the exact size of arrays inside one item schema.

    WHY:  Used for the lesson, where quiz, concepts, cards, and so on must
          have exact sizes. item_counts maps dotted paths to counts, for
          example "cardmatching.cards": 6.

    RAISES:
        SchemaError: if a path is missing or is not an array.
    """
    for item_path, count in item_counts.items():
        node = schema_node_at(item_schema, parse_path(item_path), item_path)
        fix_array_count(node, f"lesson item '{item_path}'", count)


def check_schemas(named_schemas):
    """
    WHAT: Confirm every schema is valid JSON Schema (draft 2020-12).

    RAISES:
        SchemaError: naming the first schema that is invalid.
    """
    for label, schema in named_schemas.items():
        try:
            Draft202012Validator.check_schema(schema)
        except JsonSchemaError as exc:
            raise SchemaError(
                f"The {label} is not valid JSON Schema: {exc.message}"
            ) from exc


def build_schema_set(course_schema, array_override, lesson_override, lesson_item_counts):
    """
    WHAT: Build every schema, request version, and validator for a run.

    WHY:  One function prepares everything, so the pipeline either gets a
          complete, checked set or a clear error before any API call.

    PARAMETERS:
        course_schema:      the loaded contents of course_schema.json.
        array_override:     ARRAY_PATH from config, or None to auto-detect.
        lesson_override:    LESSON_ARRAY_PATH from config, or None to auto-detect.
        lesson_item_counts: dict of dotted paths inside a lesson to exact counts.

    RAISES:
        SchemaError: if a schema is invalid or a path cannot be found.
    """
    array_path = array_override or find_array_path(course_schema, "course schema")

    raw_module = get_array_schema(course_schema, array_path)
    lesson_path = lesson_override or find_array_path(raw_module, "module schema")

    raw_lessons = schema_node_at(raw_module, parse_path(lesson_path), lesson_path)

    if not isinstance(raw_lessons, dict) or raw_lessons.get("type") != "array":
        raise SchemaError(f"'{lesson_path}' is not an array inside a module.")

    raw_lesson = raw_lessons.get("items")

    if not isinstance(raw_lesson, dict):
        raise SchemaError(f"The lessons at '{lesson_path}' have no item schema.")

    # Lesson schema with exact counts, used for validation only.
    lesson_counted = deepcopy(raw_lesson)
    apply_item_counts(lesson_counted, lesson_item_counts)

    # Module overview: the module with an empty lesson list.
    overview_schema = set_array_length(raw_module, lesson_path, 0)

    # Course details: the course with an empty module list.
    details_schema = set_array_length(course_schema, array_path, 0)

    check_schemas({
        "course schema": course_schema,
        "course details schema": details_schema,
        "module overview schema": overview_schema,
        "lesson schema": lesson_counted,
    })

    return SchemaSet(
        array_path=array_path,
        lesson_path=lesson_path,
        course_validator=Draft202012Validator(course_schema),
        details_request=strip_array_counts(details_schema),
        details_validator=Draft202012Validator(details_schema),
        overview_request=strip_array_counts(overview_schema),
        overview_validator=Draft202012Validator(overview_schema),
        lesson_request=strip_array_counts(lesson_counted),
        lesson_validator=Draft202012Validator(lesson_counted),
        course_id_path=find_property_path(course_schema, "courseId"),
        course_field_paths={
            name: find_property_path(course_schema, name)
            for name in ("courseId", "courseTitle", "level", "totalDuration")
        },
    )
