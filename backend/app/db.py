import os
from contextlib import contextmanager
from typing import Iterator

import psycopg
from psycopg.rows import dict_row

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://shelteros:shelteros@localhost:5432/shelteros")


@contextmanager
def get_conn() -> Iterator[psycopg.Connection]:
    with psycopg.connect(DATABASE_URL, row_factory=dict_row) as conn:
        yield conn


def seed_demo_data() -> None:
    if os.getenv("DEMO_SEED", "false").lower() != "true":
        return

    with get_conn() as conn:
        _insert_demo_data(conn)
        conn.commit()


def _insert_demo_data(conn: psycopg.Connection) -> None:
    conn.execute(
        """
        INSERT INTO shelters (id, name, location, capacity)
        VALUES
            ('AIT001', 'Shelter A', 'University Gymnasium', 200),
            ('AIT002', 'Shelter B', 'Lecture Hall', 250),
            ('AIT003', 'Shelter C', 'Student Center', 150)
        ON CONFLICT (id) DO NOTHING;
        """
    )
    conn.execute(
        """
        INSERT INTO observations (
            id, shelter_id, client_event_id, people_count, water_stock,
            urgency, memo, observed_at, reporter_name, reporter_type,
            verification_status, source
        )
        VALUES (
            'OBS-demo-seed-1', 'AIT001', 'demo-event-seed-1', 45, 25,
            'NORMAL', '', now() - interval '2 hours', '佐藤',
            'AUTHENTICATED_FIELD', 'VERIFIED', 'web'
        )
        ON CONFLICT (client_event_id) DO NOTHING;
        """
    )
    conn.execute(
        """
        INSERT INTO emergency_packets (
            id, version, shelter_code, shelter_id, packet_time,
            people_count, water_stock, status, request_code, raw_packet, received_at
        )
        VALUES (
            'EP-demo-seed-2', 'v1', 'AIT002', 'AIT002', '21:04',
            170, 18, 'WARNING', 'REQ_WATER',
            'v1|AIT002|21:04|170|18|WARNING|REQ_WATER', now() - interval '1 hour'
        )
        ON CONFLICT (id) DO NOTHING;
        """
    )
    conn.execute(
        """
        INSERT INTO observations (
            id, shelter_id, client_event_id, people_count, water_stock,
            urgency, memo, observed_at, reporter_name, reporter_type,
            verification_status, source
        )
        VALUES (
            'OBS-demo-seed-2', 'AIT002', 'LORA-demo-seed-2', 170, 18,
            'WARNING', '[Demo] [LoRa] Status: WARNING, Req: REQ_WATER',
            now() - interval '1 hour', 'LoRa Packet', 'LORA_GATEWAY',
            'UNVERIFIED', 'emergency_packet'
        )
        ON CONFLICT (client_event_id) DO NOTHING;
        """
    )
    conn.execute(
        """
        INSERT INTO observations (
            id, shelter_id, client_event_id, people_count, water_stock,
            urgency, memo, observed_at, reporter_name, reporter_type,
            verification_status, source
        )
        VALUES (
            'OBS-demo-seed-3', 'AIT003', 'demo-event-seed-3', 95, 42,
            'ALERT', '負傷者の搬送支援が必要です', now() - interval '30 minutes', '鈴木',
            'AUTHENTICATED_FIELD', 'UNVERIFIED', 'web'
        )
        ON CONFLICT (client_event_id) DO NOTHING;
        """
    )


def get_demo_data_counts(conn: psycopg.Connection | None = None) -> dict[str, int]:
    if conn is None:
        with get_conn() as managed_conn:
            return get_demo_data_counts(managed_conn)

    return {
        "shelters": conn.execute("SELECT count(*) AS count FROM shelters;").fetchone()["count"],
        "observations": conn.execute("SELECT count(*) AS count FROM observations;").fetchone()["count"],
        "emergency_packets": conn.execute(
            "SELECT count(*) AS count FROM emergency_packets;"
        ).fetchone()["count"],
    }


def reset_demo_dataset() -> dict[str, int]:
    with get_conn() as conn:
        try:
            conn.execute("SELECT pg_advisory_xact_lock(hashtext('tsunagu-demo-reset'));")
            conn.execute("TRUNCATE observations, emergency_packets, shelters CASCADE;")
            _insert_demo_data(conn)
            counts = get_demo_data_counts(conn)
            conn.commit()
            return counts
        except Exception:
            conn.rollback()
            raise
