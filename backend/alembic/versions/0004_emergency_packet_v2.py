"""Emergency Packet v2: 端末署名・重複判定キー・時刻・監査ログ.

既存のv1の行は、追加した列がすべてNULLのまま動く(制約はNULLを許可する)。
"""

from alembic import op

revision = "0004_emergency_packet_v2"
down_revision = "0003_shelter_capacity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE emergency_packets ADD COLUMN IF NOT EXISTS device_id TEXT;
        ALTER TABLE emergency_packets ADD COLUMN IF NOT EXISTS key_id TEXT;
        ALTER TABLE emergency_packets ADD COLUMN IF NOT EXISTS install_id TEXT;
        ALTER TABLE emergency_packets ADD COLUMN IF NOT EXISTS sequence TEXT;
        ALTER TABLE emergency_packets ADD COLUMN IF NOT EXISTS reported_at TIMESTAMPTZ;
        ALTER TABLE emergency_packets ADD COLUMN IF NOT EXISTS hub_received_at TIMESTAMPTZ;
        ALTER TABLE emergency_packets ADD COLUMN IF NOT EXISTS cloud_synced_at TIMESTAMPTZ;
        ALTER TABLE emergency_packets ADD COLUMN IF NOT EXISTS time_trust TEXT;
        ALTER TABLE emergency_packets ADD COLUMN IF NOT EXISTS signature_status TEXT;
        ALTER TABLE emergency_packets ADD COLUMN IF NOT EXISTS observation_id TEXT
            REFERENCES observations(id) ON DELETE SET NULL;

        ALTER TABLE emergency_packets DROP CONSTRAINT IF EXISTS emergency_packets_time_trust_check;
        ALTER TABLE emergency_packets ADD CONSTRAINT emergency_packets_time_trust_check CHECK (
            time_trust IS NULL OR time_trust IN ('TRUSTED', 'UNTRUSTED')
        );
        ALTER TABLE emergency_packets DROP CONSTRAINT IF EXISTS emergency_packets_signature_status_check;
        ALTER TABLE emergency_packets ADD CONSTRAINT emergency_packets_signature_status_check CHECK (
            signature_status IS NULL OR signature_status IN ('SIGNATURE_VALID', 'UNSIGNED_V1')
        );
        -- v1の行は3列ともNULLなので、この一意制約の対象外になる(NULLは重複扱いされない)。
        ALTER TABLE emergency_packets DROP CONSTRAINT IF EXISTS emergency_packets_device_install_sequence_key;
        ALTER TABLE emergency_packets ADD CONSTRAINT emergency_packets_device_install_sequence_key
            UNIQUE (device_id, install_id, sequence);
        CREATE INDEX IF NOT EXISTS emergency_packets_observation_idx
            ON emergency_packets (observation_id);

        -- 既存の verification_status(本部職員による確認)とは別物。Webの報告はNULL。
        ALTER TABLE observations ADD COLUMN IF NOT EXISTS signature_status TEXT;
        ALTER TABLE observations DROP CONSTRAINT IF EXISTS observations_signature_status_check;
        ALTER TABLE observations ADD CONSTRAINT observations_signature_status_check CHECK (
            signature_status IS NULL OR signature_status IN ('SIGNATURE_VALID', 'UNSIGNED_V1')
        );

        -- 認証失敗・重複キーの内容違いを記録する監査ログ。通常の報告とは分けて持つ。
        CREATE TABLE IF NOT EXISTS packet_security_events (
            id TEXT PRIMARY KEY,
            event_type TEXT NOT NULL CHECK (
                event_type IN ('PACKET_AUTH_FAILED', 'PACKET_DUPLICATE_CONFLICT')
            ),
            reason TEXT NOT NULL,
            device_id TEXT,
            key_id TEXT,
            install_id TEXT,
            sequence TEXT,
            raw_packet TEXT NOT NULL,
            existing_packet_id TEXT,
            hub_received_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE INDEX IF NOT EXISTS packet_security_events_created_idx
            ON packet_security_events (created_at DESC);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS packet_security_events;
        ALTER TABLE observations DROP CONSTRAINT IF EXISTS observations_signature_status_check;
        ALTER TABLE observations DROP COLUMN IF EXISTS signature_status;
        DROP INDEX IF EXISTS emergency_packets_observation_idx;
        ALTER TABLE emergency_packets DROP CONSTRAINT IF EXISTS emergency_packets_device_install_sequence_key;
        ALTER TABLE emergency_packets DROP CONSTRAINT IF EXISTS emergency_packets_signature_status_check;
        ALTER TABLE emergency_packets DROP CONSTRAINT IF EXISTS emergency_packets_time_trust_check;
        ALTER TABLE emergency_packets
            DROP COLUMN IF EXISTS observation_id,
            DROP COLUMN IF EXISTS signature_status,
            DROP COLUMN IF EXISTS time_trust,
            DROP COLUMN IF EXISTS cloud_synced_at,
            DROP COLUMN IF EXISTS hub_received_at,
            DROP COLUMN IF EXISTS reported_at,
            DROP COLUMN IF EXISTS sequence,
            DROP COLUMN IF EXISTS install_id,
            DROP COLUMN IF EXISTS key_id,
            DROP COLUMN IF EXISTS device_id;
        """
    )
