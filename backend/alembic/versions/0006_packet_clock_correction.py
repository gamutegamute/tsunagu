"""Repair packet clocks, retaining original values for rollback."""
from alembic import op

revision = "0006_packet_clock_correction"
down_revision = "0005_incident_request_version"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE packet_clock_corrections AS
        SELECT o.id AS observation_id, o.observed_at AS original_observed_at,
            o.created_at AS corrected_observed_at, p.id AS packet_id,
            p.time_trust AS original_time_trust
        FROM observations o LEFT JOIN emergency_packets p ON p.observation_id = o.id
        WHERE o.source = 'emergency_packet' AND o.observed_at > o.created_at;
        UPDATE emergency_packets p SET time_trust = 'UNTRUSTED'
        FROM packet_clock_corrections c WHERE c.packet_id = p.id;
        UPDATE observations o SET observed_at = c.corrected_observed_at
        FROM packet_clock_corrections c WHERE c.observation_id = o.id;
    """)


def downgrade():
    op.execute("""
        UPDATE observations o SET observed_at = c.original_observed_at
        FROM packet_clock_corrections c
        WHERE c.observation_id = o.id AND o.observed_at = c.corrected_observed_at;
        UPDATE emergency_packets p SET time_trust = c.original_time_trust
        FROM packet_clock_corrections c WHERE c.packet_id = p.id AND p.time_trust = 'UNTRUSTED';
        DROP TABLE packet_clock_corrections;
    """)
