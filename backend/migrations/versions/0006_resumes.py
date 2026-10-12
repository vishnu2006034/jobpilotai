"""Immutable resume text and reviewed extractive drafts."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0006"
down_revision = "0005"


def upgrade():
    op.create_table("resume_versions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(120), nullable=False), sa.Column("text", sa.Text(), nullable=False),
        sa.Column("digest", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("user_id", "id"), sa.UniqueConstraint("user_id", "digest"))
    op.create_table("resume_drafts",
        sa.Column("id", sa.Uuid(), primary_key=True), sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("resume_id", sa.Uuid(), nullable=False), sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("selected_blocks", JSONB(), nullable=False), sa.Column("text", sa.Text(), nullable=False),
        sa.Column("digest", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("user_id", "digest"),
        sa.ForeignKeyConstraint(["user_id", "resume_id"], ["resume_versions.user_id", "resume_versions.id"]),
        sa.ForeignKeyConstraint(["user_id", "job_id"], ["jobs.user_id", "jobs.id"]))


def downgrade():
    op.drop_table("resume_drafts")
    op.drop_table("resume_versions")
