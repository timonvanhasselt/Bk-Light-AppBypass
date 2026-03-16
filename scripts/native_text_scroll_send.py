#!/usr/bin/env python3
"""Native text sender for the ACT1025 panel.

Uses the validated A1/type-4 native transport path.
"""

import argparse
import asyncio
import sys
import zlib
from datetime import datetime
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))
from scripts.ipixel_font_map import glyph_8x10_ipixel, validate_known_glyphs


BASE_PAYLOAD = bytes.fromhex(
    "45000001003600000000000000000202000101015000ffffff0000000000ffffff000000"
    "0000000000000000000000000000ffffff00000000000000000000000000000000"
)
A1_ROUTE_MARKER = 0x65
A1_CHUNK_SIZE = 509
A1_HEADER_BYTES = 15


def parse_hex_color(value: str) -> tuple[int, int, int]:
    cleaned = value.strip().replace("#", "")
    if len(cleaned) != 6:
        raise ValueError(f"invalid color '{value}', expected #RRGGBB")
    return (int(cleaned[0:2], 16), int(cleaned[2:4], 16), int(cleaned[4:6], 16))


def glyph_8x10_pil(ch: str, font_path: Path | None = None, size: int = 10, xoff: int = 0, yoff: int = -1) -> bytes:
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ModuleNotFoundError as exc:
        raise RuntimeError("Pillow is required for non-ipixel font profiles") from exc

    img = Image.new("1", (8, 10), 0)
    draw = ImageDraw.Draw(img)
    if font_path and font_path.exists():
        font = ImageFont.truetype(str(font_path), size)
    else:
        font = ImageFont.load_default()
    draw.text((xoff, yoff), (ch or " ")[:1], 1, font=font)
    rows = bytearray()
    for y in range(10):
        row = 0
        for x in range(8):
            if img.getpixel((x, y)):
                row |= 1 << (7 - x)
        rows.append(row)
    return bytes(rows)


def reverse_bits_byte(value: int) -> int:
    value &= 0xFF
    out = 0
    for _ in range(8):
        out = (out << 1) | (value & 1)
        value >>= 1
    return out


def glyph_for_profile(ch: str, profile: str) -> bytes:
    profile = profile.lower()
    if profile == "ipixel":
        try:
            raw = glyph_8x10_ipixel(ch)
        except KeyError:
            raw = glyph_8x10_pil(ch, font_path=None, size=10, xoff=0, yoff=-1)
    elif profile == "pixeloid":
        fp = Path("/home/agent/.openclaw/workspace/tmp/ipixel_apktool/assets/fonts/PixeloidSans.ttf")
        raw = glyph_8x10_pil(ch, font_path=fp, size=10, xoff=0, yoff=-1)
    elif profile == "square-bold":
        raw = glyph_8x10_pil(ch, font_path=None, size=10, xoff=0, yoff=-1)
    else:
        raise ValueError(f"unknown font profile: {profile}")

    # Panel-native text packets expect mirrored bit order vs our logical glyph rows.
    return bytes(reverse_bits_byte(b) for b in raw)


EFFECT_CODES = {
    "fixed": 0,
    "scroll-left": 1,
    "scroll-right": 2,
    "blinking": 5,
    "breathing": 6,
    "snowflake": 7,
    "laser": 8,
}

REVERSE_FOR_EFFECT = set()

TRANSPORT_A1 = "a1"


def build_content_payload(
    text2: str,
    channel: int,
    fg_color: tuple[int, int, int] = (255, 255, 255),
    bg_color: tuple[int, int, int] = (0, 0, 0),
    font_profile: str = "ipixel",
    effect_code: int = 1,
) -> bytes:
    text2 = (text2 or "  ")[:2].ljust(2)
    p = bytearray(BASE_PAYLOAD)

    # Header / mode bytes
    p[14] = channel & 0xFF
    p[19] = effect_code & 0xFF

    # Native color fields
    p[22:25] = bytes(fg_color)
    p[25:28] = bytes(bg_color)
    p[30:33] = bytes(fg_color)
    p[33:36] = bytes(bg_color)
    p[50:53] = bytes(fg_color)
    p[53:56] = bytes(bg_color)

    # Two 8x10 glyph slots
    p[36:46] = glyph_for_profile(text2[0], font_profile)
    p[56:66] = glyph_for_profile(text2[1], font_profile)

    # CRC32 over payload[15:] (little-endian at bytes 9..12)
    crc = zlib.crc32(bytes(p[15:])) & 0xFFFFFFFF
    p[9:13] = crc.to_bytes(4, "little")
    return bytes(p)


def build_text_record_body_length(glyph_count: int) -> int:
    if glyph_count <= 0:
        glyph_count = 1
    return 20 * glyph_count + 14


def build_text_record_body(
    text: str,
    fg_color: tuple[int, int, int] = (255, 255, 255),
    bg_color: tuple[int, int, int] = (0, 0, 0),
    font_profile: str = "ipixel",
    effect_code: int = 1,
) -> bytes:
    text = text or " "

    body = bytearray()
    body.extend(
        (
            len(text) & 0xFF,
            0x00,
            0x01,
            0x01,
            effect_code & 0xFF,
            0x50,
            0x00,
        )
    )
    body.extend(fg_color)
    body.extend(bg_color)
    body.extend((0x00, 0x00))
    body.extend(fg_color)
    body.extend(bg_color)

    glyphs = [glyph_for_profile(ch, font_profile) for ch in text]
    body.extend(glyphs[0])
    body.extend(b"\x00" * (4 if len(glyphs) > 1 else 3))

    for idx, glyph in enumerate(glyphs[1:], start=1):
        body.extend(fg_color)
        body.extend(bg_color)
        body.extend(glyph)
        body.extend(b"\x00" * (4 if idx < len(glyphs) - 1 else 3))
    return bytes(body)


def build_a1_total_data(
    text: str,
    fg_color: tuple[int, int, int] = (255, 255, 255),
    bg_color: tuple[int, int, int] = (0, 0, 0),
    font_profile: str = "ipixel",
    effect_code: int = 1,
) -> bytes:
    text = text or " "
    if len(text) > 0xFF:
        raise ValueError(f"native `{TRANSPORT_A1}` path currently supports up to 255 glyphs; got {len(text)}")
    return build_text_record_body(
        text,
        fg_color=fg_color,
        bg_color=bg_color,
        font_profile=font_profile,
        effect_code=effect_code,
    )


def build_a1_payload(
    text: str,
    fg_color: tuple[int, int, int] = (255, 255, 255),
    bg_color: tuple[int, int, int] = (0, 0, 0),
    font_profile: str = "ipixel",
    effect_code: int = 1,
    route_marker: int = A1_ROUTE_MARKER,
) -> bytes:
    total_data = build_a1_total_data(
        text,
        fg_color=fg_color,
        bg_color=bg_color,
        font_profile=font_profile,
        effect_code=effect_code,
    )
    packet = bytearray()
    packet.extend((len(total_data) + 15).to_bytes(2, "little"))
    packet.extend(b"\x00\x01")
    packet.append(0x00)
    packet.extend(len(total_data).to_bytes(4, "little"))
    packet.extend((zlib.crc32(total_data) & 0xFFFFFFFF).to_bytes(4, "little"))
    packet.extend((0x00, route_marker & 0xFF))
    packet.extend(total_data)
    return bytes(packet)


def chunk_payload(payload: bytes, chunk_size: int = A1_CHUNK_SIZE) -> list[bytes]:
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    return [payload[idx:idx + chunk_size] for idx in range(0, len(payload), chunk_size)]


def packet_debug_info(payload: bytes, text: str, chunk_size: int = A1_CHUNK_SIZE) -> dict[str, int | str]:
    body_len = int.from_bytes(payload[5:9], "little")
    crc = int.from_bytes(payload[9:13], "little")
    return {
        "route": TRANSPORT_A1,
        "chars": len(text or ""),
        "body_len": body_len,
        "packet_len": len(payload),
        "chunk_count": len(chunk_payload(payload, chunk_size)),
        "crc": crc,
    }


def build_handshake() -> bytes:
    now = datetime.now()
    return bytes((0x08, 0x00, 0x01, 0x80, now.hour & 0xFF, now.minute & 0xFF, now.second & 0xFF, 0x00))


async def run(
    address: str,
    text: str,
    channel: int,
    interval: float,
    verbose: bool,
    fg_color: tuple[int, int, int],
    bg_color: tuple[int, int, int],
    font_profile: str,
    effect: str,
    a1_chunk_size: int,
):
    from bk_light.display_session import BleDisplaySession, UUID_WRITE

    effect_code = EFFECT_CODES[effect]

    async with BleDisplaySession(address=address, log_notifications=verbose) as s:
        base_seq = [
            build_handshake(),
            bytes.fromhex("04000580"),
            bytes.fromhex("0500128007"),
            bytes.fromhex(f"070008800100{channel:02x}"),
        ]
        for i, pkt in enumerate(base_seq, 1):
            await s.client.write_gatt_char(UUID_WRITE, pkt, response=False)
            await asyncio.sleep(interval)
            if verbose:
                print("sent", i)

        payload = build_a1_payload(
            text,
            fg_color=fg_color,
            bg_color=bg_color,
            font_profile=font_profile,
            effect_code=effect_code,
        )
        chunks = chunk_payload(payload, a1_chunk_size)
        debug = packet_debug_info(payload, text, a1_chunk_size)
        if verbose:
            print(
                f"route={debug['route']} chars={debug['chars']} body_len={debug['body_len']} "
                f"packet_len={debug['packet_len']} chunks={debug['chunk_count']} "
                f"crc=0x{debug['crc']:08x} route_marker=0x{payload[14]:02x} "
                f"chunk_sizes={[len(chunk) for chunk in chunks]}"
            )
        for idx, chunk in enumerate(chunks, 1):
            if verbose:
                print(f"chunk {idx}/{len(chunks)} bytes={len(chunk)}")
                if idx == 1:
                    print("payload5", chunk.hex())
            await s.client.write_gatt_char(UUID_WRITE, chunk, response=False)
            await asyncio.sleep(interval)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Send native ACT1025 text payloads using the A1/type-4 transport")
    ap.add_argument("text", help="Text to display")
    ap.add_argument("--address", default="31:C3:BD:32:14:7A")
    ap.add_argument("--channel", type=int, default=3)
    ap.add_argument("--interval", type=float, default=0.06)
    ap.add_argument("--color", default="#ffffff", help="Foreground color (#RRGGBB)")
    ap.add_argument("--background", default="#000000", help="Background color (#RRGGBB)")
    ap.add_argument("--font-profile", default="ipixel", choices=("ipixel", "pixeloid", "square-bold"))
    ap.add_argument(
        "--effect",
        default="scroll-left",
        choices=("fixed", "scroll-left", "scroll-right", "blinking", "breathing", "snowflake", "laser"),
        help="Native text effect mapped from iPixel captures",
    )
    ap.add_argument(
        "--a1-chunk-size",
        type=int,
        default=A1_CHUNK_SIZE,
        help=f"Continuation write size for `{TRANSPORT_A1}` payloads",
    )
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument(
        "--validate-font",
        action="store_true",
        help="Validate reference native glyphs and exit",
    )
    args = ap.parse_args()

    if args.validate_font:
        results = validate_known_glyphs()
        for ch, ok in sorted(results.items()):
            print(f"{ch}: {'ok' if ok else 'mismatch'}")
        raise SystemExit(0 if all(results.values()) else 1)

    fg = parse_hex_color(args.color)
    bg = parse_hex_color(args.background)
    asyncio.run(
        run(
            args.address,
            args.text,
            args.channel,
            args.interval,
            args.verbose,
            fg,
            bg,
            args.font_profile,
            args.effect,
            args.a1_chunk_size,
        )
    )
