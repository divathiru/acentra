import uuid
import random
from datetime import datetime, timedelta
import asyncio
from sqlalchemy.orm import Session
from app.core.database import SessionLocal
from app.core.models import Interaction, Ticket, User

def generate_demo_data(session: Session):
    print("Generating demo data...")
    # Fetch random user
    user = session.query(User).first()
    user_id = user.id if user else None

    outcomes = ["ANSWER", "GUIDE", "ROUTE", "REFUSE"]
    intents = ["schedule_mri", "billing_inquiry", "password_reset", "clinical_guidance"]
    workflows = ["mri_auth", "billing_dispute"]
    bands = ["HIGH", "MEDIUM", "LOW"]
    modes = ["llm", "template"]
    teams = ["Scheduling", "Billing", "IT Support"]
    dept_roles = ["Nurse", "Billing", "Doctor"]

    now = datetime.utcnow()
    
    # Generate 150 interactions over the past 21 days
    for _ in range(150):
        days_ago = random.randint(0, 21)
        ts = now - timedelta(days=days_ago, hours=random.randint(0, 23), minutes=random.randint(0, 59))
        
        outcome = random.choices(outcomes, weights=[0.5, 0.2, 0.2, 0.1])[0]
        intent = random.choice(intents)
        workflow = random.choice(workflows) if outcome == "GUIDE" else None
        band = random.choice(bands)
        mode = random.choices(modes, weights=[0.8, 0.2])[0]
        dept_role = random.choice(dept_roles)
        
        latency_ms = random.randint(500, 3000) if mode == "llm" else random.randint(50, 200)
        
        interaction = Interaction(
            id=uuid.uuid4(),
            ts=ts,
            user_id=user_id,
            dept_role=dept_role,
            outcome=outcome,
            intent=intent,
            workflow_id=workflow,
            confidence=random.uniform(0.5, 0.99),
            band=band,
            latency_ms=latency_ms,
            mode=mode,
            is_gap=random.random() < 0.1,
            citation_ok=random.random() < 0.9,
            feedback=random.choices(["positive", "negative", None], weights=[0.6, 0.1, 0.3])[0]
        )
        session.add(interaction)
        
        if outcome == "ROUTE" or interaction.is_gap:
            ticket = Ticket(
                id=uuid.uuid4(),
                team=random.choice(teams),
                urgency=random.choices(["high", "normal", "low"], weights=[0.2, 0.6, 0.2])[0],
                reason="Auto-generated demo ticket",
                is_gap=interaction.is_gap,
                status=random.choices(["open", "in_progress", "resolved", "closed"], weights=[0.4, 0.2, 0.3, 0.1])[0],
                opened_by=user_id,
                created_at=ts
            )
            session.add(ticket)
            
    session.commit()
    print("Demo data generated successfully.")

if __name__ == "__main__":
    with SessionLocal() as session:
        generate_demo_data(session)
