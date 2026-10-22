"""AI response parsing and JSON extraction utilities."""
import json
from typing import Dict, Any


def parse_ai_response(raw_text: str) -> Dict[str, Any]:
    """Extract and parse structured JSON from raw model output.

    Strips markdown code fences (```json ... ``` or ``` ... ```), isolates the outermost
    curly braces, and decodes into a dictionary.

    Args:
        raw_text: The raw textual response returned by the AI provider.

    Returns:
        Parsed dictionary matching the diagnostic schema.

    Raises:
        json.JSONDecodeError: If valid JSON cannot be parsed from the response.
    """
    text = raw_text.strip()
    # Strip markdown fences
    if text.startswith("```"):
        parts = text.split("```")
        text = parts[1] if len(parts) > 1 else text
        if text.startswith("json"):
            text = text[4:]
    text = text.strip()

    # Find JSON boundaries in case of extra leading/trailing conversational text
    start = text.find("{")
    end = text.rfind("}") + 1
    if start != -1 and end > start:
        text = text[start:end]

    return json.loads(text)
