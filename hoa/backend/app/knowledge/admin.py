"""
Admin Knowledge Management module — publish graph versions, edit articles, manage nodes & edges.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional
import structlog
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.models import GraphVersion, Node, NodeVisibility, Edge
from app.audit.api import write_audit_event
from app.knowledge.api import _GRAPH_CACHE, get_active_version_id

logger = structlog.get_logger(__name__)


def list_articles(
    db: Session,
    query: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    """List knowledge articles/nodes."""
    stmt = select(Node)
    if status:
        stmt = stmt.where(Node.status == status)
    if query:
        stmt = stmt.where(Node.title.ilike(f"%{query}%"))
    stmt = stmt.order_by(Node.title).limit(limit)

    nodes = db.execute(stmt).scalars().all()
    result = []
    for n in nodes:
        roles = db.execute(
            select(NodeVisibility.role_id).where(
                NodeVisibility.node_id == n.id,
                NodeVisibility.version_id == n.version_id,
            )
        ).scalars().all()
        result.append({
            "id": str(n.id),
            "version_id": str(n.version_id),
            "type": n.type,
            "title": n.title,
            "body": n.body[:200] + "..." if len(n.body) > 200 else n.body,
            "status": n.status,
            "version": n.version,
            "effective_date": str(n.effective_date) if n.effective_date else None,
            "owner": n.owner,
            "source_ref": n.source_ref,
            "roles": roles,
        })
    return result


def create_article(
    db: Session,
    *,
    title: str,
    body: str,
    type: str = "policy",
    owner: Optional[str] = None,
    roles: Optional[List[str]] = None,
    effective_date: Optional[date] = None,
    source_ref: Optional[str] = None,
) -> Node:
    """Create a new article node in the active graph version."""
    active_ver = get_active_version_id(db)
    if not active_ver:
        # Create a graph version if none exists
        gv = GraphVersion(status="active")
        db.add(gv)
        db.flush()
        active_ver = gv.id

    node_id = uuid.uuid4()
    node = Node(
        id=node_id,
        version_id=active_ver,
        type=type,
        title=title,
        body=body,
        status="approved",
        version=1,
        effective_date=effective_date or date.today(),
        owner=owner or "Department Operations Head",
        source_ref=source_ref or title,
    )
    db.add(node)
    db.flush()

    for r in (roles or ["ALL"]):
        nv = NodeVisibility(node_id=node_id, version_id=active_ver, role_id=r)
        db.add(nv)

    db.flush()

    write_audit_event(db, "article_created", {
        "node_id": str(node_id),
        "title": title,
        "type": type,
        "owner": owner,
    })

    logger.info("article.created", node_id=str(node_id), title=title)
    return node


def publish_new_graph_version(db: Session, note: str = "") -> GraphVersion:
    """
    Publish a new active graph version.
    Archives current active version and sets new one to active.
    Clears NetworkX cache.
    """
    current_active = get_active_version_id(db)
    if current_active:
        db.execute(
            update(GraphVersion)
            .where(GraphVersion.id == current_active)
            .values(status="archived")
        )

    new_ver = GraphVersion(status="active")
    db.add(new_ver)
    db.flush()

    _GRAPH_CACHE.clear()

    write_audit_event(db, "graph_version_published", {
        "new_version_id": str(new_ver.id),
        "previous_version_id": str(current_active) if current_active else None,
        "note": note,
    })

    logger.info("graph_version.published", new_version_id=str(new_ver.id))
    return new_ver


def rollback_graph_version(db: Session, target_version_id: str) -> GraphVersion:
    """Roll back to a specified previous graph version."""
    target_uuid = uuid.UUID(target_version_id)
    target = db.execute(
        select(GraphVersion).where(GraphVersion.id == target_uuid)
    ).scalar_one_or_none()

    if not target:
        raise ValueError(f"Graph version {target_version_id} not found")

    current_active = get_active_version_id(db)
    if current_active:
        db.execute(
            update(GraphVersion)
            .where(GraphVersion.id == current_active)
            .values(status="archived")
        )

    target.status = "active"
    db.flush()

    _GRAPH_CACHE.clear()

    write_audit_event(db, "graph_version_rollback", {
        "target_version_id": str(target_uuid),
        "previous_version_id": str(current_active) if current_active else None,
    })

    logger.info("graph_version.rollback", target_version_id=str(target_uuid))
    return target
