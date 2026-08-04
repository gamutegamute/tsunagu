from pathlib import Path

import lora_serial_gateway as gateway


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
