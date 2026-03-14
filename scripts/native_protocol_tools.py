import argparse
from pathlib import Path


def load_sequence(path: Path) -> list[bytes]:
    payloads = []
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip().lower()
        if not line or line.startswith("#"):
            continue
        payloads.append(bytes.fromhex(line))
    return payloads


def recover_first_gif(payloads: list[bytes]) -> bytes | None:
    start_index = None
    offset = None
    for i, payload in enumerate(payloads):
        j = payload.find(b"GIF89a")
        if j != -1:
            start_index = i
            offset = j
            break
    if start_index is None or offset is None:
        return None

    data = bytearray(payloads[start_index][offset:])
    for payload in payloads[start_index + 1 :]:
        data.extend(payload)

    trailer = data.find(b"\x3b")
    if trailer == -1:
        return bytes(data)
    return bytes(data[: trailer + 1])


def cmd_recover_gif(sequence: Path, out: Path) -> None:
    payloads = load_sequence(sequence)
    gif = recover_first_gif(payloads)
    if gif is None:
        raise SystemExit("No GIF89a signature found in sequence")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(gif)
    width = int.from_bytes(gif[6:8], "little") if len(gif) >= 10 else 0
    height = int.from_bytes(gif[8:10], "little") if len(gif) >= 10 else 0
    print(f"Recovered GIF -> {out} ({len(gif)} bytes, {width}x{height})")


def main() -> None:
    parser = argparse.ArgumentParser(description="Native protocol helper tools")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_recover = sub.add_parser("recover-gif", help="Recover first GIF from fa02 sequence")
    p_recover.add_argument("sequence", type=Path)
    p_recover.add_argument("--out", type=Path, default=Path("tmp/recovered.gif"))

    args = parser.parse_args()

    if args.cmd == "recover-gif":
        cmd_recover_gif(args.sequence, args.out)


if __name__ == "__main__":
    main()
