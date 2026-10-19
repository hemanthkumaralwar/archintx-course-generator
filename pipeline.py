"""
pipeline.py

WHAT: The full workflow for one course:
      1. Check settings, load course_schema.json, build the schema set.
      2. Plan: every module title and its lesson titles (or reuse the saved plan).
      3. Course details: the course-level fields (or reuse the saved output).
      4. For each module: write the overview, then write each lesson in order,
         saving after every piece and printing each lesson under its module.
      5. Final check: validate the finished file against course_schema.json.

WHY:  Each piece is saved as soon as it is valid. If the run stops, only the
      piece in progress is lost, and rerunning continues from the next lesson.
"""

from copy import deepcopy

from config import (
    API_KEY,
    ARRAY_PATH,
    LESSON_ARRAY_PATH,
    LESSON_ITEM_COUNTS,
    SCHEMA_FILE,
    validate_config,
)
from checkpoint import load_plan, save_plan
from exceptions import CheckpointError, ConfigurationError, DataPathError
from gemini_service import create_client
from json_utils import get_value, load_json, replace_array, save_json
from module_writer import write_lesson, write_overview
from planner import generate_course_details, generate_plan
from schema_utils import build_schema_set
from validation import ensure_valid


def ensure_output_dirs(request):
    """
    WHAT: Create the course's output and error folders.

    RAISES:
        ConfigurationError: if a folder cannot be created.
    """
    try:
        request.output_dir.mkdir(parents=True, exist_ok=True)
        request.error_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ConfigurationError(
            f"Could not create output folders under '{request.output_dir}': {exc}"
        ) from exc


def load_or_create_plan(request, client):
    """
    WHAT: Return the planned modules, from the saved plan if it exists,
          otherwise by generating and saving a new plan.

    RETURNS:
        A list of {"title", "lessons"} dicts.
    """
    if request.plan_file.exists():
        modules = load_plan(request.plan_file, request)
        print(f"Reusing the saved plan from {request.plan_file}.")
        return modules

    modules = generate_plan(client, request)
    save_plan(request.plan_file, request, modules)
    return modules


def load_or_create_output(request, schemas, client):
    """
    WHAT: Return the course object, from the saved output if it exists,
          otherwise by generating the course details and saving them.

    RETURNS:
        A dict holding the course, with its module list possibly partly filled.
    """
    if request.output_file.exists():
        output = load_json(request.output_file)

        if not isinstance(output, dict):
            raise CheckpointError(
                f"The output file {request.output_file} must contain a JSON object."
            )

        print(f"Reusing the saved output from {request.output_file}.")
        return output

    details = generate_course_details(client, request, schemas)

    # IDs are set by code so they follow the same pattern every time.
    # courseId is placed where the schema defines it (for example inside "course").
    course_values = {
        "courseId": request.course_id,
        "courseTitle": request.title,
        "level": request.level_display,
        "totalDuration": request.total_duration_text,
    }

    for name, value in course_values.items():
        path = (schemas.course_field_paths or {}).get(name)

        if path:
            parts = path.split(".")
            parent = get_value(details, ".".join(parts[:-1])) if len(parts) > 1 else details
            parent[parts[-1]] = value

    save_json(request.output_file, details)
    return details


def course_details_from(output, array_path):
    """
    WHAT: Return a copy of the course object with its module list emptied.

    WHY:  Prompts need the course details as context, but not the modules
          already written. Sending them would waste tokens.
    """
    details = deepcopy(output)
    replace_array(details, array_path, [])
    return details


def write_course(request, schemas, client, plan_modules, output):
    """
    WHAT: Write every missing module overview and lesson, in order.

    HOW:  For each module, the overview is written if it is missing. Then
          each lesson is written if it is missing. Each piece is saved
          immediately. Lesson names are printed under the module name.

    WHY:  Working in this order means a run can stop at any point and resume
          from the exact lesson that was not finished.

    RAISES:
        DataPathError:   if the module list or a module's lessons are malformed.
        CheckpointError: if the saved output has more modules than the plan.
    """
    modules = get_value(output, schemas.array_path)

    if not isinstance(modules, list):
        raise DataPathError(f"'{schemas.array_path}' in the output must be an array.")

    total_modules = len(plan_modules)

    if len(modules) > total_modules:
        raise CheckpointError(
            f"The output has {len(modules)} modules but the plan has {total_modules}. "
            f"Delete '{request.output_dir}' to start over."
        )

    details = course_details_from(output, schemas.array_path)

    for m_index, plan_module in enumerate(plan_modules):
        print(f"\nModule {m_index + 1}/{total_modules}: {plan_module['title']}")

        if m_index >= len(modules):
            overview = write_overview(client, request, m_index, plan_modules, details, schemas)
            overview["moduleId"] = f"{request.course_id}-mod-{m_index + 1}"
            overview[schemas.lesson_path] = []   # Lessons are added one at a time below.
            modules.append(overview)
            save_json(request.output_file, output)

        module = modules[m_index]
        lessons = module.get(schemas.lesson_path)

        if not isinstance(lessons, list):
            raise DataPathError(
                f"Module {m_index + 1} in the output has no '{schemas.lesson_path}' list."
            )

        for l_index, lesson_title in enumerate(plan_module["lessons"]):
            label = f"  Lesson {m_index + 1}.{l_index + 1}: {lesson_title}"

            if l_index < len(lessons):
                print(f"{label} (already saved)")
                continue

            lesson = write_lesson(
                client,
                request,
                m_index,
                l_index,
                plan_modules,
                course_overview_for_prompt(module, schemas.lesson_path),
                details,
                schemas,
            )

            lesson["lessonId"] = (
                f"{request.course_id}-mod-{m_index + 1}-lesson-{l_index + 1}"
            )
            lessons.append(lesson)
            save_json(request.output_file, output)
            print(f"{label} (saved)")


def course_overview_for_prompt(module, lesson_path):
    """
    WHAT: Return the module overview without its lesson list.

    WHY:  The lessons are already in the output file. Sending them again in
          every lesson prompt would add a lot of tokens for no benefit.
    """
    overview = deepcopy(module)
    overview[lesson_path] = []
    return overview


def finish(request, schemas, plan_modules):
    """
    WHAT: Read the saved file back and check it fully.

    WHY:  Reading from disk checks exactly what the user receives. Each lesson
          was checked as it was written. This final pass checks the whole course
          against course_schema.json and confirms every module has all its lessons.

    RAISES:
        DataPathError:         if a module has the wrong number of lessons.
        ValidationFailedError: if the course breaks the schema.
    """
    final = load_json(request.output_file)
    modules = get_value(final, schemas.array_path)

    if len(modules) != len(plan_modules):
        raise DataPathError(
            f"The final course has {len(modules)} modules; expected {len(plan_modules)}."
        )

    for number, module in enumerate(modules, start=1):
        lessons = module.get(schemas.lesson_path, [])

        if len(lessons) != request.lessons_per_module:
            raise DataPathError(
                f"Module {number} has {len(lessons)} lessons; "
                f"expected {request.lessons_per_module}."
            )

    ensure_valid(schemas.course_validator, final, "Final course")

    print("\nSUCCESS: All modules and lessons were generated.")
    print("SUCCESS: Final JSON matches course_schema.json.")
    print(f"Output: {request.output_file.resolve()}")


def run_pipeline(request):
    """
    WHAT: Run every step for one course request.

    WHY:  This is the only function main.py calls, so the whole workflow is
          visible in one place.

    RAISES:
        CourseGenerationError subclasses for any expected failure.
    """
    validate_config()
    ensure_output_dirs(request)

    schemas = build_schema_set(
        load_json(SCHEMA_FILE),
        ARRAY_PATH,
        LESSON_ARRAY_PATH,
        LESSON_ITEM_COUNTS,
    )
    print(f"Module array found at: '{schemas.array_path}'")
    print(f"Lesson array found at: '{schemas.lesson_path}' ({request.lessons_per_module} per module)")
    print(f"Modules planned: {request.module_count} for {request.duration_hours:g} hours")

    # An output without its plan cannot be resumed safely.
    if request.output_file.exists() and not request.plan_file.exists():
        raise CheckpointError(
            f"An output file exists without its plan. Delete '{request.output_dir}' "
            "to start over."
        )

    client = create_client(API_KEY)

    plan_modules = load_or_create_plan(request, client)
    output = load_or_create_output(request, schemas, client)

    write_course(request, schemas, client, plan_modules, output)
    finish(request, schemas, plan_modules)
