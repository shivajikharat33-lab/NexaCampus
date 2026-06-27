"""
Unit Tests for Smart College Civic Detector
Run with: python -m pytest test_main.py -v
"""
import pytest
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi.testclient import TestClient

# ── AI Unit Tests (no server needed) ─────────────────────────────
def test_predict_priority_emergency():
    from ai.predictor import predict_priority
    assert predict_priority("fire in the building") == "Emergency"

def test_predict_priority_high():
    from ai.predictor import predict_priority
    assert predict_priority("broken chair in classroom") == "High"

def test_predict_priority_low():
    from ai.predictor import predict_priority
    assert predict_priority("minor suggestion for improvement") == "Low"

def test_predict_category_it():
    from ai.predictor import predict_category
    assert predict_category("wifi is not working") == "IT"

def test_predict_category_plumbing():
    from ai.predictor import predict_category
    assert predict_category("water leaking from pipe") == "Plumbing"

def test_predict_category_electrical():
    from ai.predictor import predict_category
    assert predict_category("light not working in room") == "Electrical"

def test_predict_category_cleanliness():
    from ai.predictor import predict_category
    assert predict_category("garbage and trash everywhere dirty") == "Cleanliness"

def test_severity_critical():
    from ai.severity import calculate_severity
    result = calculate_severity("Emergency", "Electrical", "fire and explosion danger")
    assert result["score"] > 75
    assert result["label"] == "Critical"

def test_severity_low():
    from ai.severity import calculate_severity
    result = calculate_severity("Low", "General", "minor paint issue")
    assert result["score"] < 50

def test_severity_has_color():
    from ai.severity import calculate_severity
    result = calculate_severity("High", "Security", "theft reported")
    assert "color" in result
    assert "breakdown" in result

def test_auto_router_electrical():
    from ai.auto_router import auto_assign_department
    assert auto_assign_department("Electrical") == "Electrical Department"

def test_auto_router_it():
    from ai.auto_router import auto_assign_department
    assert auto_assign_department("IT") == "IT Department"

def test_auto_router_unknown():
    from ai.auto_router import auto_assign_department
    assert auto_assign_department("Unknown") == "Administration Department"

def test_auto_router_security():
    from ai.auto_router import auto_assign_department
    assert auto_assign_department("Security") == "Security Department"

def test_auto_router_plumbing():
    from ai.auto_router import auto_assign_department
    assert auto_assign_department("Plumbing") == "Plumbing & Sanitation Department"


# ── Config Tests ──────────────────────────────────────────────────
def test_config_loaded():
    from config import SECRET_KEY, ALGORITHM, ALLOWED_PRIORITIES, ALLOWED_STATUSES
    assert SECRET_KEY is not None
    assert ALGORITHM == "HS256"
    assert "Emergency" in ALLOWED_PRIORITIES
    assert "Pending" in ALLOWED_STATUSES

def test_categories_loaded():
    from categories import ALLOWED_CATEGORIES
    assert len(ALLOWED_CATEGORIES) > 50
    assert "Water Leakage" in ALLOWED_CATEGORIES

def test_password_hash():
    from password_utils import hash_password, verify_password
    hashed = hash_password("TestPass@123")
    assert hashed != "TestPass@123"
    assert verify_password("TestPass@123", hashed) == True
    assert verify_password("WrongPass", hashed) == False

def test_auth_token_creation():
    from auth import create_access_token, create_refresh_token
    token = create_access_token({"email": "test@test.com", "role": "student"})
    assert token is not None
    assert len(token) > 10

def test_refresh_token_creation():
    from auth import create_refresh_token
    token = create_refresh_token({"email": "test@test.com", "role": "admin"})
    assert token is not None

def test_reset_token_creation():
    from auth import create_reset_token, decode_reset_token
    token = create_reset_token("test@test.com")
    email = decode_reset_token(token)
    assert email == "test@test.com"

def test_rate_limiter_import():
    from rate_limiter import check_rate_limit
    assert callable(check_rate_limit)

def test_health_score_import():
    from ai.health_score import get_campus_health, calculate_area_health
    assert callable(get_campus_health)
    assert callable(calculate_area_health)

def test_summarizer_fallback():
    from ai.summarizer import summarize_complaint
    result = summarize_complaint("water leaking", "Plumbing", "Library")
    assert isinstance(result, str)
    assert len(result) > 10

def test_similarity_import():
    from ai.similarity import find_similar_complaints
    assert callable(find_similar_complaints)