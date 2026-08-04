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
        conn.execute(
            """
            INSERT INTO shelters (id, name, location)
            VALUES
                ('AIT001', 'Shelter A', 'University Gymnasium'),
                ('AIT002', 'Shelter B', 'Lecture Hall'),
                ('AIT003', 'Shelter C', 'Student Center')
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
                'NORMAL', 'Demo report', now() - interval '2 hours', 'Demo Reporter',
                'ANONYMOUS', 'UNVERIFIED', 'web'
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
        conn.commit()
