"""
prompts.py

WHAT: Every piece of text sent to Gemini, and the schema for the plan step.

WHY:  Prompts change more often than the logic around them. Keeping them in
      one file makes tuning quick. The quality rules are written once and
      shared by every lesson-level prompt, so the standard stays the same.
"""

import json

from config import (
    LESSON_ITEM_COUNTS,
    LESSON_MINUTES_MAX,
    LESSON_MINUTES_MIN,
    OBJECTIVE_POINTS,
)

# How many earlier errors to send back. Long lists add cost without much gain.
MAX_ERRORS_IN_PROMPT = 15


# What each difficulty level should mean in the writing.
DIFFICULTY_GUIDE = {
    "beginner": (
        "assume no prior experience, define every new term the first time it "
        "appears, and build from familiar everyday comparisons to the real thing"
    ),
    "intermediate": (
        "assume basic familiarity with the subject, focus on practical "
        "techniques, trade-offs, and common mistakes practitioners make"
    ),
    "advanced": (
        "assume strong foundations, focus on depth, edge cases, design "
        "decisions, and failure modes, and skip introductory material"
    ),
}


# Shared quality standard. This is what makes the content read like real
# course material rather than generic filler.
QUALITY_RULES = """
Quality standard (follow strictly):
- Use real, specific tools, libraries, datasets, algorithms, and industries
  relevant to the topic. Never use placeholders such as "Item 1", "Company X",
  "foo", "bar", or "lorem ipsum".
- Scenarios must be concrete. State the data, the goal, and the constraint.
  Example of the level of detail wanted: a grocery chain forecasting weekly
  demand for 300 products from two years of point-of-sale records.
- Quiz questions test application and reasoning in a scenario, not memorized
  definitions. Each wrong option must be a plausible mistake a learner might
  really make. Never use "all of the above" or "none of the above".
- Each quiz explanation says why the correct answer is right and why the most
  tempting wrong answer is wrong.
- Code must be complete, correct, and runnable in the language the topic
  uses, with realistic variable names and short comments. Do not use
  pseudo-code unless the field asks for it.
- The code reordering exercise follows CODE_REORDER_RULES below.
- Card matching and drag-and-drop items must relate to the lesson in a way a
  learner has to think about (for example, a metric matched to the situation
  where it is the right choice). No two items may be trivially identical.
- Mini challenges give a realistic task with concrete input, the expected
  result, and hints that guide without giving the answer.
- Real-world stories describe a plausible situation in a named industry. Do
  not attribute invented figures, quotes, or outcomes to real companies.
- Do not reuse the examples or scenarios from earlier lessons in the module.
- Write full, specific sentences. Avoid filler such as "In this lesson we will
  learn" and generic phrases such as "a powerful tool".
"""


# Image fields are required by the schema but cannot be generated here, so the
# prompt fixes their values.
IMAGE_RULES = """
Image format. Every image in this lesson is a Mermaid diagram: the
"hooklineimage" object, and the "image" object inside each "hooklines" item.
- "status": exactly "included".
- "style": exactly "diagram".
- "html": a Mermaid diagram in a fenced block, with exactly one root node. It starts with a line
  containing ```mermaid, then "flowchart TD", then the nodes and arrows, and
  ends with a line containing ```. Use short, concrete labels related to the
  text it illustrates.
- "prompt": exactly "" (empty).
- "alt": one short sentence describing what the diagram shows.
"""


MODULE_EXPLANATION_RULES = """
Module explanation (the "moduleExplanation" field) format:
- Use ONE topic named after the module title. Its "points" list contains
  full, specific sentences in this order:
  1. A summary of what the module covers, how many lessons it has, and why
     the skills matter for the course.
  2. What the learner will be able to do by the end of the module.
  3. The key terms the module introduces, written out in full. Put code or
     technical names in backticks.
  4. The lesson progression: each lesson title in order, with what it builds
     on. Number the lessons.
  5. The built-in functions, tools, or operators the module uses, and what
     each one is for.
  6. One realistic beginner mistake per lesson and how to avoid it.
  7. The practice built into the lessons (exercises, mini challenges,
     matching, sorting, and debugging tasks).
  8. How the module prepares the learner for the next module.
- Stay on this module's topic. Do not describe other modules in detail.
"""


def objective_rules_text():
    """
    WHAT: Describe the required format of a lesson's objective text.

    WHY:  The objective must hold a fixed number of numbered, measurable skills.
          The same count is checked in module_writer.py.
    """
    numbered = ", ".join(f"({n})" for n in range(1, OBJECTIVE_POINTS + 1))
    return f"""
Objective field format: one string that starts with "By the end of this
lesson, you will be able to:" and then lists exactly {OBJECTIVE_POINTS} numbered
points, written as {numbered}. Each point is one specific, measurable skill
that matches the lesson content.
"""


CODE_REORDER_RULES = """
Code reordering format (the "codereordering" object):
- "title": a short name for the exercise, such as "Reorder: how typeof works".
- "instruction": one sentence that tells the learner what to order, such as
  "Drag the steps into the order the computer follows when this code runs."
- "codelines": exactly the number of lines given in the item counts. Each line
  starts with its true step number as a comment, "// N.", where N is the
  step's position in the real execution order (1 is first). After the number,
  write one sentence that describes the step and quotes the relevant code.
  Example: // 3. The engine reads the value's internal type tag
- Each number from 1 to the number of lines appears exactly once.
- The lines are listed in a SHUFFLED order, not in step order.
- "correctOrder": the index of each codeline, written as text, in step order
  (step 1 first). Indexes start at "0". Example: if the line numbered 1 is at
  index 3, correctOrder begins ["3", ...]. Every index appears exactly once.
"""


DRAG_DROP_RULES = """
Drag-and-drop format (the "dragandropp" object):
- "title": a short name for the exercise, such as "Sort: const vs let".
- "instruction": one sentence that tells the learner what to sort, such as
  "Drag each scenario into the right keyword bucket."
- "items": exactly the number of items given in the item counts. Each item has:
  - "id": text, numbered "1", "2", "3", ... in order.
  - "content": one realistic scenario a learner has to think about. It is a
    situation, not a definition. Do not write the bucket name in it.
  - "correctCategory": the bucket this scenario belongs to, copied exactly
    from "correctpairs".
- "correctpairs": the list of bucket names, 2 to 4 distinct names, written
  exactly as the buckets appear in correctCategory.
- Use at least two buckets, and no single bucket may hold every item.
- Scenarios must be different from one another and must test a real
  distinction, not a memorized fact.
"""


CARD_MATCH_RULES = """
Card matching format (the "cardmatching" object):
- "title": a short name for the exercise, such as "Match the term with its meaning".
- "instruction": one sentence that tells the learner what to match, such as
  "Match each term on the left with its plain-English description on the right."
- "cards": exactly the number of cards given in the item counts. They form
  pairs: each pair is one TERM card and one DESCRIPTION card.
  - Cards are numbered "1", "2", "3", ... in order, and each pair uses two
    consecutive numbers, with the term first (for example "1" and "2").
  - A term card is a short keyword or concept name of 1 to 4 words, taken from
    the lesson.
  - A description card is one plain-English sentence that explains the term. It
    must not contain its own term as a word.
- "matches": exactly the number of pairs given in the item counts. Each match
  gives "card1Id" (the term card) and "card2Id" (its description card). Every
  card appears in exactly one match.
- Terms must be different from one another and cover the lesson's main ideas.
  Do not pair a term with a description that describes a different term.
"""


FLOWCHART_RULES = """
Flowchart format (the "flowchart" object). Follow this structure, using the example as the model:

flowchart TD
    A["Need a variable"] --> B{"Will the value ever change?"}
    B -- no --> C["const"]
    B -- yes --> D{"Is this legacy code?"}
    D -- no --> E["let"]
    D -- yes --> F["var (carefully)"]
    C --> G["Write the declaration"]
    E --> G
    F --> G

- "title": a short name for the decision the flowchart shows, such as "Picking the right keyword".
- "type": exactly "mermaid".
- "code": the Mermaid flowchart, with these rules:
  - The first line is "flowchart TD". Indent every arrow line with four spaces.
  - Define each node with its label the first time it appears: ["..."] for a
    step, and {"..."} for a decision.
  - Exactly one root: one start node that no arrow points to.
  - Every other node can have any number of arrows, in any direction.
  - Use {...} for a decision that asks a question, and [...] for a step.
  - Branch labels are short, written as: B -- yes --> D and B -- no --> C.
    Labels are optional.
- Node labels are short and concrete. Decision questions relate to this lesson's concept.
"""




SYNTAX_PARTS_RULES = """
Syntax and parts formats:
- "syntax": "title" is "Syntax". "highlight.code" is 2 to 6 lines of real code
  that uses this lesson's keyword or pattern. Use \\n between lines.
- "parts": exactly the number of parts given in the item counts. Each part has:
  - "label": "Step 1", "Step 2", and so on, in order.
  - "name": a distinct keyword or concept of 1 to 4 words from this lesson.
  - "description": one or two specific sentences with a concrete example. Start
    with the core ideas of the lesson and move to the rules and pitfalls.
"""


EXTRA_LESSON_RULES = """
Additional lesson rules:
- Example titles are "Example 1: ..." through "Example 5: ...", in order. Start
  with a basic case and progress to a practical one. Each example has "title",
  "code", and "explanation".
- "lessonExplanation" has exactly one topic. Its points are full sentences.
- The lesson "title" is the lesson name only. Do not start it with "Lesson" or a number.
- Quiz "correctAnswer" is the zero-based index of the correct option, written as
  text: "0", "1", "2", or "3". Never write the answer text or a computed value.
"""


KEY_TAKEAWAY_RULES = """
Key takeaways (the "keyTakeaways" list): exactly 6 items, each one complete sentence.
- Items 1 to 4: specific rules, habits, or consequences from this lesson. Name
  keywords and operators exactly as the lesson uses them, in backticks.
- Item 5 must start with "⚠️ Common Mistake:" and describe a mistake learners will make.
- Item 6 must start with "💡 Pro Tip:" and describe a practical habit.
- Do not repeat the lesson objective word for word, and do not repeat one idea
  in two items.
"""


def lesson_item_counts_text():
    """
    WHAT: List the exact item counts that every lesson must follow.

    WHY:  The counts are not in the request schema (see schema_utils), so the
          prompt must state them too.
    """
    return "\n".join(
        f"   - {item_path}: exactly {count}"
        for item_path, count in LESSON_ITEM_COUNTS.items()
    )


def outline_text(plan_modules):
    """
    WHAT: Return the module titles as a numbered list.

    WHY:  Each prompt shows the whole course so the model knows where the
          current module fits.
    """
    return "\n".join(
        f"{number}. {module['title']}"
        for number, module in enumerate(plan_modules, start=1)
    )


def add_error_feedback(prompt, previous_errors):
    """
    WHAT: Append the previous attempt's problems to a prompt, if there are any.

    WHY:  Showing the model its own mistakes is the most direct way to get a
          corrected answer on the next attempt.
    """
    if not previous_errors:
        return prompt

    shown = previous_errors[:MAX_ERRORS_IN_PROMPT]

    return (
        prompt
        + "\nYour previous output failed validation. Fix these problems "
        + "without changing the structure:\n"
        + "\n".join(f"- {error}" for error in shown)
    )


def plan_schema():
    """
    WHAT: Schema for the course plan: module titles, each with its lesson titles.

    WHY:  The plan is short, so one request covers the whole course. Exact
          counts are checked by the planner, not by the schema.
    """
    return {
        "type": "object",
        "properties": {
            "modules": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "lessons": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                    },
                    "required": ["title", "lessons"],
                },
            }
        },
        "required": ["modules"],
    }


def build_plan_prompt(request, previous_errors=None):
    """
    WHAT: Prompt for the complete course plan: module titles and lesson titles.

    WHY:  Planning every lesson title first means each lesson is written with
          knowledge of the full course, so lessons do not overlap and build
          on each other in order.
    """
    prompt = f"""
Plan a course.

Course title: {request.title}
Difficulty level: {request.difficulty}
Total duration: {request.duration_hours:g} hours
Number of modules: {request.module_count}
Lessons per module: {request.lessons_per_module}
Lesson length: {LESSON_MINUTES_MIN}-{LESSON_MINUTES_MAX} minutes

Requirements:
1. Return exactly {request.module_count} modules, in learning order.
2. Each module has exactly {request.lessons_per_module} lessons, in learning order.
3. Module and lesson titles must be specific (for example "Train-Test Splits and
   Data Leakage", not "Data Part 2"). Each lesson builds on the one before it.
4. Match the difficulty: {DIFFICULTY_GUIDE[request.difficulty]}.
5. Return only the JSON object, with no Markdown fences or extra text.
"""
    return add_error_feedback(prompt, previous_errors)


def build_details_prompt(request, previous_errors=None):
    """
    WHAT: Prompt for the course-level fields. The module list stays empty.

    WHY:  The course description and goals are written first so every module
          and lesson keeps the same voice and level.
    """
    prompt = f"""
Create the course-level information for the course "{request.title}".

Difficulty level: {request.difficulty}
Total duration: {request.duration_hours:g} hours
Number of modules: {request.module_count}

Fill in every field defined by the supplied JSON schema for the course itself.
Leave the module list EMPTY. Modules are written in a separate step.

Requirements:
1. Match the difficulty: {DIFFICULTY_GUIDE[request.difficulty]}.
2. Keep the course title exactly as given.
3. Describe real outcomes a learner can achieve, not generic promises.
4. Return only the JSON object, with no Markdown fences or extra text.
"""
    return add_error_feedback(prompt, previous_errors)


def build_overview_prompt(request, index, plan_modules, details, previous_errors=None):
    """
    WHAT: Prompt for one module overview. Its lesson list stays empty.

    WHY:  The overview previews the lessons that follow, so the module reads
          as one coherent unit.
    """
    module = plan_modules[index]
    lesson_list = "\n".join(
        f"{number}. {title}" for number, title in enumerate(module["lessons"], start=1)
    )

    prompt = f"""
Write the OVERVIEW for module {index + 1} of {len(plan_modules)} in the course "{request.title}".

Module title (use exactly this): "{module['title']}"

Lessons that follow in this module. Lead into them, but do not write the lessons:
{lesson_list}

Course outline:
{outline_text(plan_modules)}

Course details already written:
{json.dumps(details, ensure_ascii=False)}

Requirements:
1. Match the difficulty: {DIFFICULTY_GUIDE[request.difficulty]}.
2. Explain what the module covers and why it matters, using specific topics.
3. Leave the lessons list EMPTY.
4. Follow the supplied JSON schema exactly.
{MODULE_EXPLANATION_RULES}
{QUALITY_RULES}
5. Return only the JSON object, with no Markdown fences or extra text.
"""
    return add_error_feedback(prompt, previous_errors)


def build_lesson_prompt(
    request,
    module_index,
    lesson_index,
    plan_modules,
    module_overview,
    details,
    previous_errors=None,
):
    """
    WHAT: Prompt for one lesson, with the course, module, and earlier lessons as context.

    WHY:  Giving the earlier lesson titles stops repetition. Giving the module
          overview and course details keeps the lesson consistent with the rest.
    """
    module = plan_modules[module_index]
    lesson_title = module["lessons"][lesson_index]
    earlier = module["lessons"][:lesson_index]

    earlier_text = "\n".join(f"- {title}" for title in earlier) or "None. This is the first lesson."

    prompt = f"""
Write ONE lesson for the course "{request.title}".

Module {module_index + 1}: "{module['title']}"
Lesson {module_index + 1}.{lesson_index + 1}: "{lesson_title}"
The lesson title must be exactly this.
Target study time: {LESSON_MINUTES_MIN}-{LESSON_MINUTES_MAX} minutes.

Earlier lessons in this module (do not repeat their examples or scenarios):
{earlier_text}

Module overview already written:
{json.dumps(module_overview, ensure_ascii=False)}

Course outline:
{outline_text(plan_modules)}

Course details already written:
{json.dumps(details, ensure_ascii=False)}

Requirements:
1. Match the difficulty: {DIFFICULTY_GUIDE[request.difficulty]}.
2. Cover only this lesson's topic.
3. Use exactly these list sizes:
{lesson_item_counts_text()}
4. Follow the supplied JSON schema exactly.
{IMAGE_RULES}
{SYNTAX_PARTS_RULES}
{objective_rules_text()}
{CODE_REORDER_RULES}
{DRAG_DROP_RULES}
{CARD_MATCH_RULES}
{FLOWCHART_RULES}
{KEY_TAKEAWAY_RULES}
{EXTRA_LESSON_RULES}
{QUALITY_RULES}
5. Return only the JSON object for this ONE lesson, with no Markdown fences or extra text.
"""
    return add_error_feedback(prompt, previous_errors)
