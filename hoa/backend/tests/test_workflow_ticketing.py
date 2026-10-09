"""
Unit tests for Task 7: Workflows, Ticketing, and Routing.
"""

import os
import pytest
from app.core.database import SessionLocal
from app.workflow.session_store import SessionStore
from app.workflow.fsm import load_workflow, WorkflowDef, FieldSpec
from app.workflow.scenarios.mri_preauth import handle_mri_preauth, WorkflowAction
from app.workflow.scenarios.discharge_billing import handle_discharge_billing
from app.workflow.scenarios.specimen_rejection import handle_specimen_rejection
from app.ticketing.api import (
    create_ticket,
    claim_ticket,
    resolve_ticket,
    reassign_ticket,
    list_tickets,
)
from app.core.models import User, Ticket
from app.core.security import hash_password


def _get_or_create_test_user(db, email: str, app_role: str = "agent") -> User:
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


def test_session_store_encryption():
    """Test Fernet encryption of sensitive vault fields."""
    os.environ["VAULT_KEY"] = "gAAAAABl-testingkey1234567890123456789012="
    with SessionLocal() as db:
        agent = _get_or_create_test_user(db, "agent_test_wf@demo.com", "agent")
        store = SessionStore(db)
        
        user_id = str(agent.id)
        encounter_id = "enc_100"
        dept = "radiology"
        
        session, _ = store.get_or_create(user_id, "wf_mri", encounter_id, dept)
        slots = {"insurer": "Aetna", "mrn": "MRN-998877", "ssn": "000-11-2222"}
        store.set_slots(session, slots)
        
        loaded_slots = store.get_slots(session)
        assert loaded_slots["insurer"] == "Aetna"
        assert "mrn" not in loaded_slots
        assert "ssn" not in loaded_slots
        
        vault_keys = store.get_vault_keys(session)
        assert "mrn" in vault_keys
        assert "ssn" in vault_keys
        
        decrypted_vault = store._decrypt_vault(session.vault_json_encrypted)
        assert decrypted_vault["mrn"] == "MRN-998877"
        assert decrypted_vault["ssn"] == "000-11-2222"
        
        # Clean up session
        store.purge(session)




def test_mri_preauth_scenario_missing_fields():
    """Test MRI pre-auth scenario asking for missing fields."""
    action = handle_mri_preauth({}, vault_keys=set(), governing_article_id="ART-007")
    assert action.state == "COLLECT"
    assert "insurer" in action.prompt_fields


def test_mri_preauth_scenario_rejected():
    """Test MRI pre-auth scenario routing on rejected status."""
    slots = {
        "insurer": "Aetna",
        "procedure_code": "70551",
        "scheduled_date": "2026-10-15",
        "authorization_status": "rejected",
    }
    vault_keys = {"patient_mrn"}
    
    action = handle_mri_preauth(slots, vault_keys=vault_keys, governing_article_id="ART-007")
    assert action.state == "ROUTE"
    assert action.route_team == "Insurance/TPA"



def test_discharge_billing_high_amount():
    """Test discharge billing clearance routing when total charges exceeds threshold."""
    slots = {
        "discharge_date": "2026-10-10",
        "total_charges": 6000.00,
        "insurance_coverage_amount": 4000.00,
        "patient_balance": 2000.00,
    }
    thresholds = {"billing_supervisor_threshold": 5000.00}
    
    action = handle_discharge_billing(slots, vault_keys=set(), thresholds=thresholds, governing_article_id="ART-012")
    assert action.state == "ROUTE"
    assert action.route_team == "Billing Supervisor"



def test_ticketing_idempotency_and_sod():
    """Test ticket creation idempotency window and separation of duties on claim/resolve."""
    with SessionLocal() as db:
        agent = _get_or_create_test_user(db, "agent1_wf@demo.com", "agent")
        admin = _get_or_create_test_user(db, "admin1_wf@demo.com", "admin")

        user_id = str(agent.id)
        other_user_id = str(admin.id)
        encounter_id = "enc_test_idem_123"


        # 1. Ticket creation
        ticket1 = create_ticket(
            db=db,
            opened_by=user_id,
            encounter_id=encounter_id,
            dept_role="Billing",
            team="Billing Operations",
            reason="insufficient_evidence",
            assistant_text="Test assistant text",
            summary="Test ticket summary",
        )
        db.commit()
        assert ticket1.id is not None
        
        # 2. Idempotent creation within window returns existing ticket
        ticket2 = create_ticket(
            db=db,
            opened_by=user_id,
            encounter_id=encounter_id,
            dept_role="Billing",
            team="Billing Operations",
            reason="insufficient_evidence",
            assistant_text="Test assistant text duplicate",
            summary="Test ticket summary duplicate",
        )
        assert ticket2.id == ticket1.id

        # 3. Separation of duties: creator cannot claim their own ticket
        with pytest.raises(PermissionError):
            claim_ticket(db, str(ticket1.id), actor_id=user_id)

        # Other agent claims ticket
        claimed = claim_ticket(db, str(ticket1.id), actor_id=other_user_id)
        assert str(claimed.assigned_to) == other_user_id
        assert claimed.status == "in_progress"

        # Creator cannot resolve ticket either
        with pytest.raises(PermissionError):
            resolve_ticket(db, str(ticket1.id), actor_id=user_id, resolution_note="Self resolve attempt")

        # Other agent resolves ticket
        resolved = resolve_ticket(db, str(ticket1.id), actor_id=other_user_id, resolution_note="Resolved issue successfully.")
        assert resolved.status == "resolved"


def test_routing_engine():
    """Test deterministic routing rule engine."""
    from app.ticketing.routing import RoutingEngine
    with SessionLocal() as db:
        engine = RoutingEngine(db)
        
        # Test always-routed check
        assert engine.should_always_route("account_specific", "check my account")
        
        # Test team resolution
        res = engine.resolve_team("authorization_rejected")
        assert res["team"] == "Insurance/TPA"
        
        # Test fallback
        fallback = engine.resolve_team("unknown_random_category")
        assert fallback["team"] == "Department Operations Head"


