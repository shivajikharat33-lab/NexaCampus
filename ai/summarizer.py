"""
AI Complaint Summarizer.
Uses Gemini API if GEMINI_API_KEY is set in .env, otherwise uses a simple fallback.
Get a free Gemini key at: https://aistudio.google.com
"""

import requests
from config import GEMINI_API_KEY
from logger import logger


def summarize_complaint(description: str, category: str, location: str) -> str:
    """
    Returns a 1-2 sentence plain-English summary.
    Tries Gemini first, falls back to basic summary if API key not set or call fails.
    """
    if GEMINI_API_KEY:
        return _gemini_summary(description, category, location)
    return _basic_summary(description, category, location)


def _gemini_summary(description: str, category: str, location: str) -> str:
    try:
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"
        )
        prompt = (
            f"Summarize this campus complaint in 1-2 clear sentences for an admin dashboard. "
            f"Be factual and concise. Do not add recommendations.\n\n"
            f"Category: {category}\n"
            f"Location: {location}\n"
            f"Description: {description}"
        )
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"maxOutputTokens": 100, "temperature": 0.3}
        }
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
        data = response.json()
        return data["candidates"][0]["content"]["parts"][0]["text"].strip()
    except Exception as e:
        logger.warning(f"Gemini summary failed: {e} — using fallback")
        return _basic_summary(description, category, location)


def _basic_summary(description: str, category: str, location: str) -> str:
    """Simple fallback — no API needed."""
    desc = description.strip()
    if len(desc) > 120:
        desc = desc[:120].rsplit(" ", 1)[0] + "..."
    return f"A {category.lower()} issue reported at {location}: {desc}"