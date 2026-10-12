"""Durable tasks, execution attempts and persisted interval schedules."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0004"
down_revision = "0003"


def upgrade():
    op.create_table("background_tasks", sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("task_type", sa.String(80), nullable=False), sa.Column("payload", JSONB(), nullable=False),
        sa.Column("resource_key", sa.String(160), nullable=False), sa.Column("idempotency_key", sa.String(160), nullable=False),
        sa.Column("status", sa.String(30), nullable=False), sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False), sa.Column("run_after", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_token", sa.Uuid()), sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("result", JSONB()), sa.Column("error_code", sa.String(100)),
        sa.UniqueConstraint("user_id", "idempotency_key"), sa.UniqueConstraint("user_id", "id"))
    op.create_index("ix_task_due", "background_tasks", ["status", "run_after"])
    op.create_index("ix_task_lease", "background_tasks", ["lease_expires_at"])
    op.create_index("uq_task_active_resource", "background_tasks", ["user_id", "resource_key"], unique=True,
                    postgresql_where=sa.text("status IN ('queued', 'running')"))
    op.create_table("task_attempts", sa.Column("task_id", sa.Uuid(), sa.ForeignKey("background_tasks.id"), primary_key=True),
        sa.Column("number", sa.Integer(), primary_key=True), sa.Column("lease_token", sa.Uuid(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False), sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(30), nullable=False), sa.Column("error_code", sa.String(100)))
    op.create_table("task_schedules", sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("task_type", sa.String(80), nullable=False), sa.Column("payload", JSONB(), nullable=False),
        sa.Column("resource_key", sa.String(160), nullable=False), sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("interval_minutes", sa.Integer(), nullable=False), sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "resource_key"), sa.UniqueConstraint("user_id", "id"))
    op.create_index("ix_task_schedules_next_run_at", "task_schedules", ["next_run_at"])


def downgrade():
    for name in ("task_schedules", "task_attempts", "background_tasks"):
        op.drop_table(name)
