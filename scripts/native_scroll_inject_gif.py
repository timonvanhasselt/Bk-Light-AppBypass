import argparse
from pathlib import Path


def load_hex_lines(path: Path) -> list[bytes]:
    out = []
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip().lower()
        if not line or line.startswith("#"):
            continue
        out.append(bytes.fromhex(line))
    return out


def inject_gif(seq: list[bytes], gif_bytes: bytes) -> list[bytes]:
    # Flatten payload area and replace from first GIF89a up to trailer 0x3b
    flat = bytearray().join(seq)
    start = flat.find(b"GIF89a")
    if start < 0:
        raise ValueError("GIF89a not found in sequence")
    end = flat.find(b"\x3b", start)
    if end < 0:
        raise ValueError("GIF trailer not found in sequence")
    old_len = end - start + 1

    replacement = gif_bytes
    if len(replacement) < old_len:
        replacement = replacement + b"\x00" * (old_len - len(replacement))
    else:
        replacement = replacement[:old_len]
        replacement = replacement[:-1] + b"\x3b"

    patched = bytearray(flat)
    patched[start : start + old_len] = replacement

    # Re-split into original packet lengths
    out = []
    off = 0
    for chunk in seq:
        n = len(chunk)
        out.append(bytes(patched[off : off + n]))
        off += n
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Inject GIF bytes into a captured native animation sequence")
    parser.add_argument("sequence", type=Path)
    parser.add_argument("gif", type=Path)
    parser.add_argument("--out", type=Path, default=Path("tmp/injected_sequence.txt"))
    args = parser.parse_args()

    seq = load_hex_lines(args.sequence)
    gif = args.gif.read_bytes()
    patched = inject_gif(seq, gif)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(c.hex() for c in patched) + "\n", encoding="utf-8")
    print(f"Wrote patched sequence: {args.out} ({len(patched)} chunks)")


if __name__ == "__main__":
    main()
