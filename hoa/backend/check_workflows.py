"""Script to inspect workflow structure in the database."""
from app.core.database import SessionLocal
from sqlalchemy import text

with SessionLocal() as db:
    result = db.execute(text("""
    SELECT w.title as wf_title, s.title as step_title, s.body as step_body, f.title as field_name
    FROM nodes w
    JOIN edges ews ON ews.from_id = w.id AND ews.type = 'has_step'
    JOIN nodes s ON s.id = ews.to_id AND s.type = 'step'
    LEFT JOIN edges esf ON esf.from_id = s.id AND esf.type = 'requires'
    LEFT JOIN nodes f ON f.id = esf.to_id AND f.type = 'field'
    WHERE w.type = 'workflow' AND w.title ILIKE '%MRI%'
    ORDER BY s.title LIMIT 30
    """)).fetchall()
    print("=== MRI Workflow ===")
    for r in result:
        print(f"  Step: {r.step_title} | Field: {r.field_name}")
    
    # All workflows
    print("\n=== All Workflows ===")
    wfs = db.execute(text("SELECT id, title FROM nodes WHERE type='workflow'")).fetchall()
    for w in wfs:
        print(f"  {w.title} ({w.id})")
        steps = db.execute(text("""
        SELECT s.title, f.title as field
        FROM edges ews
        JOIN nodes s ON s.id = ews.to_id AND s.type = 'step'
        LEFT JOIN edges esf ON esf.from_id = s.id AND esf.type = 'requires'
        LEFT JOIN nodes f ON f.id = esf.to_id AND f.type = 'field'
        WHERE ews.from_id = :wid AND ews.type = 'has_step'
        ORDER BY s.title
        """), {"wid": w.id}).fetchall()
        for s in steps:
            print(f"    - Step: {s.title} | field: {s.field}")

    # Check routing rules
    print("\n=== Routing Rules ===")
    rules = db.execute(text("SELECT intent, team, urgency FROM routing_rules LIMIT 20")).fetchall()
    for r in rules:
        print(f"  intent={r.intent} -> team={r.team} urgency={r.urgency}")
    
    # policy thresholds
    print("\n=== Policy Thresholds ===")
    thresholds = db.execute(text("SELECT key, value FROM policy_thresholds")).fetchall()
    for t in thresholds:
        print(f"  {t.key} = {t.value}")
