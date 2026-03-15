# Native Text Scroll Protocol (working path)

Date: 2026-03-15

## Summary

For the ACT1025 panel, **text scroll mode from iPixel** follows a short 5-packet flow that is different from GIF multi-chunk upload.

This path was extracted from `tmp/btsnoop_hci.log` (around ~13:58 test) and replayed successfully with visible `AA` scrolling on panel.

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
