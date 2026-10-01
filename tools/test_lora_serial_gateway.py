from pathlib import Path
from urllib.error import HTTPError, URLError

import lora_serial_gateway as gateway

NORMAL_PACKET = "v1|AIT001|21:02|170|30|NORMAL|NONE"
WARNING_PACKET = "v1|AIT004|21:07|150|15|WARNING|REQ_WATER"
ALERT_PACKET = "v1|AIT003|21:06|120|10|ALERT|REQ_MEDICAL"
CRITICAL_PACKET = "v1|AIT002|21:05|90|5|CRITICAL|REQ_RESCUE"


def test_failed_packet_stays_in_queue(tmp_path, monkeypatch):
    queue = gateway.PacketQueue(tmp_path / "queue.db")
    queue.enqueue("v1|AIT001|21:04|170|18|WARNING|REQ_WATER")

    def fail(*_args):
        raise ConnectionError("offline")

    monkeypatch.setattr(gateway, "post_packet", fail)
    assert gateway.flush_queue(queue, "https://example.invalid", "key") is False
    assert queue.count() == 1


def test_successful_packet_is_removed(tmp_path, monkeypatch):
    queue = gateway.PacketQueue(tmp_path / "queue.db")
    queue.enqueue("v1|AIT001|21:04|170|18|WARNING|REQ_WATER")
    monkeypatch.setattr(gateway, "post_packet", lambda *_args: None)

    assert gateway.flush_queue(queue, "https://example.test", "key") is True
    assert queue.count() == 0



def test_critical_packet_is_sent_before_older_normal_packet(tmp_path, monkeypatch):
    queue = gateway.PacketQueue(tmp_path / "queue.db")
    queue.enqueue(NORMAL_PACKET)
    queue.enqueue(CRITICAL_PACKET)
    sent = []
    monkeypatch.setattr(gateway, "post_packet", lambda _url, _key, packet: sent.append(packet))

    assert gateway.flush_queue(queue, "https://example.test", "key") is True
    assert sent == [CRITICAL_PACKET, NORMAL_PACKET]


def test_http_error_skips_only_that_packet(tmp_path, monkeypatch):
    queue = gateway.PacketQueue(tmp_path / "queue.db")
    queue.enqueue(NORMAL_PACKET)
    queue.enqueue(CRITICAL_PACKET)
    attempts = []

    def reject_first_attempt(url, _key, packet):
        attempts.append(packet)
        if len(attempts) == 1:
            raise HTTPError(url, 400, "Bad Request", hdrs=None, fp=None)

    monkeypatch.setattr(gateway, "post_packet", reject_first_attempt)

    assert gateway.flush_queue(queue, "https://example.test", "key") is False
    assert len(attempts) == 2
    assert [packet for _id, packet in queue.pending()] == [attempts[0]]


def test_connection_error_stops_flush(tmp_path, monkeypatch):
    queue = gateway.PacketQueue(tmp_path / "queue.db")
    queue.enqueue(NORMAL_PACKET)
    queue.enqueue(CRITICAL_PACKET)
    attempts = []

    def offline(_url, _key, packet):
        attempts.append(packet)
        raise URLError("offline")

    monkeypatch.setattr(gateway, "post_packet", offline)

    assert gateway.flush_queue(queue, "https://example.invalid", "key") is False
    assert attempts == [CRITICAL_PACKET]
    assert queue.count() == 2



def test_mixed_statuses_are_sent_in_priority_order(tmp_path, monkeypatch):
    queue = gateway.PacketQueue(tmp_path / "queue.db")
    # 優先度と逆の順に積んで、先着順ではなく緊急度順で送られることを確認する
    for packet in [NORMAL_PACKET, WARNING_PACKET, ALERT_PACKET, CRITICAL_PACKET]:
        queue.enqueue(packet)
    sent = []
    monkeypatch.setattr(gateway, "post_packet", lambda _url, _key, packet: sent.append(packet))

    assert gateway.flush_queue(queue, "https://example.test", "key") is True
    assert sent == [CRITICAL_PACKET, ALERT_PACKET, WARNING_PACKET, NORMAL_PACKET]
    assert queue.count() == 0


def test_rejected_packet_does_not_block_following_packets(tmp_path, monkeypatch):
    queue = gateway.PacketQueue(tmp_path / "queue.db")
    for packet in [NORMAL_PACKET, WARNING_PACKET, ALERT_PACKET, CRITICAL_PACKET]:
        queue.enqueue(packet)
    sent = []

    def reject_alert(url, _key, packet):
        if packet == ALERT_PACKET:
            raise HTTPError(url, 500, "Internal Server Error", hdrs=None, fp=None)
        sent.append(packet)

    monkeypatch.setattr(gateway, "post_packet", reject_alert)

    assert gateway.flush_queue(queue, "https://example.test", "key") is False
    assert sent == [CRITICAL_PACKET, WARNING_PACKET, NORMAL_PACKET]
    assert [packet for _id, packet in queue.pending()] == [ALERT_PACKET]


def test_new_environment_variable_takes_priority(monkeypatch):
    monkeypatch.setenv("TSUNAGU_API_URL", "https://new.example")
    monkeypatch.setenv("SHELTEROS_API_URL", "https://legacy.example")

    assert gateway._environment_value("TSUNAGU_API_URL", "SHELTEROS_API_URL") == "https://new.example"
