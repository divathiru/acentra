"""
Unit and integration tests for Task 8: Audit log verification, Analytics, System Settings, Feedback, and Knowledge Admin.
"""

import pytest
from app.core.database import SessionLocal
from app.audit.api import write_audit_event, verify_chain
from app.analytics.api import get_analytics_summary
from app.core.system_settings import get_all_settings, get_setting, set_setting
from app.feedback.api import record_feedback
from app.knowledge.admin import list_articles, create_article, publish_new_graph_version
from app.core.models import AuditLog, Interaction, User, Node
from app.core.security import hash_password
from sqlalchemy import text

def _get_or_create_test_user(db, email: str, app_role: str = "admin") -> User:
    u = db.query(User).filter(User.email == email).first()
    if not u:
        u = User(
            email=email,
            name=email.split("@")[0],
            password_hash=hash_password("Demo@1234"),
            app_role=app_role,
        )
        db.add(u)
        db.commit()
        db.refresh(u)
    return u


def test_audit_hmac_verification_and_tamper_detection():
    """Test HMAC chain creation, valid verification, and tamper detection."""
    with SessionLocal() as db:
        # Clear audit log to avoid dirty state from previous failed test runs
        db.execute(text("DELETE FROM audit_log"))
        db.commit()

        # Write 3 audit events
        e1 = write_audit_event(db, "test_event_1", {"data": "test1"})
        e2 = write_audit_event(db, "test_event_2", {"data": "test2"})
        e3 = write_audit_event(db, "test_event_3", {"data": "test3"})
        db.commit()

        # 1. Verify valid chain
        ok, violations = verify_chain(db)
        assert ok is True, f"Chain is broken: {violations}"
        assert len(violations) == 0

        # 2. Tamper with payload of e2
        t_entry = db.query(AuditLog).filter(AuditLog.id == e2.id).first()
        orig_payload = dict(t_entry.payload)
        t_entry.payload = {"data": "tampered_data"}
        db.commit()

        # 3. Verification should detect tampered link
        ok_tampered, violations_tampered = verify_chain(db)
        assert ok_tampered is False
        assert len(violations_tampered) > 0
        assert violations_tampered[0]["id"] == e2.id

        # Restore original payload so chain is intact for other tests
        t_entry = db.query(AuditLog).filter(AuditLog.id == e2.id).first()
        t_entry.payload = orig_payload
        db.commit()


def test_system_settings():
    """Test getting and updating database-backed system settings."""
    with SessionLocal() as db:
        user = _get_or_create_test_user(db, "admin_settings@demo.com", "admin")
        
        # Read defaults
        settings = get_all_settings(db)
        assert "llm_enabled" in settings
        assert settings["llm_enabled"] in ("true", "false")

        # Update setting
        set_setting(db, "llm_enabled", "false", actor_id=str(user.id))
        db.commit()

        assert get_setting(db, "llm_enabled") == "false"

        # Restore setting
        set_setting(db, "llm_enabled", "true", actor_id=str(user.id))
        db.commit()


def test_analytics_summary():
    """Test computing analytics summary metrics."""
    with SessionLocal() as db:
        user = _get_or_create_test_user(db, "user_analytics@demo.com", "employee")
        
        # Create a test interaction
        interaction = Interaction(
            user_id=user.id,
            dept_role="Billing",
            outcome="ANSWER",
            intent="information_query",
            confidence=0.85,
            band="HIGH",
            latency_ms=120,
            stage_ms_json={"guard": 5, "retrieve": 40, "generate": 75},
            mode="llm",
            is_gap=False,
        )
        db.add(interaction)
        db.commit()

        summary = get_analytics_summary(db)
        assert summary["total_interactions"] >= 1
        assert "ANSWER" in summary["outcome_breakdown"]
        assert "HIGH" in summary["confidence_band_breakdown"]
        assert isinstance(summary["gap_rate"], float)


def test_feedback_recording():
    """Test recording user feedback and linking to interaction."""
    with SessionLocal() as db:
        user = _get_or_create_test_user(db, "user_feedback@demo.com", "employee")
        
        interaction = Interaction(
            user_id=user.id,
            dept_role="Billing",
            outcome="ANSWER",
            intent="information_query",
            confidence=0.90,
            band="HIGH",
            latency_ms=100,
            mode="llm",
        )
        db.add(interaction)
        db.commit()

        fb = record_feedback(
            db,
            user_id=str(user.id),
            rating="positive",
            comment="Great answer!",
            interaction_id=str(interaction.id),
        )
        db.commit()

        assert fb.id is not None
        assert fb.rating == "positive"
        
        # Check interaction feedback column updated
        db.refresh(interaction)
        assert interaction.feedback == "positive"


def test_knowledge_admin():
    """Test creating articles, listing articles, and publishing graph versions."""
    from app.knowledge.api import get_active_version_id, _GRAPH_CACHE
    from app.core.models import GraphVersion
    from sqlalchemy import update

    with SessionLocal() as db:
        orig_active = get_active_version_id(db)

        # Create new article
        node = create_article(
            db,
            title="Test Policy Article",
            body="This is a test policy body.",
            type="policy",
            owner="Compliance",
            roles=["Billing"],
        )
        db.commit()
        assert node.id is not None

        # List articles
        articles = list_articles(db, query="Test Policy Article")
        assert len(articles) >= 1
        assert articles[0]["title"] == "Test Policy Article"

        # Publish new graph version
        new_ver = publish_new_graph_version(db, note="Test publish")
        db.commit()
        assert new_ver.id is not None
        assert new_ver.status == "active"

        # Restore original graph version status so subsequent test suites retain active graph nodes
        if orig_active:
            db.execute(update(GraphVersion).where(GraphVersion.id == new_ver.id).values(status="archived"))
            db.execute(update(GraphVersion).where(GraphVersion.id == orig_active).values(status="active"))
            db.commit()
            _GRAPH_CACHE.clear()
