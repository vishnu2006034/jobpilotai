"""Private manual jobs, saved jobs and explainable matches."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0002"
down_revision = "0001"


def upgrade():
    op.create_table("jobs", sa.Column("id", sa.Uuid(), primary_key=True),
                    sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
                    sa.Column("source_url", sa.String(2048), nullable=False), sa.Column("data", JSONB(), nullable=False),
                    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
                    sa.UniqueConstraint("user_id", "source_url"), sa.UniqueConstraint("user_id", "id"))
    op.create_index("ix_jobs_user_id", "jobs", ["user_id"])
    op.create_index("ix_jobs_created_at", "jobs", ["created_at"])
    op.create_table("saved_jobs", sa.Column("user_id", sa.Uuid(), primary_key=True),
                    sa.Column("job_id", sa.Uuid(), primary_key=True), sa.Column("saved_at", sa.DateTime(timezone=True), nullable=False),
                    sa.ForeignKeyConstraint(["user_id", "job_id"], ["jobs.user_id", "jobs.id"], ondelete="CASCADE"))
    op.create_table("user_job_matches", sa.Column("user_id", sa.Uuid(), primary_key=True),
                    sa.Column("job_id", sa.Uuid(), primary_key=True), sa.Column("profile_version", sa.Integer(), nullable=False),
                    sa.Column("result", JSONB(), nullable=False), sa.Column("scored_at", sa.DateTime(timezone=True), nullable=False),
                    sa.ForeignKeyConstraint(["user_id", "job_id"], ["jobs.user_id", "jobs.id"], ondelete="CASCADE"))


def downgrade():
    for table in ("user_job_matches", "saved_jobs", "jobs"):
        op.drop_table(table)
