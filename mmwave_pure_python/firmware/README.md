# rf_eval firmware (TI mmWave Studio 02.01.01.00)

These are the **RF-eval firmware binaries mmWave Studio loads into the xWR1843's RAM over SPI**
(`DownloadBSSFw` / `DownloadMSSFw` in `../reference/lua/skeleton.lua`). They produce phase-coherent
chirps (the sharp single zero-Doppler line). The planned SPI/rf_eval port loads these instead of the
flashed studio_cli no-DSP firmware (which has the ~10× phase-noise skirt → RD vertical lines).
See `../UBUNTU_SPI_PORT_HANDOVER.md`.

| file | role | size (bytes) |
|---|---|---|
| `xwr18xx_radarss.bin` | RadarSS / BSS (RF front-end firmware) | 35,728 |
| `xwr18xx_masterss.bin` | MSS (master subsystem firmware) | 52,904 |

- **Source:** `C:\ti\mmwave_studio_02_01_01_00\rf_eval_firmware\{radarss,masterss}\` (Windows install).
  Also ship with TI **mmWave-DFP** / **mmWave SDK**.
- **License:** TI-licensed firmware. Included here for this project's own use. If this repo is/becomes
  public, consider whether redistribution is permitted under your TI license, or keep them out-of-tree.
- Loaded into **RAM** (2-part: radarss then masterss), not flashed — same as mmWave Studio. See the
  port plan §10-R1 for the RAM 2-part download flow to implement via `rlDeviceFileDownload`.

---

## `mmwave_Studio_cli_xwr18xx.bin` — flashable no-DSP "studio_cli" firmware (151,620 B)

The **flashable** firmware for the *current* pure-Python path (UART CLI @ 921600, full **256×255** raw
ADC — stock `mmw_demo` caps Doppler near 256×64). Flashed to the radar's **SFLASH** (persistent),
unlike the rf_eval pair above (loaded to RAM over SPI).

- **Purpose:** restore the pure-Python UART path after a flash erase. Flash via **UniFlash** (flashing
  mode **SOP=101**) on Windows, or via the UART ROM bootloader on Linux
  (`../reference/UART_BOOTLOADER_PROTOCOL.md`).
- **SHA256:** `16401BA8B676C6D21392D9157F96ED10F28B646623606B6178E7F44DF5180F95`
- **⚠️ NOTE for Ubuntu-CC:** the firmware you erased is **this studio_cli no-DSP bin**, *not*
  `xwr18xx_mmw_demo`. Reflash THIS to get 256×255 back (mmw_demo would cap at 256×64). Source: TI
  Radar Toolbox "mmWave Studio CLI" tool.
