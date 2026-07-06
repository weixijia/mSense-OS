# Candidate Repositories — scored evaluation

> ## ✅ RESOLVED 2026-06-22 — none of these were needed for the live path (see `SETUP.md`)
>
> The pure-Python trigger evaluation below was for replacing mmWave Studio. The shipped workflow keeps
> Studio for the one-time bring-up and captures on Ubuntu receive-only (`python main.py --no-camera
> --no-trigger`). `gaoweifan/pyRadar` (#1) is still used — but only for its **fpga_udp DCA1000 UDP
> receiver**, which we extended with an off-GIL C frame-assembler (patch in
> `mmwave_pure_python/patches/`); its SPI/UART trigger code is not used. Kept as a historical record.

Legend for **Covers**: `DCA` = DCA1000 UDP control, `RF` = IWR RF config without
Studio, `UART` = CLI-UART cfg path, `SPI` = mmwavelink-over-SPI/FTDI, `RX` = raw
ADC receive/parse only.

| # | Repo | ★ | Covers | Board match | Status | Notes |
|---|------|---|--------|-------------|--------|-------|
| 1 | **gaoweifan/pyRadar** | 172 | DCA + UART + (SPI for AWR2243 only) | **IWR1843+DCA1000 exact** | PRIMARY | Full Studio replacement via mmw_demo fw + UART + DCA1000 UDP. Has `xWR1843_profile_3D.cfg`. fpga_udp = C/pybind11 ext (needs MSVC + FTDI D2XX). |
| 2 | EsonJohn/mmWave_script | 119 | DCA (via CLI exe) | IWR1642+DCA1000 | secondary | "without mmWave Studio". Custom-built `DCA1000EVM_CLI_Control.exe` + `run.py`. Not pure python; calls TI CLI exe. |
| 3 | PreSenseRadar/OpenRadar | 901 | DCA (pure python) + RX/parse | generic xWR | REFERENCE | `mmwave/dataloader/adc.py` = pure-python DCA1000 UDP control + parse. pyRadar's mmwave is forked from this. No RF config. |
| 4 | WiseLabCMU/rover | 13 | DCA + collection | AWR1843+DCA1000 | tertiary | chirp data collection platform |
| 5 | jkablan/iwr6843_raw_collect | 12 | DCA | IWR6843+DCA1000 | tertiary | raw collect |
| 6 | bitsforbrains/mmwave | 18 | DCA + proc | DCA1000 | tertiary | python module capture/process |

---

## Key architectural finding

The triggering Vomee lacks = two pieces, both pure-python-able:
1. **UART control (COM4)** — send `.cfg` profile + `sensorStart` (pyserial). Requires radar
   running **mmw_demo firmware in functional mode (SOP[2:0]=001)**, NOT mmWave Studio's RAM image.
2. **DCA1000 UDP control (port 4096)** — `config_fpga` / `config_record` / `start_record` command
   packets (header `0xA55A`, footer `0xAAEE`). Protocol in OpenRadar `adc.py`.

Vomee's `mmwave_capture.py` already RECEIVES + parses the resulting UDP raw-ADC stream.

### THE decision point (needs user / physical access)
mmWave Studio drives the radar by loading a meta-image into RAM over the FTDI (mmwavelink/SPI).
Pure-python Path B instead needs the radar in **functional mode running xwr18xx_mmw_demo**:
- Physically set **SOP[2:0]=001** jumpers/switches on the IWR1843BOOST.
- Ensure `xwr18xx_mmw_demo` is flashed (one-time UniFlash); may already be on flash.
This is mutually exclusive with the current mmWave-Studio session.

---

## Detailed evaluations

(one subsection per repo as it is cloned + tested)
