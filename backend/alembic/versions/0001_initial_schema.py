"""Create the ShelterOS schema and report trust fields."""

from alembic import op

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # IF NOT EXISTS keeps the migration compatible with databases created by v0.8.
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS shelters (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            location TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );

        CREATE TABLE IF NOT EXISTS observations (
            id TEXT PRIMARY KEY,
            shelter_id TEXT NOT NULL REFERENCES shelters(id) ON DELETE CASCADE,
            client_event_id TEXT NOT NULL UNIQUE,
            people_count INTEGER NOT NULL CHECK (people_count >= 0),
            water_stock INTEGER NOT NULL CHECK (water_stock >= 0),
            urgency TEXT NOT NULL CHECK (urgency IN ('NORMAL', 'WARNING', 'ALERT', 'CRITICAL')),
            memo TEXT NOT NULL DEFAULT '',
            observed_at TIMESTAMPTZ NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            reporter_name TEXT NOT NULL DEFAULT '',
            source TEXT NOT NULL DEFAULT 'web'
        );

        CREATE TABLE IF NOT EXISTS emergency_packets (
            id TEXT PRIMARY KEY,
            version TEXT NOT NULL,
            shelter_code TEXT NOT NULL,
            shelter_id TEXT REFERENCES shelters(id) ON DELETE SET NULL,
            packet_time TEXT NOT NULL,
            people_count INTEGER NOT NULL CHECK (people_count >= 0),
            water_stock INTEGER NOT NULL CHECK (water_stock >= 0),
            status TEXT NOT NULL CHECK (status IN ('NORMAL', 'WARNING', 'ALERT', 'CRITICAL')),
            request_code TEXT NOT NULL CHECK (
                request_code IN ('REQ_WATER', 'REQ_MEDICAL', 'REQ_FOOD', 'REQ_RESCUE', 'REQ_CONFIRM', 'NONE')
            ),
            raw_packet TEXT NOT NULL,
            received_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );

        ALTER TABLE observations ADD COLUMN IF NOT EXISTS reporter_email TEXT;
        ALTER TABLE observations ADD COLUMN IF NOT EXISTS reporter_type TEXT NOT NULL DEFAULT 'ANONYMOUS';
        ALTER TABLE observations ADD COLUMN IF NOT EXISTS verification_status TEXT NOT NULL DEFAULT 'UNVERIFIED';
        ALTER TABLE observations ADD COLUMN IF NOT EXISTS verified_by TEXT;
        ALTER TABLE observations ADD COLUMN IF NOT EXISTS verified_at TIMESTAMPTZ;

        ALTER TABLE observations DROP CONSTRAINT IF EXISTS observations_reporter_type_check;
        ALTER TABLE observations ADD CONSTRAINT observations_reporter_type_check CHECK (
            reporter_type IN ('ANONYMOUS', 'AUTHENTICATED_FIELD', 'AUTHENTICATED_HQ', 'LORA_GATEWAY')
        );
        ALTER TABLE observations DROP CONSTRAINT IF EXISTS observations_verification_status_check;
        ALTER TABLE observations ADD CONSTRAINT observations_verification_status_check CHECK (
            verification_status IN ('UNVERIFIED', 'VERIFIED', 'REJECTED')
        );

        CREATE INDEX IF NOT EXISTS observations_shelter_observed_idx
            ON observations (shelter_id, observed_at DESC, created_at DESC);
        CREATE INDEX IF NOT EXISTS observations_verification_idx
            ON observations (verification_status);
        CREATE INDEX IF NOT EXISTS emergency_packets_received_idx
            ON emergency_packets (received_at DESC);

        INSERT INTO shelters (id, name, location)
        VALUES
            ('AIT001', 'Shelter A', 'University Gymnasium'),
            ('AIT002', 'Shelter B', 'Lecture Hall'),
            ('AIT003', 'Shelter C', 'Student Center')
        ON CONFLICT (id) DO NOTHING;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS emergency_packets;")
    op.execute("DROP TABLE IF EXISTS observations;")
    op.execute("DROP TABLE IF EXISTS shelters;")
