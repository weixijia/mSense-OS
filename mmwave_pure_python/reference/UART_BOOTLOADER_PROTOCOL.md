# xWR1843 UART ROM Bootloader — Phase 1 of the rf_eval port (CONFIRMED)

> **Note (2026-06-22):** the rf_eval Linux port is **parked** (the live path is the Studio→reboot→
> `python main.py` receive-only bypass — see `../SETUP.md`). Also, a later Studio USB trace
> showed the xWR1843 bring-up is actually all-SPI (the "two-phase UART download" premise below was
> wrong). Kept as a protocol reference for the UART ROM bootloader itself.

This is the **firmware-download-over-UART** half of the two-phase rf_eval bring-up
(see `../UBUNTU_SPI_PORT_HANDOVER.md` §CORRECTION). Replicates mmWave Studio's
`DownloadBSSFw` / `DownloadMSSFw`. Validated empirically on this hardware (Ubuntu, 2026-06-21).

Client: `../spi_port/xwr_uart_bootloader.py`. Protocol spec: TI **SWRA627** (xWR) and
**SPRACR5** (AWR2243) — "Programming Serial Data Flash Over UART (Bootloader Service)".

## Hardware preconditions (CONFIRMED)
- SOP switch S1 = **Flashing mode**, `SOP[2:0] = 101` (SOP2=ON, SOP1=OFF, SOP0=ON) — see
  AWR1843BOOST UG **SPRUIM4B** Table 4. (Functional=001 boots flash fw and the mmw_demo CLI
  *echoes* bytes — that's how we detected wrong mode. Debug=011 halts the R4F.)
- **Power-cycle** after changing SOP (latched only at power-up; nRESET is not enough).
- **Port** = `/dev/ttyACM0` = XDS110 Application/User UART (USB interface 00). (ttyACM1 = iface 03, aux.)
- **ModemManager must be off** the port: `sudo systemctl stop ModemManager`, or a udev rule
  `ATTRS{idVendor}=="0451", ENV{ID_MM_DEVICE_IGNORE}="1"`. Otherwise EBUSY on open.

## Wire protocol (CONFIRMED)
- **Baud 115200**, autobaud locks after a **UART break** sent before the first command.
- **Byte order BIG-ENDIAN** for multi-byte fields (verified: length `00 03` accepted, `03 00` not).
- Host packet: `SYNC(0xAA) | LEN(2,BE) | CKSUM(1) | PAYLOAD`, where `LEN = len(PAYLOAD)+2`,
  `CKSUM = sum(PAYLOAD bytes) & 0xFF`.
- Device response: `LEN(2,BE) | CKSUM(1) | PAYLOAD` (**no** 0xAA prefix).
  - **ACK** = payload `00 CC` (full frame `00 04 CC 00 CC`).
  - **STATUS** = `00 03 <ck> <status>`; status `0x40`=SUCCESS, `0x4B`=IN_PROGRESS, `0x00`=initial.
    `GET_STATUS` returns *only* a STATUS frame (no preceding ACK). Other actionable cmds → ACK.

### Commands (SWRA627 Table 2)
| cmd | id | notes |
|---|---|---|
| PING | 0x20 | → ACK |
| OPEN FILE | 0x21 | payload: `id | FILE_SIZE(4) | STORAGE(4) | FILE_TYPE(4) | RESERVED(4)` |
| CLOSE FILE | 0x22 | payload: `id | STORAGE(4)` |
| GET STATUS | 0x23 | → STATUS only |
| WRITE FILE to SFLASH | 0x24 | payload: `id | data≤240` |
| WRITE FILE to RAM | 0x26 | payload: `id | data≤240` |
| ERASE DEVICE | 0x28 | erases SFLASH |
| GET VERSION | 0x2F | → ACK + VERSION (`00 0e <ck> <rom_ver:4> <rsvd:8>`) |

STORAGE: `2`=SFLASH, `4`=SRAM. Chunk count `N = ceil(file_size/240)`.

### Validated exchange (this device)
```
PING        TX aa00032020  RX 0004cc00cc                      (ACK)
GET_VERSION TX aa00032f2f  RX 0004cc00cc 000e0f 03000a02...   (ACK + ROM ver 03 00 0a 02)
GET_STATUS  TX aa00032323  RX 00034040                        (STATUS 0x40 = SUCCESS)
```

## OPEN QUESTION — file-type for separate RadarSS vs MSS → RAM (last Phase-1 unknown)
The public app notes only document the FILE_TYPE enum as META IMG1..4 (`4..7`) and mostly the
**flash** (SFLASH) of a *combined* metaImage. The AWR2243 DFP uses META_IMG1(4) for its single
combined image over SPI. But xWR1843 rf_eval ships **separate** `xwr18xx_radarss.bin` (BSS) and
`xwr18xx_masterss.bin` (MSS), which Studio downloads via two separate `DownloadBSSFw`/`DownloadMSSFw`
calls **to RAM**. The exact `OPEN` `FILE_TYPE` (+ whether `CLOSE` triggers execution, or PowerOn over
SPI does) for the per-image RAM case is **not in the public docs** — it's in mmWave Studio's source.
→ Resolve via Studio source / a reverse-engineered flasher, or experiment (RAM writes are non-destructive):
try `download_to_ram(radarss, ft)` for `ft in {4,5,6,7,...}` and check `GET_STATUS==0x40`, then confirm
end-to-end when Phase-2 SPI `PowerOn` stops returning `-8`.

## EMPIRICAL FINDING (2026-06-21 PM) — firmware loads, but flashing mode does not execute it
Full radarss(149 chunks)+masterss(221 chunks) downloads succeed: **every WRITE_TO_RAM ACKs, CLOSE ACKs**,
for *every* file_type pair tried — `(4,5) (0,0) (2,3) (0,1) (1,2) (6,7) (4,4)`. But in **all** cases:
- `GET_STATUS` after CLOSE stays **`0x00`** (never `0x40 SUCCESS`), and
- a post-download **PING still ACKs** → the ROM is **not** eclipsed → the MSS image is **not running**.

So OPEN/WRITE/CLOSE do not validate file_type, and **Flashing mode (SOP-5/101) accepts RAM writes but
does not eclipse-and-execute** the loaded image. The data is in RAM; nothing runs it. Two live hypotheses:
1. **Execution is triggered by the Phase-2 SPI `PowerOn`** (Studio order: DownloadBSS/MSS over UART →
   *then* `ar1.PowerOn` over SPI). i.e. load over UART, then SPI PowerOn eclipses ROM + starts MSS.
   → Test end-to-end: UART-load then SPI PowerOn **in the same session (NO reset/power-cycle — that wipes
   RAM)**. Needs **S2 switch = SPI** (not CAN) per SPRUIM4B §2.8.4, and a Phase-2 SPI flow that does NOT
   reset/re-download (the firmware is already in RAM).
2. **A different boot mode** than flashing-101 is required for "load over UART and execute". (SWRA627: the
   UART-load-and-execute path is the *functional-mode fallback when SFLASH is invalid*; our SFLASH has
   valid mmw_demo, so functional boots that instead. Studio forces the UART path somehow — exact SOP TBD.)

## Firmware bins
`../firmware/xwr18xx_radarss.bin` (35,728 B, BSS) · `../firmware/xwr18xx_masterss.bin` (52,904 B, MSS).
Order per Studio: **radarss (BSS) first, then masterss (MSS)**, then PowerOn over SPI (Phase 2).
