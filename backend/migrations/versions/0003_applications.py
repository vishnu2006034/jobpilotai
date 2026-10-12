"""Manual application state and append-only evidence timeline."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0003"
down_revision = "0002"


def upgrade():
    op.create_table("applications", sa.Column("id", sa.Uuid(), primary_key=True),
                    sa.Column("user_id", sa.Uuid(), nullable=False), sa.Column("job_id", sa.Uuid(), nullable=False),
                    sa.Column("state", sa.String(), nullable=False), sa.Column("version", sa.Integer(), nullable=False),
                    sa.Column("applied_at", sa.DateTime(timezone=True)),
                    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
                    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
                    sa.UniqueConstraint("user_id", "job_id"), sa.UniqueConstraint("user_id", "id"),
                    sa.ForeignKeyConstraint(["user_id", "job_id"], ["jobs.user_id", "jobs.id"]))
    op.create_index("ix_applications_user_id", "applications", ["user_id"])
    op.create_table("application_events", sa.Column("id", sa.Uuid(), primary_key=True),
                    sa.Column("user_id", sa.Uuid(), nullable=False), sa.Column("application_id", sa.Uuid(), nullable=False),
                    sa.Column("command_id", sa.Uuid(), nullable=False), sa.Column("request_hash", sa.String(), nullable=False),
                    sa.Column("version", sa.Integer(), nullable=False), sa.Column("previous_state", sa.String()),
                    sa.Column("next_state", sa.String(), nullable=False), sa.Column("evidence", JSONB(), nullable=False),
                    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
                    sa.UniqueConstraint("application_id", "command_id"), sa.UniqueConstraint("application_id", "version"),
                    sa.ForeignKeyConstraint(["user_id", "application_id"], ["applications.user_id", "applications.id"]))
    op.execute("""CREATE FUNCTION reject_event_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN RAISE EXCEPTION 'Application events are append-only'; END; $$""")
    op.execute("""CREATE TRIGGER immutable_application_events BEFORE UPDATE OR DELETE ON application_events
        FOR EACH ROW EXECUTE FUNCTION reject_event_mutation()""")


def downgrade():
    op.drop_table("application_events")
    op.execute("DROP FUNCTION reject_event_mutation()")
    op.drop_table("applications")
