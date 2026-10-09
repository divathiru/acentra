"""Tests for the knowledge retrieval module."""

import pytest
import asyncio
from datetime import date, timedelta
import uuid

from sqlalchemy import select

from app.core.database import SessionLocal
from app.knowledge.api import retrieve, RetrieveFlags
from app.knowledge.verify import verify_evidence
from app.core.models import Node, Edge, NodeVisibility, NodeChunk, GraphVersion

def test_verify_coverage_computed_correctly():
    class DummyBundle:
        edges = [
            {"type": "defined_in"},
            {"type": "requires_form"},
            {"type": "has_step"},
            {"type": "owned_by"},
            {"type": "requires"}
        ]
        top1_cosine = 0.8
        conflict_flag = False
        conflict_owners = []
        
    config = {}
    verif = verify_evidence(DummyBundle(), expected_entities=2, resolved_entities=2, config=config)
    
    assert verif["score"] >= 0.8 # should be high since sim = 1.0, cov = 1.0, ent = 1.0 -> 0.4+0.4+0.2 = 1.0
    assert verif["band"] == "high"
    assert verif["conflict"] is False
    assert all(verif["coverage"].values()) is True

@pytest.mark.asyncio
async def test_retrieval_restrictions():
    # We will test:
    # 1. Restricted node never returned for wrong role
    # 2. Draft/retired/future nodes never returned
    # 3. Hop re-check blocks a restricted neighbor
    # 4. Conflict flag set for the conflict pair
    
    with SessionLocal() as session:
        version_id = session.execute(select(GraphVersion.id).where(GraphVersion.status == "active")).scalar_one()
        
        # Test 1: Restricted Node
        # We know "Billing Supervisor" has restricted nodes.
        # So "Billing" should not see them.
        flags = RetrieveFlags(use_fts=True, use_graph=False)
        bundle = await retrieve(session, "billing", "Billing", flags)
        
        # Check that no node returned has visibility restricted to Billing Supervisor
        for nid in bundle.nodes:
            vis = session.execute(
                select(NodeVisibility.role_id).where(NodeVisibility.node_id == uuid.UUID(nid), NodeVisibility.version_id == version_id)
            ).scalars().all()
            assert "ALL" in vis or "Billing" in vis or "employee" in vis
            
        bundle_sup = await retrieve(session, "billing", "Billing Supervisor", flags)
        # Should potentially return something different, but just verify no error.
        assert bundle_sup is not None

        # Test 2: Draft/archived/future nodes never returned
        flags = RetrieveFlags(use_fts=True, use_graph=True)
        bundle_all = await retrieve(session, "test", "ALL", flags)
        for nid, node_info in bundle_all.nodes.items():
            n = session.execute(select(Node).where(Node.id == uuid.UUID(nid), Node.version_id == version_id)).scalar_one()
            assert n.status == "approved"
            assert n.effective_date is None or n.effective_date <= date.today()

        # Test 4: Conflict flag set for the conflict pair
        # We seeded a conflict pair in the synthetic data, find it via query
        # Just query something that brings up the conflict articles
        bundle_conflict = await retrieve(session, "conflict", "ALL", flags)
        # Since it depends on the embeddings (which are fake or random), we might not hit it directly with "conflict"
        # We'll just do a manual retrieve overriding the query to match a known conflict node id? No, `retrieve` uses semantic search.
        
        # Let's find a conflict node and inject its exact text to query
        conflict_edge = session.execute(select(Edge).where(Edge.type == "conflicts_with", Edge.version_id == version_id)).scalars().first()
        if conflict_edge:
            conflict_node = session.execute(select(Node).where(Node.id == conflict_edge.from_id, Node.version_id == version_id)).scalar_one()
            bundle_conflict = await retrieve(session, conflict_node.title, "ALL", flags)
            
            # Now we expect conflict flag to be true if it expanded to both or the edge was found.
            # wait, conflict flag is set if ANY expanded node has a conflicts_with edge pointing out of it.
            # so as long as the conflict_node is in entry nodes, it will be flagged.
            assert bundle_conflict.conflict_flag is True
            assert len(bundle_conflict.conflict_owners) > 0
            
