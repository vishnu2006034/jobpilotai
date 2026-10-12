"""Identity, revocable sessions and versioned profiles."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0001"
down_revision = None


def upgrade():
    op.create_table("users", sa.Column("id", sa.Uuid(), primary_key=True),
                    sa.Column("email", sa.String(254), nullable=False, unique=True),
                    sa.Column("password_hash", sa.String(), nullable=False),
                    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_table("profiles", sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
                    sa.Column("data", JSONB(), nullable=False), sa.Column("version", sa.Integer(), nullable=False))
    op.create_table("auth_sessions", sa.Column("token_hash", sa.String(64), primary_key=True),
                    sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
                    sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_auth_sessions_user_id", "auth_sessions", ["user_id"])
    op.create_index("ix_auth_sessions_expires_at", "auth_sessions", ["expires_at"])
    op.create_table("login_guards", sa.Column("key", sa.String(64), primary_key=True),
                    sa.Column("attempts", sa.Integer(), nullable=False),
                    sa.Column("window_start", sa.DateTime(timezone=True), nullable=False))


def downgrade():
    for table in ("login_guards", "auth_sessions", "profiles", "users"):
        op.drop_table(table)
