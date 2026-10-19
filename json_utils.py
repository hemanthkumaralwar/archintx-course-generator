"""
json_utils.py

WHAT: Reading, writing, and navigating JSON data with dot paths
      such as 'course.modules'.

WHY:  All file and path handling is kept here so the rest of the
      project can treat JSON as ordinary Python dicts and lists.
      Low-level errors (missing file, bad syntax, disk full) are
      converted into our own exceptions with clear messages.
"""

import json
from pathlib import Path

from exceptions import DataPathError, JSONFileError


# ------------------------------------------------------------
# File input and output
# ------------------------------------------------------------

def load_json(path):
    """
    WHAT: Read a JSON file and return the parsed Python object.

    WHY:  Wrapping the error means the message always names the file
          and, for syntax errors, the line number.

    RAISES:
        JSONFileError: if the file is missing, unreadable, or not valid JSON.
    """
    path = Path(path)

    if not path.is_file():
        raise JSONFileError(f"JSON file not found: {path}")

    try:
        with path.open("r", encoding="utf-8") as file:
            return json.load(file)

    except json.JSONDecodeError as exc:
        raise JSONFileError(
            f"Invalid JSON in {path} at line {exc.lineno}: {exc.msg}"
        ) from exc

    except OSError as exc:
        raise JSONFileError(f"Could not read {path}: {exc}") from exc


def save_json(path, data):
    """
    WHAT: Write data to a JSON file safely.

    WHY:  The data is written to a temporary file first and then renamed
          over the real file. If the program crashes mid-write, the
          previous good file is still intact. A failed temporary file
          is deleted so no stray files are left behind.

    RAISES:
        JSONFileError: if the folder cannot be created, the data cannot
                       be serialised, or the write fails.
    """
    path = Path(path)
    temp_path = path.with_name(path.name + ".tmp")

    try:
        path.parent.mkdir(parents=True, exist_ok=True)

        with temp_path.open("w", encoding="utf-8") as file:
            json.dump(data, file, indent=2, ensure_ascii=False)
            file.write("\n")

        # replace() is atomic on most systems, so readers never see
        # a half-written file.
        temp_path.replace(path)

    except (OSError, TypeError, ValueError) as exc:
        # Remove the partial temporary file, but do not hide the real error.
        try:
            if temp_path.exists():
                temp_path.unlink()
        except OSError:
            pass

        raise JSONFileError(f"Could not save JSON to {path}: {exc}") from exc


# ------------------------------------------------------------
# Dot-path navigation
# ------------------------------------------------------------

def parse_path(path_text):
    """
    WHAT: Split a dot path such as '$.course.modules' into key names.

    WHY:  Leading '$' and '.' characters are removed so both
          'course.modules' and '$.course.modules' work.

    RAISES:
        DataPathError: if the path is empty or contains no key names.
    """
    if not isinstance(path_text, str) or not path_text.strip():
        raise DataPathError(
            "A path must be a non-empty string such as 'course.modules'."
        )

    parts = [part for part in path_text.strip("$.").split(".") if part]

    if not parts:
        raise DataPathError(
            f"Path '{path_text}' does not contain any key names."
        )

    return parts


def _walk(root, parts, full_path):
    """
    WHAT: Follow a list of keys through nested dicts.

    WHY:  get_value and replace_array both need the same traversal, so it
          lives in one helper. An empty list returns root itself.

    RAISES:
        DataPathError: if any key is missing or a value is not a dict.
    """
    current = root

    for part in parts:
        if not isinstance(current, dict) or part not in current:
            raise DataPathError(
                f"Cannot find '{part}' while following '{full_path}'."
            )
        current = current[part]

    return current


def get_value(root, path_text):
    """
    WHAT: Return the value stored at a dot path.

    WHY:  Used to locate the module array inside the course file.

    RAISES:
        DataPathError: if the path does not exist in the data.
    """
    return _walk(root, parse_path(path_text), path_text)


def replace_array(root, path_text, new_array):
    """
    WHAT: Replace the array at a dot path with a new list.

    WHY:  The surrounding course metadata (title, version, and so on)
          must stay exactly as it was. Only the array changes.

    RAISES:
        DataPathError: if new_array is not a list, or the parent path
                       or final key does not exist.
    """
    if not isinstance(new_array, list):
        raise DataPathError(
            f"replace_array expects a list for '{path_text}', "
            f"got {type(new_array).__name__}."
        )

    parts = parse_path(path_text)
    parent = _walk(root, parts[:-1], path_text)
    key = parts[-1]

    if not isinstance(parent, dict) or key not in parent:
        raise DataPathError(
            f"Cannot replace '{path_text}' because '{key}' does not exist."
        )

    parent[key] = new_array
