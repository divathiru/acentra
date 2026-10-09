"""Unit tests for RBAC visibility."""

import pytest
import uuid
from sqlalchemy import select, func
from app.core.database import SessionLocal
from app.core.models import Node, NodeVisibility
from app.knowledge.api import get_active_version_id, _visibility_clause

def test_rbac_billing_supervisor():
    """Verify that 'Billing' role cannot see 'Billing Supervisor' nodes."""
    with SessionLocal() as session:
        version_id = get_active_version_id(session)
        assert version_id is not None, "Graph must be seeded"
        
        # Create a test node requiring "Billing Supervisor" in the active version
        restricted_node = Node(
            version_id=version_id,
            type="policy",
            title="Billing Supervisor Only Node",
            body="Secret billing stuff",
            status="approved"
        )
        session.add(restricted_node)
        session.flush()
        
        vis = NodeVisibility(
            node_id=restricted_node.id,
            version_id=version_id,
            role_id="Billing Supervisor"
        )
        session.add(vis)
        session.commit()
        
        restricted_node_id = restricted_node.id
        
        # Test visibility for 'Billing'
        res_billing = session.execute(
            select(Node).where(
                Node.id == restricted_node_id,
                _visibility_clause(["Billing"], version_id)
            )
        )
        assert res_billing.scalars().first() is None, "Billing role should not see this node"
        
        # Test visibility for 'Billing Supervisor'
        res_supervisor = session.execute(
            select(Node).where(
                Node.id == restricted_node_id,
                _visibility_clause(["Billing Supervisor"], version_id)
            )
        )
        assert res_supervisor.scalars().first() is not None, "Billing Supervisor role should see this node"
        
        # Create a generic node (visible to ALL)
        generic_node = Node(
            version_id=version_id,
            type="policy",
            title="Generic Node",
            body="Public info",
            status="approved"
        )
        session.add(generic_node)
        session.flush()
        
        vis_all = NodeVisibility(
            node_id=generic_node.id,
            version_id=version_id,
            role_id="ALL"
        )
        session.add(vis_all)
        session.commit()
        
        generic_node_id = generic_node.id
        
        res_generic = session.execute(
            select(Node).where(
                Node.id == generic_node_id,
                _visibility_clause(["Billing"], version_id)
            )
        )
        assert res_generic.scalars().first() is not None, "Billing role should see ALL nodes"
