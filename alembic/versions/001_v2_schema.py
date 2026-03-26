"""v2 schema: users, sessions, collaborator_invites, extend prompts

Revision ID: 001
Revises:
Create Date: 2026-03-23

Handles two cases:
  1. Fresh install   — creates all tables from scratch with v2 schema.
  2. v1 upgrade      — adds new tables, adds new columns to existing prompts,
                       backfills User/Session rows from existing string session_ids.
"""
from typing import Sequence, Union
from datetime import datetime

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    existing = inspector.get_table_names()

    # ------------------------------------------------------------------ #
    # 1. Create users table                                                #
    # ------------------------------------------------------------------ #
    if "users" not in existing:
        op.create_table(
            "users",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("telegram_id", sa.String(255), nullable=False),
            sa.Column("username", sa.String(255), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_users_id", "users", ["id"])
        op.create_index("ix_users_telegram_id", "users", ["telegram_id"], unique=True)

    # ------------------------------------------------------------------ #
    # 2. Create sessions table                                             #
    # ------------------------------------------------------------------ #
    if "sessions" not in existing:
        op.create_table(
            "sessions",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("owner_id", sa.Integer(), nullable=False),
            sa.Column("collaborator_id", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["collaborator_id"], ["users.id"]),
            sa.ForeignKeyConstraint(["owner_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_sessions_id", "sessions", ["id"])
        op.create_index("ix_sessions_owner_id", "sessions", ["owner_id"])

    # ------------------------------------------------------------------ #
    # 3. Create collaborator_invites table                                 #
    # ------------------------------------------------------------------ #
    if "collaborator_invites" not in existing:
        op.create_table(
            "collaborator_invites",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("session_id", sa.Integer(), nullable=False),
            sa.Column("inviter_id", sa.Integer(), nullable=False),
            sa.Column("invitee_telegram_username", sa.String(255), nullable=False),
            sa.Column("status", sa.String(20), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["inviter_id"], ["users.id"]),
            sa.ForeignKeyConstraint(["session_id"], ["sessions.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_collaborator_invites_id", "collaborator_invites", ["id"])

    # ------------------------------------------------------------------ #
    # 4. Create or alter prompts table                                     #
    # ------------------------------------------------------------------ #
    if "prompts" not in existing:
        # Fresh install — create full v2 prompts table directly
        op.create_table(
            "prompts",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=True),
            sa.Column("session_id", sa.Integer(), nullable=True),
            sa.Column("legacy_chat_id", sa.String(255), nullable=True),
            sa.Column("transcript", sa.Text(), nullable=True),
            sa.Column("features", sa.Text(), nullable=True),
            sa.Column("decisions", sa.Text(), nullable=True),
            sa.Column("next_steps", sa.Text(), nullable=True),
            sa.Column("blockers", sa.Text(), nullable=True),
            sa.Column("raw_summary", sa.Text(), nullable=True),
            sa.Column("challenges", sa.Text(), nullable=True),
            sa.Column("tags", sa.Text(), nullable=True),
            sa.Column("speaker_attribution", sa.Text(), nullable=True),
            sa.Column("embedding", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["session_id"], ["sessions.id"]),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_prompts_id", "prompts", ["id"])
        op.create_index("ix_prompts_user_id", "prompts", ["user_id"])
        op.create_index("ix_prompts_legacy_chat_id", "prompts", ["legacy_chat_id"])
    else:
        # v1 upgrade path
        existing_cols = {c["name"] for c in inspector.get_columns("prompts")}

        # Step A: add new columns (skip any that already exist)
        with op.batch_alter_table("prompts", schema=None) as batch_op:
            if "user_id" not in existing_cols:
                batch_op.add_column(sa.Column("user_id", sa.Integer(), nullable=True))
            if "session_fk_id" not in existing_cols and "session_id" in existing_cols:
                # Add temporary integer column; will be renamed after backfill
                batch_op.add_column(sa.Column("session_fk_id", sa.Integer(), nullable=True))
            if "transcript" not in existing_cols:
                batch_op.add_column(sa.Column("transcript", sa.Text(), server_default=""))
            if "tags" not in existing_cols:
                batch_op.add_column(sa.Column("tags", sa.Text(), server_default="[]"))
            if "speaker_attribution" not in existing_cols:
                batch_op.add_column(sa.Column("speaker_attribution", sa.Text(), nullable=True))
            if "embedding" not in existing_cols:
                batch_op.add_column(sa.Column("embedding", sa.Text(), nullable=True))
            if "legacy_chat_id" not in existing_cols:
                batch_op.add_column(sa.Column("legacy_chat_id", sa.String(255), nullable=True))

        # Step B: backfill Users and Sessions from existing string session_ids
        now = datetime.utcnow().isoformat()
        rows = bind.execute(
            text("SELECT DISTINCT session_id FROM prompts WHERE session_id IS NOT NULL")
        ).fetchall()

        for (old_chat_id,) in rows:
            if not old_chat_id:
                continue
            # Check if user already exists (idempotent)
            existing_user = bind.execute(
                text("SELECT id FROM users WHERE telegram_id = :tid"),
                {"tid": str(old_chat_id)},
            ).fetchone()
            if existing_user:
                user_id = existing_user[0]
            else:
                bind.execute(
                    text(
                        "INSERT INTO users (telegram_id, username, created_at)"
                        " VALUES (:tid, :uname, :ts)"
                    ),
                    {"tid": str(old_chat_id), "uname": "", "ts": now},
                )
                user_id = bind.execute(
                    text("SELECT id FROM users WHERE telegram_id = :tid"),
                    {"tid": str(old_chat_id)},
                ).fetchone()[0]

            # Create one session per user (v1 had no sessions concept)
            existing_session = bind.execute(
                text("SELECT id FROM sessions WHERE owner_id = :oid LIMIT 1"),
                {"oid": user_id},
            ).fetchone()
            if existing_session:
                session_id = existing_session[0]
            else:
                bind.execute(
                    text(
                        "INSERT INTO sessions (owner_id, collaborator_id, created_at)"
                        " VALUES (:oid, NULL, :ts)"
                    ),
                    {"oid": user_id, "ts": now},
                )
                session_id = bind.execute(
                    text(
                        "SELECT id FROM sessions WHERE owner_id = :oid ORDER BY id DESC LIMIT 1"
                    ),
                    {"oid": user_id},
                ).fetchone()[0]

            # Update prompts rows: copy old string session_id to legacy_chat_id,
            # set user_id and session_fk_id
            bind.execute(
                text(
                    "UPDATE prompts"
                    " SET user_id = :uid, session_fk_id = :sid, legacy_chat_id = :lcid"
                    " WHERE session_id = :old_sid"
                ),
                {
                    "uid": user_id,
                    "sid": session_id,
                    "lcid": str(old_chat_id),
                    "old_sid": old_chat_id,
                },
            )

        # Step C: rename session_id (string) → legacy_chat_id_orig (temp),
        #         rename session_fk_id → session_id (integer FK)
        # We do this in a single batch to keep SQLite happy.
        with op.batch_alter_table("prompts", schema=None) as batch_op:
            # Drop the old string session_id column
            batch_op.drop_column("session_id")
            # Rename session_fk_id to session_id
            batch_op.alter_column("session_fk_id", new_column_name="session_id")

        op.create_index("ix_prompts_user_id", "prompts", ["user_id"])
        op.create_index("ix_prompts_legacy_chat_id", "prompts", ["legacy_chat_id"])


def downgrade() -> None:
    # Minimal downgrade: drop v2-only tables and columns
    op.drop_table("collaborator_invites")
    op.drop_table("sessions")
    op.drop_table("users")
    # Restoring the original prompts schema would require another batch migration;
    # for safety this downgrade leaves prompts as-is.
