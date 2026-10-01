import argparse
import hashlib
import json
import os
import sqlite3
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class PacketQueue:
    def __init__(self, database_path: Path):
        database_path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(database_path)
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS pending_packets (
                id TEXT PRIMARY KEY,
                packet TEXT NOT NULL,
                queued_at REAL NOT NULL
            )
            """
        )
        self.connection.commit()

    def enqueue(self, packet: str) -> None:
        packet_id = hashlib.sha256(packet.encode("utf-8")).hexdigest()
        self.connection.execute(
            "INSERT OR IGNORE INTO pending_packets (id, packet, queued_at) VALUES (?, ?, ?)",
            (packet_id, packet, time.time()),
        )
        self.connection.commit()

    def pending(self) -> list[tuple[str, str]]:
        return list(self.connection.execute("""
            SELECT id, packet FROM pending_packets
            ORDER BY CASE
              WHEN packet LIKE '%|CRITICAL|%' THEN 0
              WHEN packet LIKE '%|ALERT|%'    THEN 1
              WHEN packet LIKE '%|WARNING|%'  THEN 2
              ELSE 3 END, queued_at, id
        """))

    def remove(self, packet_id: str) -> None:
        self.connection.execute("DELETE FROM pending_packets WHERE id = ?", (packet_id,))
        self.connection.commit()

    def count(self) -> int:
        return self.connection.execute("SELECT count(*) FROM pending_packets").fetchone()[0]


def post_packet(api_url: str, api_key: str, packet: str) -> None:
    body = json.dumps({"packet": packet}).encode("utf-8")
    request = Request(
        api_url,
        data=body,
        headers={"Content-Type": "application/json", "X-Gateway-Key": api_key},
        method="POST",
    )
    with urlopen(request, timeout=5) as response:
        response.read()


def flush_queue(queue: PacketQueue, api_url: str, api_key: str) -> bool:
    all_sent = True
    for packet_id, packet in queue.pending():
        try:
            post_packet(api_url, api_key, packet)
            queue.remove(packet_id)
            print(f"posted: {packet}", flush=True)
        except HTTPError as exc:
            # 本部は応答した = このパケットだけの失敗。後ろのパケットは送りにいく
            # (HTTPErrorはURLErrorのサブクラスなので、先に捕まえる)
            all_sent = False
            print(f"rejected: {packet} ({exc})", flush=True)
            continue
        except (URLError, TimeoutError, ConnectionError) as exc:
            # 本部のネット自体に届かない。後ろも同じく失敗するので止める
            all_sent = False
            print(f"queued: {packet} ({exc})", flush=True)
            break
    return all_sent


def accept_packet(queue: PacketQueue, api_url: str, api_key: str, packet: str) -> None:
    queue.enqueue(packet)
    flush_queue(queue, api_url, api_key)


def run_stdin(queue: PacketQueue, api_url: str, api_key: str) -> None:
    flush_queue(queue, api_url, api_key)
    for line in sys.stdin:
        packet = line.strip()
        if packet:
            accept_packet(queue, api_url, api_key, packet)


def run_serial(queue: PacketQueue, api_url: str, api_key: str, port: str, baud: int) -> None:
    try:
        import serial
    except ImportError as exc:
        raise SystemExit("pyserial is required. Install it with: python -m pip install pyserial") from exc

    while True:
        try:
            print(f"connecting: {port} ({baud} baud)", flush=True)
            with serial.Serial(port, baud, timeout=1) as serial_port:
                print(f"connected: {port}", flush=True)
                flush_queue(queue, api_url, api_key)
                last_retry = time.monotonic()
                while True:
                    line = serial_port.readline().decode("utf-8", errors="ignore").strip()
                    if line:
                        accept_packet(queue, api_url, api_key, line)
                    elif queue.count() and time.monotonic() - last_retry >= 5:
                        flush_queue(queue, api_url, api_key)
                        last_retry = time.monotonic()
        except serial.SerialException as exc:
            print(f"serial disconnected: {exc}; retrying in 3 seconds", flush=True)
            time.sleep(3)


def _environment_value(new_name: str, legacy_name: str, default: str = "") -> str:
    return os.getenv(new_name) or os.getenv(legacy_name) or default


def _default_queue_path() -> Path:
    configured = _environment_value("TSUNAGU_QUEUE_DB", "SHELTEROS_QUEUE_DB")
    if configured:
        return Path(configured)
    legacy_path = Path(".shelteros/lora_gateway_queue.db")
    new_path = Path(".tsunagu/lora_gateway_queue.db")
    return legacy_path if legacy_path.exists() and not new_path.exists() else new_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Forward T-Beam Emergency Packets to TSUNAGU.")
    parser.add_argument(
        "--api-url",
        default=_environment_value(
            "TSUNAGU_API_URL",
            "SHELTEROS_API_URL",
            "http://localhost:8000/api/emergency-packets",
        ),
    )
    parser.add_argument("--port", help="Windows COM port such as COM3. If omitted, read from stdin.")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument(
        "--queue-db",
        type=Path,
        default=_default_queue_path(),
    )
    args = parser.parse_args()

    api_key = _environment_value("TSUNAGU_GATEWAY_API_KEY", "SHELTEROS_GATEWAY_API_KEY")
    if not api_key:
        raise SystemExit("TSUNAGU_GATEWAY_API_KEY is required")

    queue = PacketQueue(args.queue_db)
    if args.port:
        run_serial(queue, args.api_url, api_key, args.port, args.baud)
    else:
        run_stdin(queue, args.api_url, api_key)


if __name__ == "__main__":
    main()
