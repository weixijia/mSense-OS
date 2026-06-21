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
