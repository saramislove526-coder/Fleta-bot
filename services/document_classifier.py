# services/document_classifier.py
"""Service module for Upstage document classification.

Provides a helper function `classify_document` that takes a local image file path,
encodes it to base64, and calls the Upstage document-classification endpoint.
Uses requests (with fallback to openai if installed).
"""

import base64
import json
import logging
import os
from typing import Dict, Any

import requests

log = logging.getLogger(__name__)

UPSTAGE_DOC_CLASSIFY_URL = "https://api.upstage.ai/v1/document-classification/chat/completions"

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
    with open(image_path, "rb") as img_file:
        return base64.b64encode(img_file.read()).decode("utf-8")


def classify_document(image_path: str, api_key: str | None = None) -> Dict[str, Any]:
    """Classify a document image using Upstage's document-classification API.

    Args:
        image_path: Local path to the image file (png/jpg/pdf).
        api_key: Optional Upstage API key (defaults to UPSTAGE_API_KEY env var).

    Returns:
        dict with "category" and optional "confidence".
    """
    token = api_key or os.getenv("UPSTAGE_API_KEY")
    if not token:
        raise ValueError("UPSTAGE_API_KEY is not set.")

    base64_data = _encode_image_to_base64(image_path)
    payload = {
        "model": "document-classify",
        "messages": [
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
        "response_format": {
            "type": "json_schema",
            "json_schema": _DOCUMENT_CLASSIFY_SCHEMA,
        },
    }

    resp = requests.post(
        UPSTAGE_DOC_CLASSIFY_URL,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json=payload,
        timeout=60,
    )

    if not resp.ok:
        raise RuntimeError(f"Upstage 문서 분류 API 오류 ({resp.status_code}): {resp.text[:200]}")

    data = resp.json()
    choice = data["choices"][0]
    category = choice.get("message", {}).get("content") or ""
    category = category.strip().strip('"').strip()

    confidence = None
    tool_calls = choice.get("message", {}).get("tool_calls") or []
    for tc in tool_calls:
        func = tc.get("function", {})
        args = func.get("arguments", {})
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except Exception:
                args = {}
        if isinstance(args, dict):
            doc_type = args.get("document_type", {})
            if isinstance(doc_type, dict) and "confidence_score" in doc_type:
                confidence = doc_type["confidence_score"]

    result = {"category": category}
    if confidence is not None:
        result["confidence"] = confidence
    return result


__all__ = ["classify_document"]
