from app.core.database import SessionLocal
from app.core.models import Node, NodeVisibility, GraphVersion
from sqlalchemy import select

with SessionLocal() as db:
    active_v = db.execute(select(GraphVersion).where(GraphVersion.status == 'active')).scalar_one_or_none()
    print(f"Active version: {active_v.id if active_v else None}")
    
    vis = db.execute(select(NodeVisibility.node_id, NodeVisibility.role_id, NodeVisibility.version_id)).all()
    for v in vis:
        print(f"Vis: node={v.node_id}, role={v.role_id}, ver={v.version_id}")

    nodes = db.execute(select(Node.id, Node.version_id)).all()
    for n in nodes:
        print(f"Node: id={n.id}, ver={n.version_id}")
