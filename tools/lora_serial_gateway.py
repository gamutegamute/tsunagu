import argparse
import json
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def post_packet(api_url: str, packet: str) -> None:
    body = json.dumps({"packet": packet}).encode("utf-8")
    request = Request(
        api_url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=5) as response:
        response.read()


def run_stdin(api_url: str) -> None:
    for line in sys.stdin:
        packet = line.strip()
        if packet:
            post_packet(api_url, packet)
            print(f"posted: {packet}", flush=True)


def run_serial(api_url: str, port: str, baud: int) -> None:
    try:
        import serial
    except ImportError as exc:
        raise SystemExit("pyserial is required for --port mode. Install it with: pip install pyserial") from exc

    with serial.Serial(port, baud, timeout=1) as serial_port:
        while True:
            line = serial_port.readline().decode("utf-8", errors="ignore").strip()
            if not line:
                continue
            try:
                post_packet(api_url, line)
                print(f"posted: {line}", flush=True)
            except (HTTPError, URLError, TimeoutError) as exc:
                print(f"failed: {line} ({exc})", flush=True)
                time.sleep(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Forward T-Beam serial Emergency Packets to ShelterOS.")
    parser.add_argument("--api-url", default="http://localhost:8000/api/emergency-packets")
    parser.add_argument("--port", help="Windows COM port such as COM3. If omitted, read packets from stdin.")
    parser.add_argument("--baud", type=int, default=115200)
    args = parser.parse_args()

    if args.port:
        run_serial(args.api_url, args.port, args.baud)
    else:
        run_stdin(args.api_url)


if __name__ == "__main__":
    main()
