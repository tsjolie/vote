"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-07-10
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

UUID = postgresql.UUID(as_uuid=False)
TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("username", sa.String(20), nullable=False),
        sa.Column("username_lower", sa.String(20), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("is_admin", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("username_lower", name="uq_users_username_lower"),
    )
    op.create_index("ix_users_username_lower", "users", ["username_lower"])

    op.create_table(
        "sessions",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("user_id", UUID, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("expires_at", TS, nullable=False),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_sessions_user_id", "sessions", ["user_id"])

    op.create_table(
        "polls",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("slug", sa.String(16), nullable=False),
        sa.Column("creator_id", UUID, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("closes_at", TS, nullable=True),
        sa.Column("closed_at", TS, nullable=True),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("slug", name="uq_polls_slug"),
    )
    op.create_index("ix_polls_slug", "polls", ["slug"])
    op.create_index("ix_polls_creator_id", "polls", ["creator_id"])

    op.create_table(
        "questions",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("poll_id", UUID, sa.ForeignKey("polls.id", ondelete="CASCADE"), nullable=False),
        sa.Column("position", sa.Integer, nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("is_required", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", TS, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_questions_poll_id", "questions", ["poll_id"])

    op.create_table(
        "options",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("question_id", UUID, sa.ForeignKey("questions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("position", sa.Integer, nullable=False),
        sa.Column("label", sa.String(200), nullable=False),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_options_question_id", "options", ["question_id"])

    op.create_table(
        "ballots",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("question_id", UUID, sa.ForeignKey("questions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", UUID, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("ranking", postgresql.JSONB, nullable=False),
        sa.Column("is_invalidated", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("submitted_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", TS, nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("question_id", "user_id", name="uq_ballot_question_user"),
    )
    op.create_index("ix_ballots_question_id", "ballots", ["question_id"])
    op.create_index("ix_ballots_user_id", "ballots", ["user_id"])

    op.create_table(
        "poll_bans",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("poll_id", UUID, sa.ForeignKey("polls.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", UUID, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("poll_id", "user_id", name="uq_poll_ban"),
    )
    op.create_index("ix_poll_bans_poll_id", "poll_bans", ["poll_id"])
    op.create_index("ix_poll_bans_user_id", "poll_bans", ["user_id"])

    op.create_table(
        "display_orders",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("question_id", UUID, sa.ForeignKey("questions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", UUID, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("order", postgresql.JSONB, nullable=False),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("question_id", "user_id", name="uq_display_order"),
    )
    op.create_index("ix_display_orders_question_id", "display_orders", ["question_id"])
    op.create_index("ix_display_orders_user_id", "display_orders", ["user_id"])


def downgrade() -> None:
    op.drop_table("display_orders")
    op.drop_table("poll_bans")
    op.drop_table("ballots")
    op.drop_table("options")
    op.drop_table("questions")
    op.drop_table("polls")
    op.drop_table("sessions")
    op.drop_table("users")
