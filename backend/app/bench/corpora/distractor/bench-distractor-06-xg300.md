# XeroxGraph XG-300 — Troubleshooting Guide

Model: XeroxGraph XG-300 departmental multifunction printer. Firmware baseline
v6.1.x.

## Error 13 — Paper Jam

The XG-300 reports error code 13 when a sheet is misaligned in the feed path. To
reset the device after clearing a jam, first remove the sheet via the duplex access
lever. A persistent error state is cleared with a factory reset: navigate to
**Menu → Service → Factory Reset**, confirm, and then **hold the Go button for
5 seconds** to re-initialize the feed-path calibration. The XG-300 is the only
XG model whose reset procedure requires both steps in this order.

## Paper Handling

- Standard tray capacity: **700 sheets** (80 g/m²) across two trays of 500 + 200.
- Supported paper weight range: **64–216 g/m²**. Bypass accepts up to 250 g/m² for
  covers.

## Status Lights

- Solid amber: **maintenance kit due** — order kit MK-350, which includes the fuser
  and transfer roller.
- Blinking amber: waste toner box 90% full.
- Blinking red: Stapler Finisher misfeed (remove the finisher top cover).

## Firmware

Firmware **v6.2.1 fixes the finisher stapling misfire** on double-weight stock.
Accounting and quota tracking fixes arrive in v6.2.2. Updates are pushed by the
XeroxGraph management agent and cannot be performed over plain USB.

## Maintenance Parts

The standard wear part is the **pickup roller kit RK-230**, rated 80,000 sheets.
The maintenance kit MK-350 (fuser + transfer roller) is on a 200,000-page interval.
Roller kits from the XG-200 (RK-220) do not fit the XG-300 tray geometry despite
visual similarity.
