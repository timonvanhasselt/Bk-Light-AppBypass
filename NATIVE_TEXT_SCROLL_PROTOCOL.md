# Native Text Scroll Protocol (ACT1025)

Date: 2026-03-15

## Current production rule

After end-to-end hardware validation, the stable routing rule is:

- **Default auto route: `A1` for all text lengths** (`>= 1` char)
- `0x45` and `0xF9` are kept as manual/debug transports only (`--transport 45|f9|a1`)

Reason: `A1` is the only route that validated consistently across short, medium, and long strings in our latest tests.

## Handshake / open sequence

Before text payload, send:

1. `08 00 01 80 HH MM SS 00`
2. `04 00 05 80`
3. `05 00 12 80 07`
4. `07 00 08 80 01 00 CH`

Then send text payload frame(s).

## A1 frame (type-4 channel payload)

Observed accepted framing (from app captures and validated sender):

- Bytes `0..1`: framed packet length (LE)
- Bytes `2..3`: data type `00 01`
- Byte `4`: type `00`
- Bytes `5..8`: `totalData` length (LE)
- Bytes `9..12`: `CRC32(totalData)` (LE)
- Bytes `13..14`: route marker/trailer `00 65`
- Bytes `15..`: `totalData`

Long payloads are segmented into multiple BLE writes (chunked value writes).

## `totalData` text record layout

- Byte `0`: text length (1-byte)
- Byte `1`: `00`
- Bytes `2..3`: `01 01`
- Byte `4`: effect code
- Bytes `5..6`: `50 00`
- Bytes `7..20`: color prelude
  - `fg(3) + bg(3) + 00 00 + fg(3) + bg(3)`
- Bytes `21..`: glyph records
  - first glyph + separator
  - then repeated `fg + bg + glyph + separator`

Effect codes:
- `0=fixed`
- `1=scroll-left`
- `2=scroll-right`
- `5=blinking`
- `6=breathing`
- `7=snowflake`
- `8=laser`

## Validation status

Visually validated on panel:
- short text (`1`, `2`, `3`, `5`, `8`, `10` chars)
- medium text (`11` chars)
- long text (`>11`, including repeated "Hello World" long string)
- effects and color

## Notes

- Success criterion is always visual panel rendering (not BLE write/ack alone).
- Glyph rendering uses the repo native font mapping (`scripts/ipixel_font_map.py`).
