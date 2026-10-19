"""
planner.py

WHAT: The two planning steps that run before any module is written:
      1. generate_plan:           every module title and its lesson titles.
      2. generate_course_details: the course-level fields with an empty module list.

WHY:  Planning first gives every later step the same map of the course.
      Lesson titles are fixed here, so each lesson can be written separately
      and in order, and resumed without changing the outline.
"""

from exceptions import ValidationFailedError
from gemini_service import request_json
from json_utils import replace_array
from prompts import build_details_prompt, build_plan_prompt, plan_schema
from retry import run_with_retries
from validation import ensure_valid


def validate_plan(data, request):
    """
    WHAT: Check the plan's module and lesson counts and return cleaned titles.

    WHY:  The schema does not fix the counts (it would be too complex for
          Gemini), so they are checked here. Duplicate lesson titles inside a
          module are also rejected, because they would produce repeated lessons.

    RETURNS:
        A list of {"title": str, "lessons": [str, ...]} dicts.

    RAISES:
        ValidationFailedError: if the shape, counts, or titles are wrong.
    """
    if not isinstance(data, dict) or not isinstance(data.get("modules"), list):
        raise ValidationFailedError(
            "The plan must be an object with a 'modules' list.",
            errors=['top-level value must be {"modules": [...]}'],
        )

    modules = data["modules"]
    errors = []

    if len(modules) != request.module_count:
        errors.append(f"expected {request.module_count} modules, got {len(modules)}")

    for m_number, module in enumerate(modules, start=1):
        if not isinstance(module, dict):
            errors.append(f"module {m_number} is not an object")
            continue

        title = module.get("title")
        lessons = module.get("lessons")

        if not isinstance(title, str) or not title.strip():
            errors.append(f"module {m_number} has no title")

        if not isinstance(lessons, list) or len(lessons) != request.lessons_per_module:
            count = len(lessons) if isinstance(lessons, list) else "no list"
            errors.append(
                f"module {m_number} must have exactly {request.lessons_per_module} "
                f"lesson titles (got {count})"
            )
            continue

        cleaned = []
        for l_number, lesson in enumerate(lessons, start=1):
            if not isinstance(lesson, str) or not lesson.strip():
                errors.append(f"module {m_number} lesson {l_number} is empty")
            else:
                cleaned.append(lesson.strip())

        if len(set(cleaned)) != len(cleaned):
            errors.append(f"module {m_number} has duplicate lesson titles")

    if errors:
        raise ValidationFailedError(
            "The course plan is invalid:\n  " + "\n  ".join(errors),
            errors=errors,
        )

    return [
        {
            "title": module["title"].strip(),
            "lessons": [lesson.strip() for lesson in module["lessons"]],
        }
        for module in modules
    ]


def generate_plan(client, request):
    """
    WHAT: Ask Gemini for every module and lesson title, and return them once valid.

    RETURNS:
        A list of module dicts, each with a title and its lesson titles.

    RAISES:
        GenerationError: if no valid plan is produced after retries.
    """
    def attempt(previous_errors, attempt_number):
        data = request_json(
            client,
            plan_schema(),
            build_plan_prompt(request, previous_errors),
            "planning the course",
        )
        return validate_plan(data, request)

    return run_with_retries("Course plan", attempt)


def generate_course_details(client, request, schemas):
    """
    WHAT: Ask Gemini for the course-level fields. The module list is kept empty.

    RETURNS:
        A dict that matches the course schema, with its module list set to [].

    RAISES:
        GenerationError: if no valid course details are produced after retries.
    """
    def attempt(previous_errors, attempt_number):
        data = request_json(
            client,
            schemas.details_request,
            build_details_prompt(request, previous_errors),
            "creating course details",
        )

        if not isinstance(data, dict):
            raise ValidationFailedError(
                "Course details must be a JSON object.",
                errors=["top-level value is not an object"],
            )

        ensure_valid(schemas.details_validator, data, "Course details")
        return data

    details = run_with_retries("Course details", attempt)

    # The module list must be empty at this stage, whatever the model returned.
    replace_array(details, schemas.array_path, [])
    return details
