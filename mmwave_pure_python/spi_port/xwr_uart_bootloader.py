"""xWR1843 ROM serial-bootloader client over UART (Phase 1 of the rf_eval port).

This talks to the xWR1843 *ROM bootloader* (the device must be in **Flashing mode**,
SOP[2:0] = 101 / "SOP mode 5", and power-cycled) to download the rf_eval firmware
(`xwr18xx_radarss.bin` then `xwr18xx_masterss.bin`) into device RAM — exactly what
mmWave Studio's `DownloadBSSFw` / `DownloadMSSFw` do. Once masterss runs it brings up
the SPI mmwavelink interface, after which Phase 2 (PowerOn/ProfileConfig/.../StartFrame)
runs over the FT4232H SPI. See ../reference/UART_BOOTLOADER_PROTOCOL.md.

Protocol = TI SWRA627 (xWR) / SPRACR5 (AWR2243), CONFIRMED empirically on this hardware
(2026-06-21, Ubuntu): PING/GET_VERSION/GET_STATUS all answered correctly.

  Port   : /dev/ttyACM0  (XDS110 Application/User UART, interface 00)
  Baud   : 115200        (autobaud locks here after a UART break)
  Framing: BIG-ENDIAN length field; UART break required before the first command.

  Host pkt:  SYNC(0xAA) | LEN(2,BE)=len(payload)+2 | CKSUM(1)=sum(payload)&0xFF | PAYLOAD
  Dev resp:  LEN(2,BE) | CKSUM(1) | PAYLOAD              (NO 0xAA prefix)
             ACK payload = 00 CC.  STATUS payload(1): 0x40=SUCCESS 0x4B=IN_PROGRESS 0x00=initial.
             GET_STATUS returns ONLY a STATUS response (no preceding ACK).

NOTE: ModemManager grabs /dev/ttyACM* on enumeration (EBUSY). Run `sudo systemctl stop
ModemManager` (or install the udev ID_MM_DEVICE_IGNORE rule for VID 0451) before use.
"""
from __future__ import annotations
import time
import serial

# --- opcodes (SWRA627 Table 2) ---
PING        = 0x20
OPEN_FILE   = 0x21
CLOSE_FILE  = 0x22
GET_STATUS  = 0x23
WRITE_SFLASH= 0x24
WRITE_RAM   = 0x26
ERASE       = 0x28
GET_VERSION = 0x2F

# --- OPEN fields ---
STORAGE_SFLASH = 2
STORAGE_SRAM   = 4
# File-type enum from the app notes (META IMG1..4). For the AWR2243 ES3.0 single combined
# metaImage the DFP uses META_IMG1 (4). The per-image RadarSS-vs-MSS *RAM* file-type codes
# that Studio's DownloadBSSFw/DownloadMSSFw use are NOT in the public app notes — TO CONFIRM.
FILETYPE_META_IMG1 = 4
FILETYPE_META_IMG2 = 5
FILETYPE_META_IMG3 = 6
FILETYPE_META_IMG4 = 7

MAX_CHUNK = 240
SYNC = 0xAA
ACK_PAYLOAD = b"\x00\xcc"
STATUS_SUCCESS = 0x40

SUCCESS_STATUS = {STATUS_SUCCESS}


class BootloaderError(RuntimeError):
    pass


class XwrUartBootloader:
    def __init__(self, port: str = "/dev/ttyACM0", baud: int = 115200, timeout: float = 1.0):
        self.port, self.baud, self.timeout = port, baud, timeout
        self.s: serial.Serial | None = None

    # -- framing --
    @staticmethod
    def _frame(payload: bytes) -> bytes:
        ck = sum(payload) & 0xFF
        ln = (len(payload) + 2).to_bytes(2, "big")
        return bytes([SYNC]) + ln + bytes([ck]) + payload

    def _send(self, payload: bytes) -> None:
        assert self.s is not None
        self.s.reset_input_buffer()
        self.s.write(self._frame(payload))
        self.s.flush()

    def _read_frame(self) -> bytes:
        """Read one length-prefixed device response: LEN(2,BE) | CKSUM(1) | PAYLOAD(LEN-2).
        Returns the full frame bytes, or b'' on timeout. Deterministic (no fixed sleep)."""
        assert self.s is not None
        hdr = self.s.read(2)
        if len(hdr) < 2:
            return b""
        ln = int.from_bytes(hdr, "big")
        rest = self.s.read(ln - 1)  # cksum(1) + payload(LEN-2)
        return hdr + rest

    # -- connection --
    def connect(self) -> None:
        self.s = serial.Serial(self.port, self.baud, timeout=self.timeout)
        self.s.reset_input_buffer(); self.s.reset_output_buffer()
        self.s.send_break(0.05); time.sleep(0.05); self.s.reset_input_buffer()
        if not self.ping():
            raise BootloaderError(
                f"No bootloader ACK on {self.port}@{self.baud}. Is the device in Flashing "
                f"mode (SOP=101) and power-cycled? Is ModemManager stopped?")

    def close(self) -> None:
        if self.s:
            self.s.close(); self.s = None

    def __enter__(self): self.connect(); return self
    def __exit__(self, *a): self.close()

    # -- commands --
    @staticmethod
    def _is_ack(resp: bytes) -> bool:
        return ACK_PAYLOAD in resp

    def ping(self) -> bool:
        self._send(bytes([PING]))
        return self._is_ack(self._read_frame())

    def get_version(self) -> bytes:
        self._send(bytes([GET_VERSION]))
        ack = self._read_frame()        # ACK frame
        ver = self._read_frame()        # VERSION frame
        return ack + ver

    def get_status(self) -> int | None:
        """Returns the STATUS byte (0x40=SUCCESS) or None. GET_STATUS returns only a STATUS frame."""
        self._send(bytes([GET_STATUS]))
        r = self._read_frame()
        # STATUS RESPONSE: LEN(2,BE)=0x0003 | CKSUM(1) | STATUS(1)
        if len(r) >= 4 and r[1] == 0x03:
            return r[3]
        return r[-1] if r else None

    def open_file(self, file_size: int, storage: int, file_type: int) -> bool:
        payload = (bytes([OPEN_FILE])
                   + file_size.to_bytes(4, "big")
                   + storage.to_bytes(4, "big")
                   + file_type.to_bytes(4, "big")
                   + (0).to_bytes(4, "big"))  # RESERVED
        self._send(payload)
        return self._is_ack(self._read_frame())

    def write_ram_chunk(self, chunk: bytes) -> bool:
        if len(chunk) > MAX_CHUNK:
            raise ValueError("chunk > 240")
        self._send(bytes([WRITE_RAM]) + chunk)
        return self._is_ack(self._read_frame())

    def close_file(self, storage: int) -> bool:
        self._send(bytes([CLOSE_FILE]) + storage.to_bytes(4, "big"))
        return self._is_ack(self._read_frame())

    def erase(self, settle_s: float = 30.0) -> int | None:
        """ERASE DEVICE (0x28): wipe the SFLASH so functional mode falls back to SPI boot.
        Returns the final STATUS byte (0x40=SUCCESS). Reversible: reflash mmw_demo afterwards."""
        self._send(bytes([ERASE]))
        ack = self._is_ack(self._read_frame())
        if not ack:
            return None
        # Erase can take seconds; poll status until SUCCESS or settle timeout.
        import time as _t
        deadline_iters = int(settle_s / 0.3) + 1
        st = None
        for _ in range(deadline_iters):
            st = self.get_status()
            if st == STATUS_SUCCESS:
                return st
            _t.sleep(0.3)
        return st

    # -- high-level --
    def download_to_ram(self, bin_path: str, file_type: int) -> None:
        """OPEN(SRAM) -> WRITE_RAM chunks (in file byte order) -> CLOSE(SRAM)."""
        data = open(bin_path, "rb").read()
        if not self.open_file(len(data), STORAGE_SRAM, file_type):
            raise BootloaderError(f"OPEN failed for {bin_path} (file_type={file_type})")
        for i in range(0, len(data), MAX_CHUNK):
            if not self.write_ram_chunk(data[i:i + MAX_CHUNK]):
                raise BootloaderError(f"WRITE_RAM failed at offset {i} of {bin_path}")
        if not self.close_file(STORAGE_SRAM):
            raise BootloaderError(f"CLOSE failed for {bin_path}")
        st = self.get_status()
        if st not in SUCCESS_STATUS:
            raise BootloaderError(f"post-download status=0x{st:02x} (expected 0x40 SUCCESS)")


if __name__ == "__main__":
    import sys
    port = sys.argv[1] if len(sys.argv) > 1 else "/dev/ttyACM0"
    with XwrUartBootloader(port) as bl:
        print(f"[ok] bootloader alive on {port}")
        print(f"  version: {bl.get_version().hex()}")
        print(f"  status : 0x{bl.get_status():02x}")
