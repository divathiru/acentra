"""Public interface for this module. Other modules import only from here."""

from typing import List, Optional
import uuid
from sqlalchemy import select, and_, exists
from sqlalchemy.orm import Session
from app.core.models import GraphVersion, Node, NodeVisibility, Edge, NodeChunk

def get_active_version_id(session: Session) -> Optional[uuid.UUID]:
    res = session.execute(
        select(GraphVersion.id).where(GraphVersion.status == "active")
    )
    return res.scalar_one_or_none()

def _visibility_clause(roles: List[str], version_id: uuid.UUID):
    allowed_roles = roles + ["ALL"]
    return exists().where(
        and_(
            NodeVisibility.node_id == Node.id,
            NodeVisibility.version_id == version_id,
            NodeVisibility.role_id.in_(allowed_roles)
        )
    )

def get_node(session: Session, node_id: uuid.UUID, roles: List[str]) -> Optional[Node]:
    version_id = get_active_version_id(session)
    if not version_id:
        return None
        
    res = session.execute(
        select(Node).where(
            and_(
                Node.id == node_id,
                Node.version_id == version_id,
                _visibility_clause(roles, version_id)
            )
        )
    )
    return res.scalar_one_or_none()

def get_edges(session: Session, from_id: uuid.UUID, roles: List[str]) -> List[Edge]:
    version_id = get_active_version_id(session)
    if not version_id:
        return []
        
    res = session.execute(
        select(Edge).join(Node, and_(Node.id == Edge.to_id, Node.version_id == version_id)).where(
            and_(
                Edge.from_id == from_id,
                Edge.version_id == version_id,
                _visibility_clause(roles, version_id)
            )
        )
    )
    return list(res.scalars().all())

def semantic_search(session: Session, query_embedding: List[float], roles: List[str], limit: int = 5) -> List[NodeChunk]:
    version_id = get_active_version_id(session)
    if not version_id:
        return []
        
    res = session.execute(
        select(NodeChunk)
        .join(Node, and_(Node.id == NodeChunk.node_id, Node.version_id == version_id))
        .where(
            and_(
                NodeChunk.version_id == version_id,
                _visibility_clause(roles, version_id)
            )
        )
        .order_by(NodeChunk.embedding.cosine_distance(query_embedding))
        .limit(limit)
    )
    return list(res.scalars().all())

def get_workflows(session: Session, roles: List[str]) -> List[Node]:
    version_id = get_active_version_id(session)
    if not version_id:
        return []
        
    res = session.execute(
        select(Node).where(
            and_(
                Node.type == "workflow",
                Node.version_id == version_id,
                _visibility_clause(roles, version_id)
            )
        )
    )
    return list(res.scalars().all())
