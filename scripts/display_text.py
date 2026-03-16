import argparse
import asyncio
import sys
from dataclasses import replace
from pathlib import Path
from typing import Optional
from PIL import Image

project_root = Path(__file__).resolve().parents[1]
if str(project_root) not in sys.path:
    sys.path.append(str(project_root))

from bk_light.config import AppConfig, load_config, text_options
from bk_light.fonts import get_font_profile, resolve_font
from bk_light.panel_manager import PanelManager
from bk_light.text import build_text_bitmap
from bk_light.display_session import BleDisplaySession, UUID_WRITE
from scripts.native_text_scroll_send import (
    EFFECT_CODES,
    TRANSPORT_A1,
    packet_debug_info,
    build_a1_payload,
    build_handshake,
    chunk_payload,
)


def parse_color(value: Optional[str]) -> Optional[tuple[int, int, int]]:
    if value is None:
        return None
    cleaned = value.replace("#", "").replace(" ", "")
    if "," in cleaned:
        parts = cleaned.split(",")
        return tuple(int(part) for part in parts[:3])
    if len(cleaned) == 6:
        return tuple(int(cleaned[i:i + 2], 16) for i in (0, 2, 4))
    raise ValueError("Invalid color")


def render_static_frame(
    canvas: tuple[int, int],
    text_bitmap: Image.Image,
    background: tuple[int, int, int],
    offset_x: int,
    offset_y: int,
) -> Image.Image:
    frame = Image.new("RGBA", canvas, tuple(background) + (255,))
    x = (canvas[0] - text_bitmap.width) // 2 + offset_x
    y = (canvas[1] - text_bitmap.height) // 2 + offset_y
    frame.paste(text_bitmap, (x, y), text_bitmap)
    return frame.convert("RGB")


def render_scroll_frame(
    canvas: tuple[int, int],
    text_bitmap: Image.Image,
    background: tuple[int, int, int],
    direction: str,
    gap: int,
    offset_x: int,
    offset_y: int,
    position: int,
) -> Image.Image:
    strip_width = max(1, text_bitmap.width + gap)
    strip = Image.new("RGBA", (strip_width, canvas[1]), tuple(background) + (255,))
    y = (canvas[1] - text_bitmap.height) // 2 + offset_y
    strip.paste(text_bitmap, (0, y), text_bitmap)
    shift = position % strip_width
    start = offset_x - shift if direction == "left" else offset_x + shift
    while start > -strip_width:
        start -= strip_width
    frame = Image.new("RGBA", canvas, tuple(background) + (255,))
    x = start
    while x < canvas[0]:
        frame.paste(strip, (int(x), 0), strip)
        x += strip_width
    return frame.convert("RGB")


async def send_native_scroll(
    config: AppConfig,
    message: str,
    channel: int = 3,
    interval: float = 0.06,
    fg_color: tuple[int, int, int] = (255, 255, 255),
    bg_color: tuple[int, int, int] = (0, 0, 0),
    font_profile: str = "ipixel",
    effect: str = "scroll-left",
) -> None:
    effect_code = EFFECT_CODES.get(effect, EFFECT_CODES["scroll-left"])
    mode = TRANSPORT_A1
    async with BleDisplaySession(address=config.device.address, log_notifications=False) as session:
        for pkt in (
            build_handshake(),
            bytes.fromhex("04000580"),
            bytes.fromhex("0500128007"),
            bytes.fromhex(f"070008800100{channel:02x}"),
        ):
            await session.client.write_gatt_char(UUID_WRITE, pkt, response=False)
            await asyncio.sleep(interval)

        payload = build_a1_payload(
            message,
            fg_color=fg_color,
            bg_color=bg_color,
            font_profile=font_profile,
            effect_code=effect_code,
        )
        debug = packet_debug_info(payload, message)
        print(
            f"native-text route={debug['route']} chars={debug['chars']} body_len={debug['body_len']} "
            f"packet_len={debug['packet_len']} chunks={debug['chunk_count']} "
            f"crc=0x{debug['crc']:08x}"
        )
        for chunk in chunk_payload(payload):
            await session.client.write_gatt_char(UUID_WRITE, chunk, response=False)
            await asyncio.sleep(interval)


async def display_text(config: AppConfig, message: str, preset_name: str, overrides: dict[str, Optional[str]]) -> None:
    preset = text_options(config, preset_name, overrides)
    color = parse_color(overrides.get("color")) or parse_color(preset.color)
    background = parse_color(overrides.get("background")) or parse_color(preset.background)
    font_ref = overrides.get("font") or preset.font
    font_path = resolve_font(font_ref)
    profile = get_font_profile(font_ref, font_path)
    if overrides.get("size") is not None:
        size = int(overrides["size"])
    elif profile.recommended_size is not None:
        size = int(profile.recommended_size)
    else:
        size = preset.size
    size = max(1, int(round(size)))
    spacing_override = overrides.get("spacing")
    spacing = int(spacing_override) if spacing_override is not None else preset.spacing
    text_bitmap = build_text_bitmap(
        message,
        font_path,
        size,
        spacing,
        color,
        config.display.antialias_text,
        monospace_digits=True,
    )
    offset_x_base = preset.offset_x + profile.offset_x
    offset_y_base = preset.offset_y + profile.offset_y
    try:
        if preset.mode == "scroll":
            # Native panel-side scroll path with automatic transport selection.
            # Keep transport logic unchanged; only source glyphs from the shared font resolver.
            effect = overrides.get("effect") or "scroll-left"
            native_font_profile = str(font_path) if font_path else (str(font_ref) if font_ref else "ipixel")
            await send_native_scroll(
                config,
                message,
                channel=3,
                interval=0.06,
                fg_color=color,
                bg_color=background,
                font_profile=native_font_profile,
                effect=effect,
            )
            await asyncio.sleep(0.2)
        else:
            async with PanelManager(config) as manager:
                canvas = manager.canvas_size
                frame = render_static_frame(
                    canvas,
                    text_bitmap,
                    background,
                    offset_x_base,
                    offset_y_base,
                )
                await manager.send_image(frame, delay=0.15)
                await asyncio.sleep(0.2)
    except asyncio.CancelledError:
        raise
    except Exception as error:
        print("ERROR", str(error))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("text")
    parser.add_argument("--config", type=Path)
    parser.add_argument("--address")
    parser.add_argument("--preset")
    parser.add_argument("--color")
    parser.add_argument("--background")
    parser.add_argument("--font", type=Path)
    parser.add_argument("--size", type=int)
    parser.add_argument("--spacing", type=int)
    parser.add_argument("--mode", choices=("static", "scroll"))
    parser.add_argument("--direction", choices=("left", "right"))
    parser.add_argument(
        "--effect",
        choices=("fixed", "scroll-left", "scroll-right", "blinking", "breathing", "snowflake", "laser"),
    )
    parser.add_argument("--speed", type=float)
    parser.add_argument("--gap", type=int)
    parser.add_argument("--step", type=int)
    parser.add_argument("--offset-x", type=int)
    parser.add_argument("--offset-y", type=int)
    parser.add_argument("--interval", type=float)
    return parser.parse_args()


def build_override_map(args: argparse.Namespace) -> dict[str, Optional[str]]:
    return {
        "color": args.color,
        "background": args.background,
        "font": str(args.font) if args.font else None,
        "size": args.size,
        "spacing": args.spacing,
        "mode": args.mode,
        "direction": args.direction,
        "effect": args.effect,
        "speed": args.speed,
        "gap": args.gap,
        "step": args.step,
        "offset_x": args.offset_x,
        "offset_y": args.offset_y,
        "interval": args.interval,
    }


if __name__ == "__main__":
    args = parse_args()
    config = load_config(args.config)
    if args.address:
        config.device = replace(config.device, address=args.address)
    preset_name = args.preset or config.runtime.preset or "default"
    overrides = build_override_map(args)
    try:
        asyncio.run(display_text(config, args.text, preset_name, overrides))
    except KeyboardInterrupt:
        pass
