# Native Text Scroll Protocol (working path)

Date: 2026-03-15

## Summary

For the ACT1025 panel, **text scroll mode from iPixel** follows a short 5-packet flow that is different from GIF multi-chunk upload.

This path was extracted from `tmp/btsnoop_hci.log` (around ~13:58 test) and replayed successfully with visible `AA` scrolling on panel.

There is also a larger native text payload family starting with `0xF9 00 00 01`, captured around `2026-03-15 16:11` in `tmp/btsnoop_hci.log`. That path carries an entire short string in one ATT write instead of the 2-glyph `0x45` window.

For longer text, `tmp/btmon_from_btsnoop.txt` shows a still larger type-4 channel payload whose first bytes are `a1 08 00 01 ...`. The important detail is that `a1 08` is not a fixed opcode; it is the little-endian packet length (`0x08a1`) for that specific capture.

The generalized rule is now:

- `<= 2` chars: use the native `0x45` two-glyph packet
- `3..11` chars: use one `0xF9` packet
- `>= 12` chars: use the same text body as `0xF9`, wrapped in the type-4/A1 channel envelope and segmented into `509`-byte ATT values

The `11`-glyph cutoff is structural, not arbitrary:

- `0xF9` total packet length is `20 * glyph_count + 29`
- At ATT write-command value size `249`, the largest single-packet `0xF9` text is `11` glyphs
- `12` glyphs would require `269` bytes, so the APK switches to the segmented type-4 route

## Extracted working sequence (AA scroll)

1. `080001800d391500`  
   Opening handshake (time-based bytes + led type)
2. `04000580`  
   Hardware info/open stage 2
3. `0500128007`  
   Week/day control packet
4. `07000880010001`  
   Open/select channel 1
5. `450000010036000000eec8506c000102000101015000ffffff0000000000ffffff0000001c366363637f6363636300000000ffffff0000001c366363637f63636363000000`  
   Text-scroll content payload (single packet in this case)

Observed notifications:
- `0500088001` (channel ack)
- `0500000103` (content ack)

## Key difference vs GIF path

- **Text scroll path**: short single-content payload after open packets.
- **GIF path**: multi-chunk transfer (`0f100300...`) with stricter commit/play and more failure points.

For current goal (reliable scrolling text), this short native path is preferred.

## Notes

- Success criterion remains visual panel rendering, not BLE write success.
- Handshake in client must remain dynamic (time-derived), not hardcoded.
- APK wrapper path: `ImageTextListActivity.sendTextData2(...)` and `TextActivity.sendByteArray(...)` both end up in `SendCore.sendTextDataInvokFun2(...)`, which wraps channel text/image payloads through `SendCore.payloadChannel(type=4)` into the final `0x45 00 00 01 ... 0x36 ...` packet.
- Font mapping source: no standalone native glyph table was found in smali. The general text stack is bitmap-based (`TextAgreement.getCharBitmap*()` -> `TextAgreement.getTextData()`), so the lightweight 10-byte native glyph cells used here were reconstructed from known captures. `A` and `B` come directly from `tmp/fa02_from_btsnoop_latest.txt`; the remaining uppercase glyphs and space were rebuilt to the same bold 8x10 style in [`scripts/ipixel_font_map.py`](/home/agent/.openclaw/workspace/projects/Bk-Light-AppBypass/scripts/ipixel_font_map.py).

## `0xF9` Long-Text Path

Observed native long-text payloads on `fa02`:

- Fixed header: `f9 00 00 01`
- Length field: big-endian body length at bytes `4..5`
- CRC32: little-endian at bytes `9..12`, computed over `payload[15:]`
- Byte `14`: channel id used by the native text sender
- Byte `15`: glyph count in the packet
- Byte `19`: effect code, matching the short `0x45` path values
- Bytes `22..35`: same white/black color prelude used by the short path
- Glyph encoding: 10-byte native bitmap cells, first glyph immediately after the color prelude, later glyphs prefixed by per-glyph `fg(3) + bg(3)` colors

Derived `body` / `totalData` rule shared by `0xF9` and A1:

- Prefix bytes `0..6`: `[glyph_count][00][01][01][effect][50][00]`
- Prefix bytes `7..20`: `fg(3) + bg(3) + 00 00 + fg(3) + bg(3)`
- First glyph record: `glyph(10) + sep(4 if more glyphs else 3)`
- Later glyph record: `fg(3) + bg(3) + glyph(10) + sep(4 if more glyphs else 3)`
- Body length formula: `20 * glyph_count + 14`

This is the exact structure seen in:

- the accepted `HELLO WORLD` `0xF9` frame (`body_len = 0x00ea = 234`)
- the accepted `109`-char A1 frames (`totalDataLen = 0x00000892 = 2194`)

Current constraints:

- At ATT write-command value size `249`, one `0xF9` packet fits `11` glyphs (`249` total bytes in the capture).
- The repo sender now builds this same body for both `0xF9` and A1.

## Type-4 / "A1" Long-Text Path

Observed capture in [`btmon_from_btsnoop.txt`](/home/agent/.openclaw/workspace/tmp/btmon_from_btsnoop.txt) around `~16:43`:

- Canonical accepted frame extracted from the binary btsnoop starts with `a1 08 00 01 00 92 08 00 00 65 fb 98 c0 00 65 6d ...`
- The same logical frame is continued across four `509`-byte characteristic writes and a final `173`-byte tail
- Panel responds once at the end with `0500000103`
- The payload varies only in CRC and effect byte across captures for effects `1`, `2`, `5`, and `8`

Derived framing:

- Bytes `0..1`: little-endian framed packet length
- Bytes `2..3`: data type `00 01` (same `payloadChannel(type=4)` family used by the APK)
- Byte `4`: type byte `00`
- Bytes `5..8`: little-endian `totalData` length
- Bytes `9..12`: little-endian `CRC32(totalData)`
- Bytes `13..14`: trailer `00 65`
- Bytes `15..`: `totalData`

Derived `totalData` payload:

- Byte `0`: text length, truncated to one byte in current implementation
- Byte `1`: reserved `00`
- Bytes `2..3`: constant `01 01`
- Byte `4`: native effect code (`01`, `02`, `05`, `08` seen in accepted captures)
- Bytes `5..6`: constant `50 00`
- Bytes `7..20`: color prelude `fg(3) + bg(3) + 00 00 + fg(3) + bg(3)`
- Bytes `21..`: the same glyph-record stream used by `0xF9`, not a row-packed bitmap block

Smali confirmation:

- `SendCore.payloadChannel(...)` constructs `[len:2 LE][00 01][type:1][totalDataLen:4 LE][crc32:4 LE][trailer:2][data]`
- For `sendTextDataInvokFun2(..., type=4)` the passed `type` byte is `00`, which matches the capture at header byte `4`
- `SendCore.sendDataInner2(...)` on the BLE2 path patches byte `14` to `0x65`
- `CRC32` is computed over the full `totalData`, not over the transport header

Implementation notes in this repo:

- Auto transport selection is now `<=2 -> 0x45`, `<=11 -> 0xF9`, `>11 -> type-4/"A1"`
- `scripts/native_text_scroll_send.py` now uses one shared text-record body builder for both `0xF9` and A1
- The sender builds one full type-4 frame, then slices it into `509`-byte characteristic writes so the ATT layer matches the captured `511`-byte write-command framing (`2-byte handle + 509-byte value`)
- Current guardrail is `255` glyphs because the first `totalData` byte is a one-byte text length field in the observed format
- The repo still uses its own recovered/reconstructed native glyph profiles; the protocol framing and record layout match the APK/captures even when glyph art differs from the exact app font
- [`scripts/extract_native_a1.py`](/home/agent/.openclaw/workspace/projects/Bk-Light-AppBypass/scripts/extract_native_a1.py) now extracts accepted A1 transactions byte-for-byte from `btsnoop_hci.log` and can replay them for device-side verification
