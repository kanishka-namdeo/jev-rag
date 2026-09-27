# ScanLite SL-400 — Troubleshooting Guide

Model: ScanLite SL-400 workgroup printer-scanner. Firmware baseline v3.1.x.

## Error 13 — Paper Jam

The SL-400 reports error code 13 when a sheet is misaligned in the feed path. To
reset the device after clearing a jam, navigate to **Menu → Service → Soft Reset**
and confirm with the OK key; the unit re-homes the feed path automatically. Unlike
the smaller ScanLite models, no button combination is used.

## Paper Handling

- Standard tray capacity: **500 sheets** (80 g/m²).
- Supported paper weight range: **60–220 g/m²**, the widest range in the ScanLite
  family. Banner paper up to 1.2 m uses the rear straight-through path.

## Status Lights

- Solid amber: **drum near end of life** — order the drum kit within two weeks.
- Blinking amber: transfer belt cleaning cycle pending.
- Blinking red: duplex unit cover open.

## Firmware

Firmware **v3.2.1 fixes the duplex skew issue** affecting SL-400 units manufactured
before March 2025. Network stack security hardening ships in v3.2.2. Firmware
updates are delivered over the network by default.

## Maintenance Parts

The wear part for the SL-400 is the **pickup roller kit RK-140**, rated for 70,000
sheets. Fuser maintenance interval is 160,000 pages. Use of SL-300 roller kits
(RK-130) in the SL-400 is explicitly unsupported and jams the registration sensor.
