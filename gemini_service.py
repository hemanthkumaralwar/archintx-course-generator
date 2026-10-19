"""
gemini_service.py

WHAT: The only module that talks to the Gemini SDK. It creates the client
      and sends one schema-constrained request that returns parsed JSON.

WHY:  If the SDK or model changes, only this file changes. Other modules
      receive plain Python data and never see SDK objects.
"""

import json

from google import genai
from google.genai import types

from config import MODEL, TEMPERATURE
from exceptions import ConfigurationError, GenerationError


def create_client(api_key):
    """
    WHAT: Create an authenticated Gemini client.

    RAISES:
        ConfigurationError: if the API key is empty.
        GenerationError:    if the SDK refuses to create the client.
    """
    if not api_key:
        raise ConfigurationError("Cannot create a Gemini client without an API key.")

    try:
        return genai.Client(api_key=api_key)
    except Exception as exc:
        raise GenerationError(f"Could not create Gemini client: {exc}") from exc


def request_json(client, schema, prompt, label):
    """
    WHAT: Send a prompt with a response schema and return the parsed JSON.

    WHY:  response_json_schema makes Gemini follow the schema directly. The
          response is still parsed and checked here, because the network or
          the model can return unusable text.

    PARAMETERS:
        client: the Gemini client.
        schema: the JSON Schema the response must follow.
        prompt: the instruction text.
        label:  a short description of the step, used in error messages.

    RETURNS:
        The parsed JSON (a dict, list, or other value).

    RAISES:
        GenerationError: if the API call fails, the response is empty, or
                         the text is not valid JSON.
    """
    try:
        response = client.models.generate_content(
            model=MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_json_schema=schema,
                temperature=TEMPERATURE,
            ),
        )
    except Exception as exc:
        # The SDK can raise many exception types. Wrapping them gives the
        # retry logic one type to handle.
        raise GenerationError(f"Gemini API call failed while {label}: {exc}") from exc

    text = getattr(response, "text", None)

    if not text:
        raise GenerationError(f"Gemini returned an empty response while {label}.")

    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise GenerationError(
            f"Gemini returned text that is not valid JSON while {label}: {exc.msg}"
        ) from exc
