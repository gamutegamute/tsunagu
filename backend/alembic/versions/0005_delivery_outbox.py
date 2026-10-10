"""クラウドへの配送(Outbox)と配送履歴.

emergency_packets / observations には配送状態の列を足さない(1件の報告に複数の配送履歴を残すため)。
"""

from alembic import op

revision = "0005_delivery_outbox"
down_revision = "0004_emergency_packet_v2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS delivery_outbox (
            id TEXT PRIMARY KEY,
            emergency_packet_id TEXT NOT NULL REFERENCES emergency_packets(id) ON DELETE CASCADE,
            destination_id TEXT NOT NULL,
            state TEXT NOT NULL DEFAULT 'PENDING' CHECK (
                state IN ('PENDING', 'SENDING', 'ACCEPTED', 'QUARANTINED', 'STOPPED')
            ),
            attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
            next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            lease_until TIMESTAMPTZ,
            last_attempt_at TIMESTAMPTZ,
            last_error_code TEXT,
            last_error_summary TEXT,
            accepted_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT delivery_outbox_packet_destination_key UNIQUE (emergency_packet_id, destination_id)
        );
        CREATE INDEX IF NOT EXISTS delivery_outbox_due_idx
            ON delivery_outbox (destination_id, state, next_attempt_at);

        CREATE TABLE IF NOT EXISTS delivery_attempts (
            id TEXT PRIMARY KEY,
            -- プローブ(kind=PROBE)は報告に紐づかないので NULL。
            outbox_id TEXT REFERENCES delivery_outbox(id) ON DELETE CASCADE,
            destination_id TEXT NOT NULL,
            kind TEXT NOT NULL CHECK (kind IN ('DELIVERY', 'PROBE')),
            attempted_at TIMESTAMPTZ NOT NULL,
            outcome TEXT NOT NULL,
            http_status INTEGER,
            latency_ms INTEGER CHECK (latency_ms IS NULL OR latency_ms >= 0),
            error_code TEXT,
            CHECK ((kind = 'PROBE') = (outbox_id IS NULL))
        );
        CREATE INDEX IF NOT EXISTS delivery_attempts_destination_idx
            ON delivery_attempts (destination_id, attempted_at DESC);
        CREATE INDEX IF NOT EXISTS delivery_attempts_outbox_idx
            ON delivery_attempts (outbox_id, attempted_at);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS delivery_attempts;
        DROP TABLE IF EXISTS delivery_outbox;
        """
    )
