import argparse
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SOURCE_PATH = REPOSITORY_ROOT / "tools" / "tbeam-emergency-form.html"
TARGET_PATH = (
    REPOSITORY_ROOT
    / "hardware"
    / "TBeamEmergencySender"
    / "portal_html.h"
)
RAW_STRING_DELIMITER = "TSUNAGU_PORTAL"


def build_header(html: str) -> str:
    closing_delimiter = f"){RAW_STRING_DELIMITER}\""
    if closing_delimiter in html:
        raise ValueError("HTML contains the C++ raw-string closing delimiter")

    normalized_html = html.replace("\r\n", "\n").rstrip("\n")
    return (
        "#pragma once\n\n"
        "// Generated from tools/tbeam-emergency-form.html.\n"
        "// Run `python tools/embed_tbeam_portal.py` after editing the source HTML.\n"
        f"const char PORTAL_HTML[] PROGMEM = R\"{RAW_STRING_DELIMITER}(\n"
        f"{normalized_html}\n"
        f"){RAW_STRING_DELIMITER}\";\n"
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Embed the T-Beam emergency form in the Arduino header."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail when portal_html.h is not synchronized with the source HTML.",
    )
    args = parser.parse_args()

    expected = build_header(SOURCE_PATH.read_text(encoding="utf-8"))
    if args.check:
        actual = TARGET_PATH.read_text(encoding="utf-8") if TARGET_PATH.exists() else ""
        if actual != expected:
            print(f"out of date: {TARGET_PATH.relative_to(REPOSITORY_ROOT)}")
            return 1
        print("T-Beam portal header is up to date")
        return 0

    TARGET_PATH.write_text(expected, encoding="utf-8", newline="\n")
    print(f"updated: {TARGET_PATH.relative_to(REPOSITORY_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
