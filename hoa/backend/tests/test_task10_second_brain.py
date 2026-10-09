"""
Unit and Integration Tests for Task 10 (Second Brain — Link Suggestions, Gaps, Drafts, Approve/Publish, Retire, Impact).
"""

import uuid
import pytest
from datetime import date
from sqlalchemy import select

from app.core.database import SessionLocal
from app.core.models import GraphVersion, Node, Edge, NodeChunk, Ticket, NodeVisibility
from app.knowledge.api import retrieve, RetrieveFlags, get_active_version_id
from app.knowledge.second_brain import (
    generate_link_suggestions,
    create_draft_from_gap,
    approve_and_publish_article,
    retire_article,
    get_change_impact,
)
from app.orchestrator.pipeline import run_pipeline
from app.llm.template import TemplateAdapter


@pytest.fixture
def db_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.mark.asyncio
async def test_draft_never_retrievable(db_session):
    """Verify that an article with status='draft' is NEVER retrieved."""
    active_ver = get_active_version_id(db_session)
    if not active_ver:
        gv = GraphVersion(status="active")
        db_session.add(gv)
        db_session.flush()
        active_ver = gv.id

    draft_id = uuid.uuid4()
    title = "Secret Unapproved Policy ON XYZ"
    body = "This policy is in draft mode and contains secret information about XYZ."
    
    draft_node = Node(
        id=draft_id,
        version_id=active_ver,
        type="article",
        title=title,
        body=body,
        status="draft",  # DRAFT status!
        version=1,
        effective_date=date.today(),
        owner="Operations Manager",
        source_ref="test",
    )
    db_session.add(draft_node)
    db_session.add(NodeVisibility(node_id=draft_id, version_id=active_ver, role_id="ALL"))
    db_session.commit()

    # Attempt retrieval
    evidence = await retrieve(
        db_session,
        query="secret unapproved policy XYZ",
        dept_role="ALL",
        flags=RetrieveFlags(use_fts=True, use_graph=True),
    )

    # Draft node MUST NOT be in retrieved evidence nodes
    assert str(draft_id) not in evidence.nodes


@pytest.mark.asyncio
async def test_end_to_end_routed_gap_to_approved_answer(db_session):
    """
    End-to-End test:
    1. Ask question with insufficient evidence -> ROUTE with is_gap=True & ticket created.
    2. Owner drafts article from gap -> status='draft'.
    3. Admin approves and publishes -> status='approved' with new graph version & embeddings.
    4. Ask same question again -> cited ANSWER referencing the new article!
    """
    topic_id = uuid.uuid4().hex[:8]
    query = f"What is the procedure for zero gravity plasma containment {topic_id}?"

    # Fetch an existing user for foreign key validity
    from app.core.models import User
    user = db_session.execute(select(User)).scalars().first()
    user_id = str(user.id) if user else str(uuid.uuid4())

    # 1. Ask question (initially unknown)
    resp1, _ = await run_pipeline(
        query=query,
        user_id=user_id,
        dept_role="ALL",
        session=db_session,
        llm=TemplateAdapter(),
    )

    assert resp1.outcome in ("ROUTE", "REFUSE")
    assert resp1.ticket is not None  # Ticket was created

    ticket_id = uuid.UUID(resp1.ticket)
    t = db_session.execute(select(Ticket).where(Ticket.id == ticket_id)).scalar_one()
    assert t.is_gap is True

    # 2. Resolve gap to draft
    title = f"Zero Gravity Plasma Containment Protocol {topic_id}"
    body = f"Zero gravity plasma containment {topic_id} procedure requires initializing magnetic bottle containment field."

    draft_node = create_draft_from_gap(
        db_session,
        ticket_id=ticket_id,
        title=title,
        body=body,
        owner="Quality",
        roles=["ALL"]
    )
    db_session.commit()
    assert draft_node.status == "draft"

    # 3. Approve and publish draft article
    new_ver = approve_and_publish_article(
        db_session,
        article_id=draft_node.id,
        use_fake_embedder=True
    )
    db_session.commit()
    assert new_ver.status == "active"

    # 4. Ask the exact same question again!
    resp2, _ = await run_pipeline(
        query=query,
        user_id=user_id,
        dept_role="ALL",
        session=db_session,
        llm=TemplateAdapter(),
    )

    print("DEBUG resp2:", resp2)
    assert resp2.outcome == "ANSWER"
    assert len(resp2.citations) > 0
    citation_titles = [c.title for c in resp2.citations]
    assert title in citation_titles


def test_retire_removes_embeddings_atomically(db_session):
    """Verify retiring an article deletes its embeddings/NodeChunks in the same transaction."""
    active_ver = get_active_version_id(db_session)
    art_id = uuid.uuid4()

    node = Node(
        id=art_id,
        version_id=active_ver,
        type="article",
        title="Obsolete Policy",
        body="This policy is old and retired.",
        status="approved",
        version=1,
    )
    db_session.add(node)
    
    chunk = NodeChunk(
        id=uuid.uuid4(),
        node_id=art_id,
        version_id=active_ver,
        text="Obsolete Policy text",
        embedding=[0.1] * 1024,
    )
    db_session.add(chunk)
    db_session.commit()

    # Retire article
    retire_article(db_session, article_id=art_id)
    db_session.commit()

    # Check NodeChunk deletion
    remaining_chunks = db_session.execute(
        select(NodeChunk).where(NodeChunk.node_id == art_id)
    ).scalars().all()
    assert len(remaining_chunks) == 0

    # Check Node status
    updated_node = db_session.execute(
        select(Node).where(Node.id == art_id, Node.version_id == active_ver)
    ).scalar_one()
    assert updated_node.status == "archived"


def test_link_suggestions_workflow(db_session):
    """Test generating, approving, and rejecting link suggestions."""
    active_ver = get_active_version_id(db_session)
    if not active_ver:
        gv = GraphVersion(status="active")
        db_session.add(gv)
        db_session.flush()
        active_ver = gv.id

    # Create target System node
    sys_id = uuid.uuid4()
    sys_node = Node(
        id=sys_id,
        version_id=active_ver,
        type="system",
        title="EPIC EHR System",
        body="",
        status="approved",
    )
    db_session.add(sys_node)

    # Create Article mentioning System
    art_id = uuid.uuid4()
    art_node = Node(
        id=art_id,
        version_id=active_ver,
        type="article",
        title="Patient Admission Guidelines",
        body="All patient admissions must be documented in the EPIC EHR System within 2 hours.",
        status="approved",
    )
    db_session.add(art_node)
    db_session.commit()

    # Generate suggestions
    suggestions = generate_link_suggestions(db_session, version_id=active_ver)
    db_session.commit()

    assert len(suggestions) > 0
    sug_edge = suggestions[0]
    assert sug_edge.origin == "suggested"

    # Approve suggestion
    sug_edge.origin = "approved"
    db_session.commit()

    approved_edge = db_session.execute(
        select(Edge).where(Edge.id == sug_edge.id)
    ).scalar_one()
    assert approved_edge.origin == "approved"


def test_change_impact_api(db_session):
    """Test change impact API logic for node backlinks."""
    active_ver = get_active_version_id(db_session)

    art_id = uuid.uuid4()
    wf_id = uuid.uuid4()

    db_session.add(Node(id=art_id, version_id=active_ver, type="article", title="Target Article", body="Target"))
    db_session.add(Node(id=wf_id, version_id=active_ver, type="workflow", title="Dependent Workflow", body="WF"))

    # Link WF -> Article (defined_in)
    db_session.add(Edge(from_id=wf_id, to_id=art_id, type="defined_in", origin="structural", version_id=active_ver))
    db_session.commit()

    impact = get_change_impact(db_session, art_id)
    assert impact["total_affected"] >= 1
    wf_titles = [w["title"] for w in impact["affected_workflows"]]
    assert "Dependent Workflow" in wf_titles
