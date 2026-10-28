import importlib.util
from pathlib import Path
from uuid import uuid4

from app.db import get_conn


def test_packet_clock_migration_preserves_and_restores_original_values(monkeypatch):
    path = Path(__file__).resolve().parents[1] / "alembic/versions/0006_packet_clock_correction.py"
    spec = importlib.util.spec_from_file_location("clock_correction", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    observation_id, packet_id = f"OBS-{uuid4().hex}", f"EP-{uuid4().hex}"
    with get_conn() as conn:
        # All DDL and test data stay in one transaction and are rolled back.
        monkeypatch.setattr(migration.op, "execute", conn.execute)
        migration.downgrade()
        conn.execute("""INSERT INTO observations
            (id,shelter_id,client_event_id,people_count,water_stock,urgency,memo,observed_at,reporter_name,reporter_type,verification_status,source)
            VALUES (%s,'AIT001',%s,1,100,'NORMAL','','2099-01-01T00:00:00Z','LoRa','LORA_GATEWAY','UNVERIFIED','emergency_packet');""", (observation_id, observation_id))
        conn.execute("""INSERT INTO emergency_packets
            (id,version,shelter_code,shelter_id,packet_time,people_count,water_stock,status,request_code,raw_packet,observation_id)
            VALUES (%s,'v1','AIT001','AIT001','00:00',1,100,'NORMAL','NONE','migration-test',%s);""", (packet_id, observation_id))
        original = conn.execute("SELECT observed_at FROM observations WHERE id=%s", (observation_id,)).fetchone()["observed_at"]
        migration.upgrade()
        row = conn.execute("SELECT observed_at,created_at FROM observations WHERE id=%s", (observation_id,)).fetchone()
        assert row["observed_at"] == row["created_at"]
        snapshot = conn.execute("SELECT * FROM packet_clock_corrections WHERE observation_id=%s", (observation_id,)).fetchone()
        assert snapshot["original_observed_at"] == original
        migration.downgrade()
        assert conn.execute("SELECT observed_at FROM observations WHERE id=%s", (observation_id,)).fetchone()["observed_at"] == original
        assert conn.execute("SELECT time_trust FROM emergency_packets WHERE id=%s", (packet_id,)).fetchone()["time_trust"] is None
        migration.upgrade()
        conn.rollback()
