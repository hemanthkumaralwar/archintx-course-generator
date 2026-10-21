"""
module_writer.py

WHAT: Writes the two kinds of pieces the pipeline saves:
      - write_overview: one module's overview (lesson list empty),
      - write_lesson:   one lesson.
      Each is checked against its own schema and retried with feedback.
      Rejected output is saved to the course's errors folder.

WHY:  Small requests are less likely to be rejected or cut off, and a
      failed lesson can be retried without redoing the rest of the course.
"""

import json
import re

from config import OBJECTIVE_POINTS, SYNTAX_LINES_MAX, SYNTAX_LINES_MIN
from exceptions import ValidationFailedError
from gemini_service import request_json
from json_utils import save_json
from prompts import build_lesson_prompt, build_overview_prompt
from retry import run_with_retries
from validation import ensure_valid


def check_objective(text, points):
    """
    WHAT: Check that a lesson objective has exactly `points` numbered points.

    WHY:  The schema only says "string". Without this check, the objective
          could have 2 or 6 points, and the course would not match the format.

    RETURNS:
        A list of error strings. Empty means the objective is valid.
    """
    if not isinstance(text, str):
        return ["objective must be text"]

    errors = []

    for number in range(1, points + 1):
        if f"({number})" not in text:
            errors.append(f"objective is missing numbered point ({number})")

    if f"({points + 1})" in text:
        errors.append(f"objective has more than {points} numbered points")

    return errors


STEP_LINE_PATTERN = re.compile(r"^\s*//\s*(\d+)\.\s+\S")


def _step_number(line):
    """
    WHAT: Return the step number at the start of a codeline ("// 3. ..." gives 3), or None.
    """
    if not isinstance(line, str):
        return None

    match = STEP_LINE_PATTERN.match(line)
    return int(match.group(1)) if match else None


def check_code_reorder(section):
    """
    WHAT: Check the code reordering exercise: step numbers, shuffle, and correctOrder.

    WHY:  Each line carries its true step number, so correctOrder can be checked
          against those numbers. Lines already in number order are rejected,
          because the exercise would then be trivial.

    RETURNS:
        A list of error strings. Empty means the exercise is valid, or the
        section is missing (the schema reports a missing section).
    """
    if not isinstance(section, dict):
        return []

    lines = section.get("codelines")
    order = section.get("correctOrder")

    if not isinstance(lines, list) or not isinstance(order, list):
        return []

    count = len(lines)
    numbers = [_step_number(line) for line in lines]

    missing = [str(index) for index, number in enumerate(numbers) if number is None]

    if missing:
        return [
            'codereordering.codelines must start with a step number such as "// 1." '
            "(missing on line index " + ", ".join(missing) + ")"
        ]

    if sorted(numbers) != list(range(1, count + 1)):
        return [f"codereordering step numbers must be 1 to {count}, each used once"]

    errors = []

    if numbers == sorted(numbers):
        errors.append("codereordering.codelines are already in step order; shuffle them")

    expected = [str(numbers.index(step)) for step in range(1, count + 1)]

    if order != expected:
        errors.append(
            f"codereordering.correctOrder must be {expected}: the index of each "
            "line, in step-number order"
        )

    if len(set(lines)) != count:
        errors.append("codereordering.codelines contains duplicate lines")

    return errors


# Words that are also ordinary English or common type names. A plain whole-word
# match would reject normal sentences such as "a phone number", so for these
# words only a quoted or backticked name counts as giving the answer away.
AMBIGUOUS_NAMES = {
    # Operators and keywords that are also English words
    "and", "or", "not", "if", "else", "in", "of", "to", "is", "as", "do", "for",
    "while", "let", "return", "new", "this", "await", "async", "class",
    # Common JavaScript types and everyday words
    "number", "string", "boolean", "array", "object", "function", "value",
    "variable", "list", "set", "map", "key", "name", "text", "type", "null",
    "undefined", "true", "false", "symbol", "date", "output", "input",
}


def names_term(text, term):
    """
    WHAT: Check whether a text names a bucket or term, which would give the answer away.

    WHY:  Words such as number, string, AND, OR, or let are also ordinary English
          words and common type names. Scenarios for those buckets often use the
          word naturally (for example, typeof x === 'number'), so the check
          cannot tell a real giveaway from normal wording. Those words are not
          checked. Other names, such as const, are still checked as whole words.

    RETURNS:
        True if the text names the term in a way that gives the answer away.
    """
    if term.lower() in AMBIGUOUS_NAMES:
        return False

    return re.search(rf"\b{re.escape(term)}\b", text, re.IGNORECASE) is not None


def check_drag_drop(section):
    """
    WHAT: Check the drag-and-drop exercise for rules the schema cannot enforce.

    WHY:  The schema checks the shape only. It cannot check that every item
          belongs to a listed bucket, that at least two buckets are used, that
          item ids are unique, or that a scenario does not give away its bucket
          by naming it.

    RETURNS:
        A list of error strings. Empty means the exercise is valid, or the
        section is missing (the schema reports a missing section).
    """
    if not isinstance(section, dict):
        return []

    items = section.get("items")
    buckets = section.get("correctpairs")

    if not isinstance(items, list) or not isinstance(buckets, list):
        return []

    if not all(isinstance(bucket, str) and bucket.strip() for bucket in buckets):
        return ["dragandropp.correctpairs must be a list of bucket names"]

    errors = []
    distinct = set(buckets)

    if len(distinct) != len(buckets):
        errors.append("dragandropp.correctpairs repeats a bucket name")

    if len(distinct) < 2:
        errors.append("dragandropp.correctpairs must name at least 2 buckets")

    used = set()
    ids = []

    for number, item in enumerate(items):
        if not isinstance(item, dict):
            errors.append(f"dragandropp.items[{number}] is not an object")
            continue

        ids.append(str(item.get("id")))
        category = item.get("correctCategory")
        content = item.get("content")

        if category not in distinct:
            errors.append(
                f"dragandropp.items[{number}] correctCategory '{category}' "
                "is not one of the buckets in correctpairs"
            )
        else:
            used.add(category)

        if isinstance(content, str):
            for bucket in distinct:
                if names_term(content, bucket):
                    errors.append(
                        f"dragandropp.items[{number}] content names its bucket '{bucket}'"
                    )

    if items and len(used) < 2:
        errors.append("dragandropp items must use at least 2 different buckets")

    if len(set(ids)) != len(ids):
        errors.append("dragandropp item ids must be unique")

    return errors


def repair_code_reorder(section):
    """
    WHAT: Rebuild correctOrder from the step numbers, and shuffle the lines if
          they are already in step order.

    WHY:  The step numbers are the truth. The model's correctOrder is often
          wrong or out of date, so it is recalculated here instead of retried.
          Only the order and the index list change, never the sentences.

    NOTE: Changes the section in place. Does nothing if the step numbers are
          missing or not a clean 1 to N sequence, so the checks can report it.
    """
    if not isinstance(section, dict):
        return

    lines = section.get("codelines")

    if not isinstance(lines, list) or not lines:
        return

    count = len(lines)
    numbers = [_step_number(line) for line in lines]

    if any(number is None for number in numbers):
        return

    if sorted(numbers) != list(range(1, count + 1)):
        return

    if numbers == sorted(numbers):
        # Reversing a sorted list leaves it unsorted (for more than one line).
        lines = list(reversed(lines))
        numbers = list(reversed(numbers))
        section["codelines"] = lines

    section["correctOrder"] = [str(numbers.index(step)) for step in range(1, count + 1)]


def repair_hook_image(image):
    """
    WHAT: Add the ```mermaid fence to a hookline diagram that is missing it.

    WHY:  When the diagram text itself is valid, a missing fence is a formatting
          slip. Adding it keeps the content and avoids a retry.

    NOTE: Only changes the html field when its diagram text starts with a
          flowchart header. Anything else is left for the checks to report.
    """
    if not isinstance(image, dict):
        return

    html = image.get("html")

    if not isinstance(html, str):
        return

    stripped = html.strip()

    if stripped.startswith("```mermaid") and stripped.endswith("```"):
        return

    body = stripped.strip("`").strip()

    if body.lower().startswith("mermaid"):
        body = body[len("mermaid"):].strip()

    body_lines = [line for line in body.splitlines() if line.strip()]

    if body_lines and MERMAID_HEADER.match(body_lines[0]):
        image["html"] = "```mermaid\n" + body + "\n```"


def repair_lesson(data):
    """
    WHAT: Run every mechanical repair on a generated lesson before it is checked.

    WHY:  Keeps repairs in one place. Repairs only fix formatting and ordering,
          never the teaching content.
    """
    repair_code_reorder(data.get("codereordering"))
    repair_hook_image(data.get("hooklineimage"))


def check_card_matching(section):
    """
    WHAT: Check the card matching exercise for rules the schema cannot enforce.

    WHY:  The schema checks sizes and field names. It cannot check that each
          match links two real cards, that every card is used exactly once,
          that each term is short, or that a description does not name its
          own term (which would give the answer away).

    RETURNS:
        A list of error strings. Empty means the exercise is valid, or the
        section is missing (the schema reports a missing section).
    """
    if not isinstance(section, dict):
        return []

    cards = section.get("cards")
    matches = section.get("matches")

    if not isinstance(cards, list) or not isinstance(matches, list):
        return []

    errors = []
    contents = {}

    for number, card in enumerate(cards):
        if not isinstance(card, dict):
            errors.append(f"cardmatching.cards[{number}] is not an object")
            continue

        card_id = str(card.get("id"))

        if card_id in contents:
            errors.append(f"cardmatching card id '{card_id}' is used more than once")

        contents[card_id] = card.get("content")

    used = []
    terms = []

    for number, match in enumerate(matches):
        if not isinstance(match, dict):
            errors.append(f"cardmatching.matches[{number}] is not an object")
            continue

        term_id = str(match.get("card1Id"))
        description_id = str(match.get("card2Id"))

        if term_id == description_id:
            errors.append(f"cardmatching.matches[{number}] pairs a card with itself")

        for card_id in (term_id, description_id):
            if card_id not in contents:
                errors.append(
                    f"cardmatching.matches[{number}] refers to unknown card id '{card_id}'"
                )

        used.extend([term_id, description_id])

        term = contents.get(term_id)
        description = contents.get(description_id)

        if not isinstance(term, str) or not isinstance(description, str):
            continue

        if len(term.split()) > 4:
            errors.append(
                f"cardmatching.matches[{number}] term '{term}' has more than 4 words"
            )

        if term.strip().lower() == description.strip().lower():
            errors.append(f"cardmatching.matches[{number}] has identical cards")

        if names_term(description, term):
            errors.append(
                f"cardmatching.matches[{number}] description names its own term '{term}'"
            )

        terms.append(term.strip().lower())

    if len(used) != len(set(used)):
        errors.append("cardmatching: a card appears in more than one match")

    missing = sorted(set(contents) - set(used))

    if missing:
        errors.append(
            "cardmatching: these card ids are not in any match: " + ", ".join(missing)
        )

    if len(terms) != len(set(terms)):
        errors.append("cardmatching: two pairs use the same term")

    return errors


MERMAID_HEADER = re.compile(r"^\s*flowchart\s+(TD|TB|LR|BT|RL)\s*$", re.IGNORECASE)


def parse_mermaid(lines):
    """
    WHAT: Read the nodes and arrows of a Mermaid flowchart.

    WHY:  Shared by the lesson flowchart and the hookline diagram, so both are
          read in exactly the same way.

    HOW:  Quoted label text is removed first, so words inside labels (such as
          "var (carefully)") are not mistaken for nodes. The first line is the
          header and is skipped.

    RETURNS:
        (defined, edges): defined maps node id to "decision" or "step";
        edges is a list of (source, label, target) tuples.
    """
    defined = {}
    edges = []

    for line in lines[1:]:
        without_quotes = re.sub(r'"[^"]*"', '""', line)

        for node_id, bracket in re.findall(r"(\w+)\s*(\[|\{|\()", without_quotes):
            defined.setdefault(node_id, "decision" if bracket == "{" else "step")

        stripped = re.sub(r"\[.*?\]|\{.*?\}|\(.*?\)", "", without_quotes)

        # Form 1: A -- yes --> B   (or A --> B when there is no label)
        for source, label, target in re.findall(
            r"(\w+)\s*(?:--\s*((?:(?!-->).)+?)\s*)?-->\s*(\w+)", stripped
        ):
            edges.append((source, (label or "").strip().lower() or None, target))

        # Form 2: A -->|yes| B   (Mermaid's pipe-label form)
        for source, label, target in re.findall(
            r"(\w+)\s*-->\|\s*([^|]+?)\s*\|\s*(\w+)", stripped
        ):
            edges.append((source, label.strip().lower() or None, target))

    return defined, edges


def check_mermaid_structure(lines, label):
    """
    WHAT: Check the structure shared by every Mermaid diagram in the course.

    RULES:
        - The first line is a flowchart header (TD, LR, BT, or RL).
        - Every node used in an arrow is defined with its label.
        - Exactly one root: a node that no arrow points to.
        - No node is disconnected from the rest of the chart.
        Other nodes may have any number of arrows, in any direction.

    RETURNS:
        A list of error strings. Empty means the diagram is valid.
    """
    errors = []

    if not MERMAID_HEADER.match(lines[0]):
        errors.append(f"{label} must start with 'flowchart TD' (or LR, BT, RL)")

    defined, edges = parse_mermaid(lines)

    if not defined:
        errors.append(f"{label} defines no nodes")
        return errors

    for source, _, target in edges:
        for node_id in (source, target):
            if node_id not in defined:
                errors.append(f"{label} uses node '{node_id}' but never defines it")

    incoming = {node_id: 0 for node_id in defined}
    outgoing = {node_id: 0 for node_id in defined}

    for source, _, target in edges:
        if source in outgoing:
            outgoing[source] += 1
        if target in incoming:
            incoming[target] += 1

    roots = [node_id for node_id in defined if incoming[node_id] == 0]

    if len(roots) != 1:
        errors.append(
            f"{label} must have exactly one root (a node nothing points to); "
            f"found {len(roots)}"
        )

    disconnected = [
        node_id for node_id in defined
        if incoming[node_id] == 0 and outgoing[node_id] == 0
    ]

    if disconnected and len(defined) > 1:
        errors.append(f"{label} has disconnected nodes: " + ", ".join(disconnected))

    return errors


def check_flowchart(section):
    """
    WHAT: Check the lesson flowchart's Mermaid code.

    WHY:  The schema only sees a string. The check confirms the chart has
          exactly one root and no disconnected nodes.

    RETURNS:
        A list of error strings. Empty means valid, or the section is missing
        (the schema reports a missing section).
    """
    if not isinstance(section, dict):
        return []

    errors = []

    if section.get("type") != "mermaid":
        errors.append('flowchart.type must be "mermaid"')

    code = section.get("code")

    if not isinstance(code, str) or not code.strip():
        errors.append("flowchart.code is empty")
        return errors

    lines = [line for line in code.splitlines() if line.strip()]
    errors.extend(check_mermaid_structure(lines, "flowchart"))
    return errors


def check_hook_image(image):
    """
    WHAT: Check the hookline diagram's fields and its Mermaid block.

    WHY:  The schema only sees strings. Without this check, the diagram could be
          plain text, missing its fence, or have a prompt that would be sent to
          an image generator by mistake.

    RETURNS:
        A list of error strings. Empty means valid, or the object is missing
        (the schema reports a missing object).
    """
    if not isinstance(image, dict):
        return []

    errors = []

    if image.get("status") != "included":
        errors.append('hooklineimage.status must be "included"')

    if image.get("style") != "diagram":
        errors.append('hooklineimage.style must be "diagram"')

    if image.get("prompt") != "":
        errors.append('hooklineimage.prompt must be an empty string for a diagram')

    if not isinstance(image.get("alt"), str) or not image["alt"].strip():
        errors.append("hooklineimage.alt must describe the diagram")

    html = image.get("html")

    if not isinstance(html, str) or not html.strip().startswith("```mermaid") or not html.strip().endswith("```"):
        errors.append("hooklineimage.html must be a Mermaid block that starts with ```mermaid and ends with ```")
        return errors

    inner_lines = [
        line for line in html.strip()[len("```mermaid"):-3].splitlines() if line.strip()
    ]

    if not inner_lines:
        errors.append("hooklineimage.html has an empty diagram")
        return errors

    errors.extend(check_mermaid_structure(inner_lines, "hooklineimage diagram"))
    return errors


def check_syntax_and_parts(lesson):
    """
    WHAT: Check the syntax block and the numbered parts of a lesson.

    WHY:  The schema cannot check line counts, that step labels run in order,
          or that part names are unique.

    RETURNS:
        A list of error strings. Empty means valid.
    """
    errors = []

    syntax = lesson.get("syntax")

    if isinstance(syntax, dict):
        highlight = syntax.get("highlight")
        code = highlight.get("code") if isinstance(highlight, dict) else None

        if not isinstance(code, str) or not code.strip():
            errors.append("syntax.highlight.code is empty")
        else:
            code_lines = [line for line in code.splitlines() if line.strip()]

            if not SYNTAX_LINES_MIN <= len(code_lines) <= SYNTAX_LINES_MAX:
                errors.append(
                    f"syntax.highlight.code must have {SYNTAX_LINES_MIN} to "
                    f"{SYNTAX_LINES_MAX} lines (got {len(code_lines)})"
                )

    parts = lesson.get("parts")

    if isinstance(parts, list):
        names = []

        for number, part in enumerate(parts, start=1):
            if not isinstance(part, dict):
                errors.append(f"parts[{number - 1}] is not an object")
                continue

            if part.get("label") != f"Step {number}":
                errors.append(f"parts[{number - 1}] label must be 'Step {number}'")

            name = part.get("name")

            if not isinstance(name, str) or not name.strip():
                errors.append(f"parts[{number - 1}] has no name")
            else:
                names.append(name.strip().lower())

        if len(set(names)) != len(names):
            errors.append("parts names must be unique")

    return errors


def check_hookline_images(lesson):
    """
    WHAT: Check the image of every "hooklines" item with the same diagram rules
          as the hookline image.

    RETURNS:
        A list of error strings, each naming the hooklines item it belongs to.
    """
    errors = []
    hooklines = lesson.get("hooklines")

    if not isinstance(hooklines, list):
        return errors

    for number, item in enumerate(hooklines):
        if not isinstance(item, dict):
            continue

        for problem in check_hook_image(item.get("image")):
            errors.append(f"hooklines[{number}] {problem}")

    return errors


def check_quiz_answers(lesson):
    """
    WHAT: Check that every quiz answer is a valid option index, as text.

    WHY:  The answer must point to an option. Answer text or a number outside the
          options list would make the quiz wrong. This can check the range, not
          whether the chosen option is the correct one.
    """
    errors = []
    quiz = lesson.get("quiz")

    if not isinstance(quiz, list):
        return errors

    for number, question in enumerate(quiz, start=1):
        if not isinstance(question, dict):
            continue

        options = question.get("options")
        answer = question.get("correctAnswer")

        if not isinstance(options, list) or len(options) < 2:
            errors.append(f"quiz {number} needs at least 2 options")
            continue

        if not (isinstance(answer, str) and answer.isdigit()):
            errors.append(f"quiz {number} correctAnswer must be an index as text, such as \"0\"")
        elif int(answer) >= len(options):
            errors.append(
                f"quiz {number} correctAnswer \"{answer}\" is outside its {len(options)} options"
            )

    return errors


def check_example_titles(lesson):
    """
    WHAT: Check that examples are titled "Example 1: ..." through "Example N: ...", in order.
    """
    errors = []
    examples = lesson.get("example")

    if not isinstance(examples, list):
        return errors

    for number, example in enumerate(examples, start=1):
        title = example.get("title") if isinstance(example, dict) else None

        if not isinstance(title, str) or not title.startswith(f"Example {number}:"):
            errors.append(f"example {number} title must start with 'Example {number}:'")

    return errors


def check_lesson_title(lesson):
    """
    WHAT: Check that the lesson title has no "Lesson N:" style prefix.
    """
    title = lesson.get("title")

    if isinstance(title, str) and re.match(r"^\s*(Lesson\b|\d+[.:)])", title):
        return [f"lesson title '{title}' must not start with 'Lesson' or a number"]

    return []


def check_key_takeaways(lesson):
    """
    WHAT: Check that takeaway 5 is a Common Mistake and takeaway 6 is a Pro Tip.

    WHY:  The learner should see a warning and a practical habit at the end of
          every lesson. The count of 6 is enforced by the schema validator.

    RETURNS:
        A list of error strings. Empty means the takeaways are in the right form.
    """
    takeaways = lesson.get("keyTakeaways")

    if not isinstance(takeaways, list):
        return []

    required = {
        5: ("Common Mistake:", "⚠️ Common Mistake:"),
        6: ("Pro Tip:", "💡 Pro Tip:"),
    }

    errors = []

    for position, (label, full_prefix) in required.items():
        if len(takeaways) < position:
            continue

        text = takeaways[position - 1]
        # Ignore a leading emoji or symbol, so "⚠️" and "⚠" both match.
        stripped = re.sub(r"^[^A-Za-z]+", "", text) if isinstance(text, str) else ""

        if not stripped.startswith(label):
            errors.append(f"keyTakeaways item {position} must start with '{full_prefix}'")

    return errors


def _save_rejected(path, index_label, attempt_number, errors, generated, error_dir):
    """
    WHAT: Save a rejected response so you can see what the model produced.

    WHY:  File names include the attempt number, so earlier attempts are not
          overwritten.
    """
    save_json(
        error_dir / f"{path}_attempt_{attempt_number}.json",
        {
            "item": index_label,
            "attempt": attempt_number,
            "errors": errors,
            "generated": generated,
        },
    )


# How many times one failing section is sent back to Gemini for a fix.
SECTION_REPAIR_ROUNDS = 2

# Maps the start of a structure error to the lesson field it belongs to.
ERROR_SECTIONS = [
    (r"^syntax", "syntax"),
    (r"^parts", "parts"),
    (r"^hooklineimage", "hooklineimage"),
    (r"^hooklines\[", "hooklines"),
    (r"^objective", "objective"),
    (r"^codereordering", "codereordering"),
    (r"^dragandropp", "dragandropp"),
    (r"^cardmatching", "cardmatching"),
    (r"^flowchart", "flowchart"),
    (r"^quiz", "quiz"),
    (r"^example", "example"),
    (r"^keyTakeaways", "keyTakeaways"),
    (r"^lesson title", "title"),
]


def section_for_error(error):
    """
    WHAT: Return the lesson field that an error message is about, or None.

    WHY:  If every error points to the same field, only that field needs fixing.
    """
    for pattern, key in ERROR_SECTIONS:
        if re.match(pattern, error):
            return key

    return None


def lesson_structure_errors(data):
    """
    WHAT: Run the mechanical repairs, then every structure check, on one lesson.

    RETURNS:
        A list of error strings. Empty means the lesson passes.
    """
    repair_lesson(data)

    errors = check_objective(data.get("objective"), OBJECTIVE_POINTS)
    errors += check_code_reorder(data.get("codereordering"))
    errors += check_drag_drop(data.get("dragandropp"))
    errors += check_card_matching(data.get("cardmatching"))
    errors += check_flowchart(data.get("flowchart"))
    errors += check_hook_image(data.get("hooklineimage"))
    errors += check_syntax_and_parts(data)
    errors += check_hookline_images(data)
    errors += check_quiz_answers(data)
    errors += check_example_titles(data)
    errors += check_lesson_title(data)
    errors += check_key_takeaways(data)
    return errors


def repair_section(client, request, lesson, key, errors, schemas):
    """
    WHAT: Ask Gemini to fix only one field of a lesson, given the errors for it.

    WHY:  Regenerating a whole lesson repeats the same mistake. A smaller request
          with the current field and its exact problems is much more likely to
          produce a fix. The rest of the lesson is left as it is.

    RETURNS:
        The fixed field value, or None if the schema has no such field.
    """
    section_schema = schemas.lesson_request.get("properties", {}).get(key)

    if section_schema is None:
        return None

    current = json.dumps(lesson.get(key), ensure_ascii=False, indent=2)
    problems = "\n".join(f"- {error}" for error in errors)

    prompt = f"""
Fix only the "{key}" field of one lesson in the course "{request.title}".

Current "{key}" value:
{current}

Problems to fix:
{problems}

Rules:
- Change only what is needed to fix these problems. Keep the meaning and the teaching content.
- Keep every limit named in the problems, such as a maximum number of lines.
- Keep the same JSON shape as the current value.
- Return only the JSON for "{key}", with no Markdown fences or extra text.
"""

    return request_json(client, section_schema, prompt, f"repairing the {key} field")


def write_overview(client, request, index, plan_modules, details, schemas):
    """
    WHAT: Generate and validate the overview of module index (zero-based).

    RETURNS:
        A module dict with an empty lesson list.

    RAISES:
        GenerationError: if no valid overview is produced after retries.
    """
    label = f"Module {index + 1} overview"

    def attempt(previous_errors, attempt_number):
        data = request_json(
            client,
            schemas.overview_request,
            build_overview_prompt(request, index, plan_modules, details, previous_errors),
            f"writing the overview for module {index + 1}",
        )

        if not isinstance(data, dict):
            raise ValidationFailedError(
                f"{label} must be a JSON object.",
                errors=[f"{label}: top-level value is not an object"],
            )

        try:
            ensure_valid(schemas.overview_validator, data, label)
        except ValidationFailedError as exc:
            _save_rejected(
                f"module_{index + 1}_overview",
                index + 1,
                attempt_number,
                exc.errors,
                data,
                request.error_dir,
            )
            raise

        return data

    return run_with_retries(label, attempt)


def write_lesson(client, request, module_index, lesson_index, plan_modules, module_overview, details, schemas):
    """
    WHAT: Generate and validate one lesson, identified by module and lesson position.

    PARAMETERS:
        module_index:    zero-based module position.
        lesson_index:    zero-based lesson position inside the module.
        plan_modules:    the full plan, used for context.
        module_overview: the already-written overview of this module.
        details:         the course-level fields.

    RETURNS:
        A lesson dict that passes the exact-count lesson validator.

    RAISES:
        GenerationError: if no valid lesson is produced after retries.
    """
    label = f"Module {module_index + 1}, lesson {lesson_index + 1}"

    def attempt(previous_errors, attempt_number):
        data = request_json(
            client,
            schemas.lesson_request,
            build_lesson_prompt(
                request,
                module_index,
                lesson_index,
                plan_modules,
                module_overview,
                details,
                previous_errors,
            ),
            f"writing {label.lower()}",
        )

        if not isinstance(data, dict):
            raise ValidationFailedError(
                f"{label} must be a JSON object.",
                errors=[f"{label}: top-level value is not an object"],
            )

        structure_errors = lesson_structure_errors(data)

        # If the errors all belong to one field, ask Gemini to fix only that field.
        for _ in range(SECTION_REPAIR_ROUNDS):
            if not structure_errors:
                break

            keys = {section_for_error(error) for error in structure_errors}

            if len(keys) != 1 or None in keys:
                break

            key = keys.pop()
            fixed = repair_section(client, request, data, key, structure_errors, schemas)

            if fixed is None:
                break

            data[key] = fixed
            structure_errors = lesson_structure_errors(data)

        if structure_errors:
            _save_rejected(
                f"module_{module_index + 1}_lesson_{lesson_index + 1}",
                f"{module_index + 1}.{lesson_index + 1}",
                attempt_number,
                structure_errors,
                data,
                request.error_dir,
            )
            shown = structure_errors[:8]
            raise ValidationFailedError(
                f"{label} has invalid lesson structure:\n  " + "\n  ".join(shown),
                errors=structure_errors,
            )

        try:
            ensure_valid(schemas.lesson_validator, data, label)
        except ValidationFailedError as exc:
            _save_rejected(
                f"module_{module_index + 1}_lesson_{lesson_index + 1}",
                f"{module_index + 1}.{lesson_index + 1}",
                attempt_number,
                exc.errors,
                data,
                request.error_dir,
            )
            raise

        return data

    return run_with_retries(label, attempt)
