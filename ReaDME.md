# Course Generator

Generates a complete course as JSON using Google Gemini, following `course_schema.json`.
It also includes two general-purpose tools: one that builds a JSON Schema from an
example course, and one that checks any course JSON against a schema.

## Prerequisites

- Python 3.10 or newer
- A Google AI Studio account, with an API key from https://aistudio.google.com/apikey

## Setup

```bash
python -m venv venv
venv\Scripts\activate        # Windows
source venv/bin/activate     # macOS / Linux
pip install -r requirements.txt
```

Create a file named `.env` in this folder:

```
GEMINI_API_KEY=your_api_key_here
```

## Run

```bash
python main.py --title "AI Engineering fundamentals" --difficulty beginner --duration 31
```

## Output

The course is saved to:

```
output/<course_title>/<course_title>.json
```

If a run stops, run the same command again to continue.
To start a course over, delete its folder in `output/` first.

---

## Generate a schema from an example course

`generate_schema.py` reads an existing course JSON and writes a JSON Schema that
describes its structure and data types. Use it to create a schema for any subject
without writing one by hand.

```bash
python generate_schema.py javascript_beginner.json -o course_schema.json
```

| Option | Meaning |
|---|---|
| `-o`, `--output` | Where to save the schema. Default: `<input>.schema.json` |
| `--title` | Title stored in the schema. Default: the input file name |
| `--fix-counts` | Lock array sizes to the sizes in the example (for example, exactly 8 lessons). Off by default. |
| `--open` | Allow keys that are not in the example. By default, unknown keys are rejected. |

You can pass several example files. The schema then accepts all of them, and a key
is required only if every example has it:

```bash
python generate_schema.py course_a.json course_b.json -o course_schema.json
```

How the schema is built:

- Each key becomes a property. A key is required only if it appears in every object.
- A field that is sometimes `null` is allowed to be `null`.
- An array's items are described from all of its elements.

Exit codes: `0` when the schema is written, `2` when an input file is missing or not valid JSON.

---

## Validate a course against a schema

`validate_json.py` checks a course JSON file against a JSON Schema. It works with
any subject, so one schema and one script can check many courses.

```bash
python validate_json.py javascript_beginner.json course_schema.json
```

Example output when a problem is found:

```
INVALID: javascript_beginner.json does not match course_schema.json.

  1. course.modules[0].lessons[2].title
      4 is not of type 'string'
  2. course.modules[3].lessons[0].quiz[1].correctAnswer
      'Paris' is not of type 'integer'

Total problems: 2
```

| Option | Meaning |
|---|---|
| `--max-errors` | How many problems to print. Default: 50. The total is always shown. |

Exit codes:

| Code | Meaning |
|---|---|
| `0` | The course matches the schema |
| `1` | The course does not match. Problems are listed. |
| `2` | A file is missing or not valid JSON, or the schema itself is invalid |

This tool requires the `jsonschema` package, which is in `requirements.txt`.

---

## Typical workflow

1. Create a schema from a finished course:
   `python generate_schema.py javascript_beginner.json -o course_schema.json`
2. Check a new course against that schema:
   `python validate_json.py new_course.json course_schema.json`
