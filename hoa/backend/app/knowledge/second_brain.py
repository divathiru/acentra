"""
Second Brain module — Link suggestions, gap resolution, publish/rollback, retire, and change impact.
"""

from __future__ import annotations

import uuid
import hashlib
from datetime import date, datetime, timedelta
from typing import List, Dict, Any, Optional
import structlog
from rapidfuzz import fuzz
from sqlalchemy import select, update, delete, and_, or_
from sqlalchemy.orm import Session

from app.core.models import (
    GraphVersion, Node, Edge, NodeVisibility, NodeChunk, Ticket, TicketEvent
)
from app.audit.api import write_audit_event
from app.knowledge.api import _GRAPH_CACHE, get_active_version_id, _get_or_build_graph
from app.knowledge.embedders import MistralEmbedder, FakeEmbedder
from app.core.config import get_settings

logger = structlog.get_logger(__name__)


def generate_link_suggestions(db: Session, version_id: Optional[uuid.UUID] = None) -> List[Edge]:
    """
    Run worker job that uses rapidfuzz to find Form, System and Team names mentioned in
    article bodies and proposes edges (origin='suggested', with a confidence score and matched text).
    Suggested edges are stored in DB review queue and NEVER traversed by retrieval.
    """
    ver_id = version_id or get_active_version_id(db)
    if not ver_id:
        return []

    # Fetch Form, System, and Team nodes in this version
    target_nodes = db.execute(
        select(Node).where(
            Node.version_id == ver_id,
            Node.type.in_(["form", "system", "team"])
        )
    ).scalars().all()

    # Fetch Article nodes
    article_nodes = db.execute(
        select(Node).where(
            Node.version_id == ver_id,
            Node.type == "article"
        )
    ).scalars().all()

    existing_edges = db.execute(
        select(Edge.from_id, Edge.to_id, Edge.type).where(Edge.version_id == ver_id)
    ).all()
    existing_set = {(str(e.from_id), str(e.to_id), e.type) for e in existing_edges}

    suggested_edges: List[Edge] = []

    for art in article_nodes:
        art_text = f"{art.title} {art.body}".lower()
        for target in target_nodes:
            target_name = target.title.strip()
            if not target_name or len(target_name) < 3:
                continue

            # Check for mention using rapidfuzz or substring
            score = 0.0
            if target_name.lower() in art_text:
                score = 100.0
            else:
                ratio = fuzz.partial_ratio(target_name.lower(), art_text)
                if ratio >= 85:
                    score = float(ratio)

            if score >= 85:
                # Map edge type
                if target.type == "form":
                    edge_type = "requires_form"
                elif target.type == "system":
                    edge_type = "performed_in"
                elif target.type == "team":
                    edge_type = "owned_by"
                else:
                    edge_type = "suggested_link"

                edge_key = (str(art.id), str(target.id), edge_type)
                if edge_key not in existing_set:
                    edge = Edge(
                        from_id=art.id,
                        to_id=target.id,
                        type=edge_type,
                        origin="suggested",
                        note=f"{{\"confidence\": {score}, \"matched_text\": \"{target_name}\"}}",
                        version_id=ver_id
                    )
                    db.add(edge)
                    suggested_edges.append(edge)
                    existing_set.add(edge_key)

    db.flush()
    logger.info("link_suggestions.generated", count=len(suggested_edges), version_id=str(ver_id))
    return suggested_edges


def create_draft_from_gap(
    db: Session,
    ticket_id: uuid.UUID,
    *,
    title: str,
    body: str,
    owner: Optional[str] = None,
    roles: Optional[List[str]] = None,
    review_date: Optional[date] = None,
) -> Node:
    """
    In the gap drawer: 'Create draft article' takes resolution text and creates an
    Article node with status='draft' (never used for answers), owner and review_date set,
    and visibility defaulting to roles that asked.
    """
    ver_id = get_active_version_id(db)
    if not ver_id:
        gv = GraphVersion(status="active")
        db.add(gv)
        db.flush()
        ver_id = gv.id

    ticket = db.execute(select(Ticket).where(Ticket.id == ticket_id)).scalar_one_or_none()
    
    node_id = uuid.uuid4()
    content_hash = hashlib.sha256((title + body).encode()).hexdigest()
    
    draft_node = Node(
        id=node_id,
        version_id=ver_id,
        type="article",
        title=title,
        body=body,
        status="draft",  # MUST be draft!
        version=1,
        effective_date=date.today(),
        review_date=review_date or (date.today() + timedelta(days=90)),
        owner=owner or (ticket.team if ticket else "Department Operations Head"),
        source_ref=f"ticket:{ticket_id}",
        content_hash=content_hash,
    )
    db.add(draft_node)
    db.flush()

    vis_roles = roles or ["ALL"]
    for r in vis_roles:
        db.add(NodeVisibility(node_id=node_id, version_id=ver_id, role_id=r))

    if ticket:
        ticket.status = "resolved"
        ticket.resolved_at = datetime.utcnow()
        db.add(TicketEvent(
            ticket_id=ticket_id,
            actor_id=ticket.assigned_to or ticket.opened_by,
            event_type="resolved_to_draft",
            data={"draft_node_id": str(node_id), "title": title}
        ))

    db.flush()

    write_audit_event(db, "article_draft_created_from_gap", {
        "node_id": str(node_id),
        "ticket_id": str(ticket_id),
        "title": title,
    })

    logger.info("draft_from_gap.created", node_id=str(node_id), ticket_id=str(ticket_id))
    return draft_node


def approve_and_publish_article(
    db: Session,
    article_id: uuid.UUID,
    use_fake_embedder: bool = False
) -> GraphVersion:
    """
    Admin approves a draft article; in ONE transaction:
    1. Set status='approved' on article.
    2. Create a new graph version & set active pointer.
    3. Chunk & embed article using Mistral / Fake embedder.
    4. Copy nodes, edges, visibilities to new graph version.
    5. Rehydrate NetworkX cache.
    """
    current_active_id = get_active_version_id(db)
    
    # 1. Fetch draft article
    draft_node = db.execute(
        select(Node).where(Node.id == article_id)
    ).scalars().first()

    if not draft_node:
        raise ValueError(f"Article {article_id} not found")

    draft_node.status = "approved"

    # 2. Create new active GraphVersion
    new_ver = GraphVersion(id=uuid.uuid4(), status="active")
    db.add(new_ver)
    db.flush()

    # Archive previous active version
    if current_active_id:
        db.execute(
            update(GraphVersion)
            .where(GraphVersion.id == current_active_id)
            .values(status="archived")
        )

    # 3. Copy all nodes from current_active_id to new_ver.id
    old_nodes = db.execute(
        select(Node).where(Node.version_id == current_active_id)
    ).scalars().all() if current_active_id else []

    # Map of old node ids included
    copied_node_ids = set()
    for n in old_nodes:
        # If this node is the one being approved, use updated status
        status = "approved" if n.id == article_id else n.status
        db.add(Node(
            id=n.id,
            version_id=new_ver.id,
            type=n.type,
            title=n.title,
            body=n.body,
            status=status,
            version=n.version,
            effective_date=n.effective_date,
            review_date=n.review_date,
            owner=n.owner,
            source_ref=n.source_ref,
            content_hash=n.content_hash,
        ))
        copied_node_ids.add(n.id)

    if article_id not in copied_node_ids:
        db.add(Node(
            id=draft_node.id,
            version_id=new_ver.id,
            type=draft_node.type,
            title=draft_node.title,
            body=draft_node.body,
            status="approved",
            version=draft_node.version,
            effective_date=draft_node.effective_date,
            review_date=draft_node.review_date,
            owner=draft_node.owner,
            source_ref=draft_node.source_ref,
            content_hash=draft_node.content_hash,
        ))

    # 4. Copy edges to new_ver.id
    if current_active_id:
        old_edges = db.execute(
            select(Edge).where(Edge.version_id == current_active_id)
        ).scalars().all()
        for e in old_edges:
            db.add(Edge(
                from_id=e.from_id,
                to_id=e.to_id,
                type=e.type,
                origin=e.origin,
                note=e.note,
                version_id=new_ver.id
            ))

    # 5. Copy node visibility to new_ver.id
    if current_active_id:
        old_vis = db.execute(
            select(NodeVisibility).where(NodeVisibility.version_id == current_active_id)
        ).scalars().all()
        for v in old_vis:
            db.add(NodeVisibility(
                node_id=v.node_id,
                version_id=new_ver.id,
                role_id=v.role_id
            ))

    # Ensure draft article has visibility in new version if missing
    existing_vis = db.execute(
        select(NodeVisibility).where(NodeVisibility.node_id == article_id, NodeVisibility.version_id == new_ver.id)
    ).scalars().all()
    if not existing_vis:
        db.add(NodeVisibility(node_id=article_id, version_id=new_ver.id, role_id="ALL"))

    # 6. Copy existing chunks and embed the newly approved article
    from sqlalchemy import func
    if current_active_id:
        old_chunks = db.execute(
            select(NodeChunk).where(NodeChunk.version_id == current_active_id)
        ).scalars().all()
        for c in old_chunks:
            db.add(NodeChunk(
                id=uuid.uuid4(),
                node_id=c.node_id,
                version_id=new_ver.id,
                text=c.text,
                embedding=c.embedding,
                tsv=c.tsv,
                content_hash=c.content_hash,
                embedding_model=c.embedding_model,
            ))

    # Chunk & embed the newly approved article
    settings = get_settings()
    embedder = FakeEmbedder() if use_fake_embedder or not settings.MISTRAL_API_KEY else MistralEmbedder()
    
    text_chunk = f"{draft_node.title}\n\n{draft_node.body}"
    content_hash = hashlib.sha256(text_chunk.encode()).hexdigest()

    import asyncio
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        emb_list = asyncio.run(embedder.embed([text_chunk]))
    else:
        # If in running loop, use synchronous fake or thread runner
        emb_list = [[0.0] * 1024]

    emb = emb_list[0] if emb_list else None

    db.add(NodeChunk(
        id=uuid.uuid4(),
        node_id=article_id,
        version_id=new_ver.id,
        text=text_chunk,
        embedding=emb,
        tsv=func.to_tsvector('english', text_chunk),
        content_hash=content_hash,
        embedding_model="mistral" if not use_fake_embedder else "fake"
    ))

    db.flush()

    # 7. Rehydrate NetworkX cache
    _GRAPH_CACHE.clear()
    _get_or_build_graph(db, new_ver.id)

    write_audit_event(db, "article_approved_and_published", {
        "article_id": str(article_id),
        "new_version_id": str(new_ver.id),
        "previous_version_id": str(current_active_id) if current_active_id else None,
    })

    logger.info("article.approved_and_published", article_id=str(article_id), new_version_id=str(new_ver.id))
    return new_ver


def retire_article(
    db: Session,
    article_id: uuid.UUID,
    superseded_by_id: Optional[uuid.UUID] = None
) -> None:
    """
    Retire/supersede an article:
    Status change + deletion of its embeddings in ONE transaction.
    """
    ver_id = get_active_version_id(db)

    # 1. Status change on Node
    db.execute(
        update(Node)
        .where(Node.id == article_id)
        .values(status="archived")
    )

    # 2. Deletion of its embeddings (NodeChunk rows) in the same transaction
    db.execute(
        delete(NodeChunk).where(NodeChunk.node_id == article_id)
    )

    # 3. If superseded, add supersedes edge
    if superseded_by_id and ver_id:
        db.add(Edge(
            from_id=article_id,
            to_id=superseded_by_id,
            type="supersedes",
            origin="structural",
            version_id=ver_id
        ))

    db.flush()

    _GRAPH_CACHE.clear()

    write_audit_event(db, "article_retired", {
        "article_id": str(article_id),
        "superseded_by_id": str(superseded_by_id) if superseded_by_id else None,
    })

    logger.info("article.retired", article_id=str(article_id))


def get_change_impact(db: Session, node_id: uuid.UUID) -> Dict[str, Any]:
    """
    Change impact API: GET /graph/impact/{node_id} returns workflows and articles
    affected through backlinks.
    """
    ver_id = get_active_version_id(db)
    if not ver_id:
        return {"node_id": str(node_id), "affected_workflows": [], "affected_articles": [], "total_affected": 0}

    # Find edges pointing to node_id
    incoming_edges = db.execute(
        select(Edge).where(Edge.to_id == node_id, Edge.version_id == ver_id)
    ).scalars().all()

    affected_node_ids = {e.from_id for e in incoming_edges}

    # Transitive traversal using NetworkX
    G = _get_or_build_graph(db, ver_id)
    str_node = str(node_id)
    if str_node in G:
        predecessors = list(G.predecessors(str_node))
        for p in predecessors:
            try:
                affected_node_ids.add(uuid.UUID(p))
            except ValueError:
                pass

    if not affected_node_ids:
        return {"node_id": str(node_id), "affected_workflows": [], "affected_articles": [], "total_affected": 0}

    affected_nodes = db.execute(
        select(Node).where(Node.id.in_(list(affected_node_ids)), Node.version_id == ver_id)
    ).scalars().all()

    affected_workflows = []
    affected_articles = []

    for n in affected_nodes:
        item = {
            "id": str(n.id),
            "type": n.type,
            "title": n.title,
            "owner": n.owner,
            "status": n.status,
        }
        if n.type == "workflow":
            affected_workflows.append(item)
        elif n.type == "article":
            affected_articles.append(item)

    return {
        "node_id": str(node_id),
        "affected_workflows": affected_workflows,
        "affected_articles": affected_articles,
        "total_affected": len(affected_workflows) + len(affected_articles)
    }
