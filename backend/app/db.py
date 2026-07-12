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
                urgency TEXT NOT NULL CHECK (urgency IN ('NORMAL', 'WARNING', 'ALERT', 'CRITICAL')),
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
        conn.execute(
            """
            ALTER TABLE observations ADD COLUMN IF NOT EXISTS reporter_name TEXT NOT NULL DEFAULT '';
            """
        )
        conn.execute(
            """
            ALTER TABLE observations ADD COLUMN IF NOT EXISTS source TEXT NOT NULL DEFAULT 'web' CHECK (source IN ('web', 'emergency_packet', 'offline'));
            """
        )
        conn.execute("ALTER TABLE observations DROP CONSTRAINT IF EXISTS observations_urgency_check;")
        conn.execute(
            """
            UPDATE observations
            SET urgency = 'WARNING'
            WHERE urgency = 'HIGH';
            """
        )
        conn.execute(
            """
            ALTER TABLE observations
            ADD CONSTRAINT observations_urgency_check
            CHECK (urgency IN ('NORMAL', 'WARNING', 'ALERT', 'CRITICAL'));
            """
        )
        # 日本語でのシードデータ登録コメント: デモ用初期シードデータの追加
        # 環境変数 DEMO_SEED が true の場合のみ挿入する
        if os.getenv("DEMO_SEED", "false").lower() == "true":
            # 避難所A (AIT001) に通常報告 (web) のシードデータを追加
            conn.execute(
                """
                INSERT INTO observations (
                    id, shelter_id, client_event_id, people_count, water_stock,
                    urgency, memo, observed_at, reporter_name, source
                )
                VALUES (
                    'OBS-demo-seed-1', 'AIT001', 'demo-event-seed-1', 45, 25,
                    'NORMAL', '【デモデータ】現在、避難所は比較的安定しており、秩序が保たれています。',
                    now() - interval '2 hours', 'デモ報告者A', 'web'
                )
                ON CONFLICT (client_event_id) DO NOTHING;
                """
            )
            # 避難所B (AIT002) にLoRaパケット受信ログ (emergency_packets) を追加
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
            # 避難所B (AIT002) の報告にLoRa受信データを同期
            conn.execute(
                """
                INSERT INTO observations (
                    id, shelter_id, client_event_id, people_count, water_stock,
                    urgency, memo, observed_at, reporter_name, source
                )
                VALUES (
                    'OBS-demo-seed-2', 'AIT002', 'LORA-demo-seed-2', 170, 18,
                    'WARNING', '【デモデータ】[LoRa] Status: WARNING, Req: REQ_WATER',
                    now() - interval '1 hour', 'LoRa Packet', 'emergency_packet'
                )
                ON CONFLICT (client_event_id) DO NOTHING;
                """
            )
        conn.commit()
