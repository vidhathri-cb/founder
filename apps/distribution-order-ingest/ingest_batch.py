"""
Batch entrypoint for distribution-order-ingest.

Built for the interim period before the WhatsApp Business API webhook is
connected (v1.1): messages are being collected separately (however they're
being gathered day to day) instead of arriving one at a time from a live
webhook, so this takes one *or several* WhatsApp-format messages in a
single input -- separated by a line containing only "---" -- and ingests
each independently.

One bad message does NOT block the others: every message in the batch is
attempted, and a summary of successes/failures prints at the end. The
process exits non-zero if anything failed, so a batch run still shows red
in the Actions tab when something needs a manual look, without silently
dropping the rest of that day's entries.

Usage (same calling convention as main.py):
    python ingest_batch.py messages.txt
    cat messages.txt | python ingest_batch.py
"""
import sys

from main import ingest_message
from parser import MessageParseError


def split_messages(raw: str) -> list[str]:
    blocks: list[str] = []
    current: list[str] = []
    for line in raw.splitlines():
        if line.strip() == "---":
            if current:
                blocks.append("\n".join(current))
                current = []
        else:
            current.append(line)
    if current:
        blocks.append("\n".join(current))
    # Drop anything that's just blank lines (stray leading/trailing "---").
    return [b for b in blocks if b.strip()]


def _label_for(message: str, index: int) -> str:
    for line in message.splitlines():
        if line.strip().lower().startswith("shop name"):
            return line.strip()
    return f"message {index}"


def main() -> None:
    if len(sys.argv) > 1:
        with open(sys.argv[1]) as f:
            raw = f.read()
    else:
        raw = sys.stdin.read()

    messages = split_messages(raw)
    if not messages:
        print("No messages found (nothing to ingest).")
        raise SystemExit(1)

    print(f"Found {len(messages)} message(s) to ingest.\n")

    failures = []
    for i, msg in enumerate(messages, start=1):
        label = _label_for(msg, i)
        print(f"--- [{i}/{len(messages)}] {label} ---")
        try:
            result = ingest_message(msg)
            print(f"OK: {result}")
        except MessageParseError as e:
            print(f"FLAGGED / ESCROWED, not written: {e}")
            failures.append((i, label, str(e)))
        except Exception as e:  # noqa: BLE001 -- surface anything unexpected per-message, don't crash the batch
            print(f"UNEXPECTED ERROR: {e}")
            failures.append((i, label, str(e)))
        print()

    print("=== Summary ===")
    print(f"{len(messages) - len(failures)}/{len(messages)} ingested successfully.")
    if failures:
        print("Failed / flagged:")
        for i, label, err in failures:
            print(f"  [{i}] {label}: {err}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
