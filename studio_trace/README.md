# studio_trace/ — mmWave Studio USB bring-up capture (for the SPI/rf_eval port)

> **Note (2026-06-22):** the Linux SPI/rf_eval port this trace was captured for is now **parked** — the
> live capture path is the Studio-bring-up → reboot → `python main.py --no-camera --no-trigger` bypass
> (see `mmwave_pure_python/SETUP.md`). This trace remains a valid reference for how Studio drives the
> xWR1843 over SPI, should the Linux port ever be revived.

## `studio_bringup_ftdi_xds.pcapng` (36 MB, committed)

USBPcap capture of a **full, successful mmWave Studio rf_eval bring-up** on the xWR1843
(2026-06-22, Windows), filtered to ONLY the two relevant USB devices:

- **device 12 = FT4232H `0451:fd03`** — the **SPI/MPSSE control** path: SOPControl, reset,
  `DownloadBSSFw`/`DownloadMSSFw` (rf_eval firmware → RAM), PowerOn, RfInit, Profile/Chirp/Frame
  config, StartFrame. **578,381 pkts, 289,134 with SPI payload — this is the prize.**
- **device 11 = XDS110 `0451:bef3`** — any UART (596 pkts).

> The raw capture was **4.8 GB** (≈99% webcam USB video from Desktop Vomee) and was discarded;
> only this filtered FTDI+XDS110 trace is kept (the rest is gitignored — see repo `.gitignore`).

## Hardware state Studio needed (CONFIRMED, user-verified — supersedes earlier guesses)
- **SOP0=ON, SOP1=ON, SOP2=OFF** (= SOP[2:0] = **011**, the SPI/dev-download mode). NOT 001 Functional.
- Worked on an **ERASED SFLASH** (no flashed firmware present) → Studio downloads rf_eval to RAM over SPI.
- Resulting RD had **no vertical lines** → the clean, phase-coherent path.

## Decode on Ubuntu (tshark)
```
# FTDI SPI/MPSSE bytes (bring-up = early; after StartFrame it's continuous polling, ignore the tail)
tshark -r studio_bringup_ftdi_xds.pcapng -Y "usb.device_address==12 && usb.capdata" \
       -T fields -e frame.time_relative -e usb.endpoint_address -e usb.capdata
# XDS110 UART
tshark -r studio_bringup_ftdi_xds.pcapng -Y "usb.device_address==11 && usb.capdata" -T fields -e usb.capdata
```
The firmware download is the early burst of large OUT transfers (radarss **35,728 B** then masterss
**52,904 B**, chunked over SPI). Cross-reference `../mmwave_pure_python/reference/lua/skeleton.lua`
for the command order.
