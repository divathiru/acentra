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
        
        # Find a node that requires "Billing Supervisor"
        res = session.execute(
            select(Node.id)
            .join(NodeVisibility, Node.id == NodeVisibility.node_id)
            .where(NodeVisibility.role_id == "Billing Supervisor")
        )
        restricted_node_id = res.scalar()
        assert restricted_node_id is not None, "Missing Billing Supervisor node in test data"
        
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
        
        # Also verify that a generic node (visible to ALL) is visible to 'Billing'
        res = session.execute(
            select(Node.id)
            .join(NodeVisibility, Node.id == NodeVisibility.node_id)
            .where(NodeVisibility.role_id == "ALL")
            .limit(1)
        )
        generic_node_id = res.scalar()
        
        res_generic = session.execute(
            select(Node).where(
                Node.id == generic_node_id,
                _visibility_clause(["Billing"], version_id)
            )
        )
        assert res_generic.scalars().first() is not None, "Billing role should see ALL nodes"
