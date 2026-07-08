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


def init_db() -> None:
    with get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS shelters (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                location TEXT NOT NULL DEFAULT '',
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS observations (
                id TEXT PRIMARY KEY,
                shelter_id TEXT NOT NULL REFERENCES shelters(id) ON DELETE CASCADE,
                client_event_id TEXT NOT NULL UNIQUE,
                people_count INTEGER NOT NULL CHECK (people_count >= 0),
                water_stock INTEGER NOT NULL CHECK (water_stock >= 0),
                urgency TEXT NOT NULL CHECK (urgency IN ('NORMAL', 'HIGH', 'CRITICAL')),
                memo TEXT NOT NULL DEFAULT '',
                observed_at TIMESTAMPTZ NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );
            """
        )
        conn.execute(
            """
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
                    request_code IN (
                        'REQ_WATER',
                        'REQ_MEDICAL',
                        'REQ_FOOD',
                        'REQ_RESCUE',
                        'REQ_CONFIRM',
                        'NONE'
                    )
                ),
                raw_packet TEXT NOT NULL,
                received_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );
            """
        )
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
        conn.commit()
