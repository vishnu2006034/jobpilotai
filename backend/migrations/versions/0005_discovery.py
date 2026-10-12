"""Private source subscriptions, provider snapshots, and new-posting notices."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0005"
down_revision = "0004"


def upgrade():
    op.add_column("jobs", sa.Column("provenance", JSONB(), nullable=False, server_default='{"kind":"manual"}'))
    op.create_table("discovery_sources", sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False), sa.Column("schedule_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(30), nullable=False), sa.Column("board", sa.String(100), nullable=False),
        sa.Column("name", sa.String(160), nullable=False), sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("last_success_at", sa.DateTime(timezone=True)), sa.Column("last_requested_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "provider", "board"), sa.UniqueConstraint("user_id", "id"),
        sa.ForeignKeyConstraint(["user_id", "schedule_id"], ["task_schedules.user_id", "task_schedules.id"]))
    op.create_table("discovered_postings", sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), nullable=False), sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("external_id", sa.String(150), nullable=False), sa.Column("url", sa.String(2048), nullable=False),
        sa.Column("data", JSONB(), nullable=False), sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False), sa.Column("target", JSONB(), nullable=False),
        sa.Column("target_status", sa.String(30), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False), sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("missing_since", sa.DateTime(timezone=True)), sa.Column("closed_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("source_id", "external_id"),
        sa.ForeignKeyConstraint(["user_id", "source_id"], ["discovery_sources.user_id", "discovery_sources.id"]))
    op.create_index("ix_discovered_postings_user_id", "discovered_postings", ["user_id"])
    op.create_index("ix_discovered_postings_target_status", "discovered_postings", ["target_status"])
    op.create_table("discovery_notices", sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), nullable=False), sa.Column("task_id", sa.Uuid(), nullable=False, unique=True),
        sa.Column("source_name", sa.String(160), nullable=False), sa.Column("potential_count", sa.Integer(), nullable=False),
        sa.Column("review_count", sa.Integer(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["user_id", "task_id"], ["background_tasks.user_id", "background_tasks.id"]))
    op.create_index("ix_discovery_notices_user_id", "discovery_notices", ["user_id"])


def downgrade():
    for name in ("discovery_notices", "discovered_postings", "discovery_sources"):
        op.drop_table(name)
    op.drop_column("jobs", "provenance")
