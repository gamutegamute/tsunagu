"""Identify the exact resolution request reviewed by headquarters."""
from alembic import op

revision = "0005_incident_request_version"
down_revision = "0004_emergency_packet_v2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE incident_states ADD COLUMN resolution_request_version INTEGER NOT NULL DEFAULT 0;")
    # Repair already stored web clock errors as well as validating new inputs.
    op.execute("UPDATE observations SET observed_at = created_at WHERE source IN ('web', 'offline') AND observed_at > created_at;")


def downgrade() -> None:
    op.execute("ALTER TABLE incident_states DROP COLUMN resolution_request_version;")
