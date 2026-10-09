"""baseline schema

Revision ID: 0001
Revises:
Create Date: 2026-10-09
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID, TSVECTOR
from pgvector.sqlalchemy import Vector

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    # ── Create enums idempotently via DO block ──
    enum_defs = [
        ("graph_status", ["draft", "active", "archived"]),
        ("node_status",  ["draft", "approved", "archived"]),
        ("edge_origin",  ["structural", "suggested", "approved", "computed"]),
        ("app_role",     ["employee", "agent", "admin"]),
        ("ticket_status",["open", "in_progress", "resolved", "closed"]),
        ("outcome_type", ["ANSWER", "GUIDE", "ROUTE", "REFUSE"]),
        ("mode_type",    ["llm", "template"]),
        ("eval_split",   ["seed", "heldout"]),
    ]
    for name, values in enum_defs:
        vals = ", ".join(f"'{v}'" for v in values)
        conn.execute(sa.text(f"""
            DO $$ BEGIN
              IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = '{name}') THEN
                CREATE TYPE {name} AS ENUM ({vals});
              END IF;
            END $$;
        """))


    # ── graph_versions ──
    op.create_table(
        "graph_versions",
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True),
        sa.Column("status", sa.Enum(name="graph_status", create_type=False), nullable=False, server_default="draft"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        if_not_exists=True,
    )

    # ── nodes ──
    op.create_table(
        "nodes",
        sa.Column("id", PG_UUID(as_uuid=True), nullable=False),
        sa.Column("version_id", PG_UUID(as_uuid=True), sa.ForeignKey("graph_versions.id"), nullable=False),
        sa.Column("type", sa.String(64), nullable=False),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("body", sa.Text, nullable=False, server_default=""),
        sa.Column("status", sa.Enum(name="node_status", create_type=False), nullable=False, server_default="draft"),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("effective_date", sa.Date, nullable=True),
        sa.Column("review_date", sa.Date, nullable=True),
        sa.Column("owner", sa.String(128), nullable=True),
        sa.Column("source_ref", sa.Text, nullable=True),
        sa.Column("content_hash", sa.String(64), nullable=True),
        sa.UniqueConstraint("id", "version_id", name="pk_nodes"),
        sa.PrimaryKeyConstraint("id", "version_id", name="pk_nodes_pkey"),
        if_not_exists=True,
    )

    # ── edges ──
    op.create_table(
        "edges",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("from_id", PG_UUID(as_uuid=True), nullable=False),
        sa.Column("to_id", PG_UUID(as_uuid=True), nullable=False),
        sa.Column("type", sa.String(64), nullable=False),
        sa.Column("origin", sa.Enum(name="edge_origin", create_type=False), nullable=False, server_default="structural"),
        sa.Column("note", sa.Text, nullable=True),
        sa.Column("version_id", PG_UUID(as_uuid=True), sa.ForeignKey("graph_versions.id"), nullable=False),
        if_not_exists=True,
    )

    # ── node_visibility ──
    op.create_table(
        "node_visibility",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("node_id", PG_UUID(as_uuid=True), nullable=False),
        sa.Column("version_id", PG_UUID(as_uuid=True), sa.ForeignKey("graph_versions.id"), nullable=False),
        sa.Column("role_id", sa.String(64), nullable=False),
        if_not_exists=True,
    )

    # ── node_chunks ──
    op.create_table(
        "node_chunks",
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True),
        sa.Column("node_id", PG_UUID(as_uuid=True), nullable=False),
        sa.Column("version_id", PG_UUID(as_uuid=True), sa.ForeignKey("graph_versions.id"), nullable=False),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("embedding", Vector(1024), nullable=True),
        sa.Column("tsv", TSVECTOR, nullable=True),
        sa.Column("content_hash", sa.String(64), nullable=True),
        sa.Column("embedding_model", sa.String(64), nullable=True),
        if_not_exists=True,
    )
    # GIN index on tsv — create separately so it can be checked
    conn.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_node_chunks_tsv ON node_chunks USING gin(tsv)"
    ))

    # ── routing_rules ──
    op.create_table(
        "routing_rules",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("intent", sa.String(128), nullable=False),
        sa.Column("team", sa.String(128), nullable=False),
        sa.Column("urgency", sa.String(32), nullable=False, server_default="normal"),
        sa.Column("condition_json", JSONB, nullable=True),
        sa.Column("active", sa.Boolean, server_default="true"),
        if_not_exists=True,
    )

    # ── policy_thresholds ──
    op.create_table(
        "policy_thresholds",
        sa.Column("key", sa.String(128), primary_key=True),
        sa.Column("value", sa.Float, nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        if_not_exists=True,
    )

    # ── field_definitions ──
    op.create_table(
        "field_definitions",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("workflow_key", sa.String(128), nullable=False),
        sa.Column("field_name", sa.String(128), nullable=False),
        sa.Column("field_type", sa.String(64), nullable=False, server_default="string"),
        sa.Column("required", sa.Boolean, server_default="true"),
        sa.Column("validation_regex", sa.Text, nullable=True),
        sa.Column("order", sa.Integer, server_default="0"),
        if_not_exists=True,
    )

    # ── domain_config ──
    op.create_table(
        "domain_config",
        sa.Column("key", sa.String(128), primary_key=True),
        sa.Column("value", JSONB, nullable=False),
        if_not_exists=True,
    )

    # ── users ──
    op.create_table(
        "users",
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(255), unique=True, nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("password_hash", sa.Text, nullable=False),
        sa.Column("app_role", sa.Enum(name="app_role", create_type=False), nullable=False, server_default="employee"),
        sa.Column("active", sa.Boolean, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        if_not_exists=True,
    )

    # ── dept_roles ──
    op.create_table(
        "dept_roles",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(128), unique=True, nullable=False),
        if_not_exists=True,
    )

    # ── user_dept_roles ──
    op.create_table(
        "user_dept_roles",
        sa.Column("user_id", PG_UUID(as_uuid=True), sa.ForeignKey("users.id"), primary_key=True),
        sa.Column("dept_role_id", sa.BigInteger, sa.ForeignKey("dept_roles.id"), primary_key=True),
        if_not_exists=True,
    )

    # ── shifts ──
    op.create_table(
        "shifts",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("user_id", PG_UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("role", sa.String(128), nullable=True),
        if_not_exists=True,
    )

    # ── workflow_sessions ──
    op.create_table(
        "workflow_sessions",
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", PG_UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.Column("key", sa.String(128), nullable=False),
        sa.Column("workflow_id", sa.String(128), nullable=False),
        sa.Column("article_version", sa.Integer, nullable=True),
        sa.Column("slots_json", JSONB, nullable=False, server_default="{}"),
        sa.Column("vault_json_encrypted", sa.LargeBinary, nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        if_not_exists=True,
    )

    # ── conversations ──
    op.create_table(
        "conversations",
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", PG_UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        if_not_exists=True,
    )

    # ── messages ──
    op.create_table(
        "messages",
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True),
        sa.Column("conversation_id", PG_UUID(as_uuid=True), sa.ForeignKey("conversations.id"), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        if_not_exists=True,
    )

    # ── tickets ──
    op.create_table(
        "tickets",
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True),
        sa.Column("team", sa.String(128), nullable=False),
        sa.Column("urgency", sa.String(32), nullable=False, server_default="normal"),
        sa.Column("reason", sa.Text, nullable=False),
        sa.Column("is_gap", sa.Boolean, server_default="false"),
        sa.Column("status", sa.Enum(name="ticket_status", create_type=False), nullable=False, server_default="open"),
        sa.Column("opened_by", PG_UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.Column("assigned_to", PG_UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("summary", sa.Text, nullable=True),
        sa.Column("evidence_ids", JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        if_not_exists=True,
    )

    # ── ticket_events ──
    op.create_table(
        "ticket_events",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("ticket_id", PG_UUID(as_uuid=True), sa.ForeignKey("tickets.id"), nullable=False),
        sa.Column("actor_id", PG_UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("data", JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        if_not_exists=True,
    )

    # ── interactions ──
    op.create_table(
        "interactions",
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True),
        sa.Column("ts", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("user_id", PG_UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("dept_role", sa.String(128), nullable=True),
        sa.Column("outcome", sa.Enum(name="outcome_type", create_type=False), nullable=False),
        sa.Column("intent", sa.String(128), nullable=True),
        sa.Column("workflow_id", sa.String(128), nullable=True),
        sa.Column("confidence", sa.Float, nullable=True),
        sa.Column("band", sa.String(16), nullable=True),
        sa.Column("coverage_json", JSONB, nullable=True),
        sa.Column("latency_ms", sa.Integer, nullable=True),
        sa.Column("stage_ms_json", JSONB, nullable=True),
        sa.Column("mode", sa.Enum(name="mode_type", create_type=False), nullable=True),
        sa.Column("team", sa.String(128), nullable=True),
        sa.Column("is_gap", sa.Boolean, server_default="false"),
        sa.Column("citation_ok", sa.Boolean, nullable=True),
        sa.Column("feedback", sa.String(16), nullable=True),
        if_not_exists=True,
    )

    # ── audit_log ──
    op.create_table(
        "audit_log",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("payload", JSONB, nullable=False),
        sa.Column("prev_hash", sa.String(128), nullable=True),
        sa.Column("hash", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        if_not_exists=True,
    )

    # ── feedback ──
    op.create_table(
        "feedback",
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True),
        sa.Column("interaction_id", PG_UUID(as_uuid=True), sa.ForeignKey("interactions.id"), nullable=True),
        sa.Column("user_id", PG_UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("rating", sa.String(16), nullable=True),
        sa.Column("comment", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        if_not_exists=True,
    )

    # ── eval_cases ──
    op.create_table(
        "eval_cases",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("split", sa.Enum(name="eval_split", create_type=False), nullable=False, server_default="seed"),
        sa.Column("input_json", JSONB, nullable=False),
        sa.Column("expected_json", JSONB, nullable=False),
        if_not_exists=True,
    )

    # ── eval_runs ──
    op.create_table(
        "eval_runs",
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("config_json", JSONB, nullable=True),
        if_not_exists=True,
    )

    # ── eval_results ──
    op.create_table(
        "eval_results",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("run_id", PG_UUID(as_uuid=True), sa.ForeignKey("eval_runs.id"), nullable=False),
        sa.Column("case_id", sa.BigInteger, sa.ForeignKey("eval_cases.id"), nullable=False),
        sa.Column("result_json", JSONB, nullable=False),
        sa.Column("passed", sa.Boolean, nullable=True),
        if_not_exists=True,
    )

    # ── system_settings ──
    op.create_table(
        "system_settings",
        sa.Column("key", sa.String(128), primary_key=True),
        sa.Column("value", sa.Text, nullable=False),
        if_not_exists=True,
    )

    # ── Audit log: insert-only permissions ──
    conn.execute(sa.text("GRANT INSERT ON audit_log TO audit_writer;"))
    conn.execute(sa.text("GRANT USAGE, SELECT ON SEQUENCE audit_log_id_seq TO audit_writer;"))
    conn.execute(sa.text("REVOKE UPDATE, DELETE ON audit_log FROM PUBLIC;"))


def downgrade() -> None:
    tables = [
        "system_settings", "eval_results", "eval_runs", "eval_cases",
        "feedback", "audit_log", "interactions", "ticket_events", "tickets",
        "messages", "conversations", "workflow_sessions", "shifts",
        "user_dept_roles", "dept_roles", "users", "domain_config",
        "field_definitions", "policy_thresholds", "routing_rules",
        "node_chunks", "node_visibility", "edges", "nodes", "graph_versions",
    ]
    for t in tables:
        op.drop_table(t)

    conn = op.get_bind()
    for e in ["eval_split", "mode_type", "outcome_type", "ticket_status",
              "app_role", "edge_origin", "node_status", "graph_status"]:
        conn.execute(sa.text(f"DROP TYPE IF EXISTS {e}"))
