"""Add the incident_states table (決定事項34-a/34-b: Incident状態の永続化)."""

from alembic import op

revision = "0002_incident_states"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS incident_states (
            observation_id TEXT PRIMARY KEY REFERENCES observations(id) ON DELETE CASCADE,
            confirm_status TEXT NOT NULL DEFAULT 'UNCONFIRMED'
                CHECK (confirm_status IN ('UNCONFIRMED', 'CONFIRMED')),
            confirmed_by TEXT,
            confirmed_at TIMESTAMPTZ,
            confirm_memo TEXT,
            resolution_request_memo TEXT,
            resolution_request_staff_name TEXT,
            resolution_request_active_shelter_id TEXT,
            resolution_request_at TIMESTAMPTZ,
            resolution_memo TEXT,
            resolution_staff_name TEXT,
            resolution_approver_name TEXT,
            resolution_approved_at TIMESTAMPTZ
        );
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS incident_states;")
