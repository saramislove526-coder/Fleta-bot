# services/document_classifier.py
"""Service module for Upstage document classification.

Provides a helper function `classify_document` that takes a local image file path,
encodes it to base64, and calls the Upstage document‑classification endpoint
using the same API key used for chat models.
"""

import base64
import json
import os
from typing import Dict, Any

from openai import OpenAI

# Load required environment variables (same as used elsewhere)
UPSTAGE_API_KEY = os.getenv("UPSTAGE_API_KEY")
# The document‑classification endpoint is fixed; no separate model variable needed.
UPSTAGE_DOC_CLASSIFY_URL = "https://api.upstage.ai/v1/document-classification"

if not UPSTAGE_API_KEY:
    raise EnvironmentError("UPSTAGE_API_KEY not set in environment")

# Re‑use the OpenAI client but point to the document‑classification base URL.
client = OpenAI(api_key=UPSTAGE_API_KEY, base_url=UPSTAGE_DOC_CLASSIFY_URL)

# JSON schema used in the original user snippet – kept as a constant.
_DOCUMENT_CLASSIFY_SCHEMA = {
    "name": "document-classify",
    "schema": {
        "type": "string",
        "oneOf": [
            {"const": "invoice", "description": "Commercial invoice with itemized charges and billing information"},
            {"const": "receipt", "description": "Receipt showing purchase transaction details"},
            {"const": "contract", "description": "Legal agreement or contract document"},
            {"const": "cv", "description": "Curriculum vitae or resume"},
            {"const": "others", "description": "Other"},
        ],
    },
}

def _encode_image_to_base64(image_path: str) -> str:
    """Read an image file and return a base64‑encoded string.

    Args:
        image_path: Path to the image file.
    Returns:
        Base64 string without any data‑uri prefix.
    """
    with open(image_path, "rb") as img_file:
        return base64.b64encode(img_file.read()).decode("utf-8")

def classify_document(image_path: str) -> Dict[str, Any]:
    """Classify a document image using Upstage's document‑classification model.

    The function mirrors the example the user posted, returning the parsed JSON
    response from the API.

    Args:
        image_path: Local path to the image (png/jpg/etc.).
    Returns:
        The JSON payload returned by Upstage, e.g. ``{"category": "invoice"}``.
    """
    base64_data = _encode_image_to_base64(image_path)
    response = client.chat.completions.create(
        model="document-classify",
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:application/octet-stream;base64,{base64_data}"},
                    }
                ],
            }
        ],
        response_format={
            "type": "json_schema",
            "json_schema": _DOCUMENT_CLASSIFY_SCHEMA,
        },
    )
    # Upstage returns the category as a plain string in content (e.g. "invoice")
    # and optionally includes confidence_score inside tool_calls.
    try:
        choice = response.choices[0]
        category = choice.message.content or ""
        category = category.strip().strip('"').strip()

        # Try to extract confidence_score from tool_calls if available
        confidence = None
        if choice.message.tool_calls:
            for tc in choice.message.tool_calls:
                if hasattr(tc, "function") and tc.function:
                    args = tc.function.arguments
                    if isinstance(args, dict):
                        doc_type = args.get("document_type", {})
                        if isinstance(doc_type, dict):
                            confidence = doc_type.get("confidence_score")
                    elif isinstance(args, str):
                        try:
                            parsed = json.loads(args)
                            doc_type = parsed.get("document_type", {})
                            if isinstance(doc_type, dict):
                                confidence = doc_type.get("confidence_score")
                        except (json.JSONDecodeError, AttributeError):
                            pass

        result = {"category": category}
        if confidence is not None:
            result["confidence"] = confidence
        return result
    except Exception as e:
        raise RuntimeError(f"Failed to parse Upstage classification response: {e}")

__all__ = ["classify_document"]
