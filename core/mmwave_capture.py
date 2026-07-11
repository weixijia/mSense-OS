"""
mmWave Radar Data Capture Module

Handles UDP reception from TI IWR1843 mmWave radar, frame assembly,
packet loss detection/recovery, and circular buffer management.

Preserved core logic from steaming.py.
"""

import socket
import struct
import threading
import numpy as np
from datetime import datetime
from typing import Tuple, Optional, Union

import sys
sys.path.append('..')
from config import ADC_PARAMS, NETWORK_PARAMS, BUFFER_PARAMS

# Static constants
MAX_PACKET_SIZE = 4096
BYTES_IN_PACKET = 1456

# Dynamic calculations based on ADC parameters
BYTES_IN_FRAME = (ADC_PARAMS['chirps'] * ADC_PARAMS['rx'] * ADC_PARAMS['tx'] *
                  ADC_PARAMS['IQ'] * ADC_PARAMS['samples'] * ADC_PARAMS['bytes'])

BYTES_IN_FRAME_CLIPPED = (BYTES_IN_FRAME // BYTES_IN_PACKET) * BYTES_IN_PACKET
PACKETS_IN_FRAME = BYTES_IN_FRAME / BYTES_IN_PACKET
PACKETS_IN_FRAME_CLIPPED = BYTES_IN_FRAME // BYTES_IN_PACKET
UINT16_IN_PACKET = BYTES_IN_PACKET // 2
UINT16_IN_FRAME = BYTES_IN_FRAME // 2


class MmWaveCapture(threading.Thread):
    """
    Thread-based mmWave radar data capture.

    Receives UDP packets from TI IWR1843 radar, assembles frames,
    handles packet loss, and maintains a circular buffer.
    """

    def __init__(self,
                 pc_ip: str = None,
                 radar_ip: str = None,
                 data_port: int = None,
                 buffer_size: int = None):
        """
        Initialize mmWave capture thread.

        Args:
            pc_ip: PC static IP address (default from config)
            radar_ip: Radar ADC IP address (default from config)
            data_port: UDP data port (default from config)
            buffer_size: Circular buffer size in frames (default from config)
        """
        threading.Thread.__init__(self, daemon=True)

        # Use config defaults if not specified
        self.pc_ip = pc_ip or NETWORK_PARAMS['pc_ip']
        self.radar_ip = radar_ip or NETWORK_PARAMS['radar_ip']
        self.data_port = data_port or NETWORK_PARAMS['data_port']
        self.config_port = NETWORK_PARAMS['config_port']
        self.buffer_size = buffer_size or BUFFER_PARAMS['mmwave_buffer_size']

        # Thread control
        self._running = True
        self._lock = threading.Lock()

        # Buffer management
        self.recent_cap_num = 0
        self.latest_read_num = 0
        self.next_read_position = 0
        self.next_cap_position = 0
        self.buffer_overwritten = False

        # Initialize sockets
        self._init_sockets()

        # Initialize buffers
        self.buffer_array = np.zeros((self.buffer_size, BYTES_IN_FRAME // 2), dtype=np.int16)
        self.item_num_array = np.zeros(self.buffer_size, dtype=np.int32)
        self.lost_packet_flag_array = np.zeros(self.buffer_size, dtype=bool)
        self.timestamp_array = np.zeros(self.buffer_size, dtype=float)

        # Statistics
        self.total_frames = 0
        self.lost_frames = 0

    def _init_sockets(self):
        """Initialize the UDP data socket.

        NOTE: this class is receive-only. It deliberately does NOT bind the
        config port (4096) — the radar/DCA1000 are configured by mmWave
        Studio, and holding 4096 here would only risk conflicts.
        """
        self.data_recv = (self.pc_ip, self.data_port)

        self.data_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)

        # Bind data socket with large receive buffer
        self.data_socket.bind(self.data_recv)
        self.data_socket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 2**27)

    def run(self):
        """Main thread entry point."""
        try:
            self._frame_receiver()
        except OSError as e:
            if self._running:
                print(f"[mmWave] Socket error: {e}")
        except Exception as e:
            if self._running:
                print(f"[mmWave] Capture error: {e}")
                import traceback
                traceback.print_exc()

    def _frame_receiver(self):
        """
        Main frame reception loop.

        Receives UDP packets, assembles complete frames, handles packet loss,
        and stores frames in circular buffer.
        """
        self.data_socket.settimeout(2)  # 2 second timeout for responsiveness
        lost_packets = False
        timeout_count = 0
        max_timeouts = 5  # Max consecutive timeouts before warning

        recent_frame = np.zeros(UINT16_IN_FRAME, dtype=np.int16)

        print("[mmWave] Waiting for radar data...")

        # Find the beginning of first frame
        while self._running:
            try:
                packet_num, byte_count, packet_data = self._read_data_packet()
                timeout_count = 0  # Reset on successful read
            except socket.timeout:
                timeout_count += 1
                if timeout_count >= max_timeouts:
                    print(f"[mmWave] No data received (timeout {timeout_count}). Is radar streaming?")
                    timeout_count = 0
                continue
            except OSError:
                if not self._running:
                    return  # Socket closed, exit gracefully
                raise

            # Skip malformed/foreign datagrams (a runt or stray packet on the
            # port would otherwise raise a broadcast ValueError in assembly
            # and kill the capture thread for the whole session)
            if packet_data.size != UINT16_IN_PACKET:
                continue

            after_packet_count = (byte_count + BYTES_IN_PACKET) % BYTES_IN_FRAME

            # Found new frame start (frame boundary within this packet)
            if after_packet_count < BYTES_IN_PACKET:
                frame_start_time = datetime.now().timestamp()

                recent_frame[0:after_packet_count // 2] = packet_data[(BYTES_IN_PACKET - after_packet_count) // 2:]

                self.recent_cap_num = (byte_count + BYTES_IN_PACKET) // BYTES_IN_FRAME
                recent_frame_collect_count = after_packet_count
                last_packet_num = packet_num
                print("[mmWave] First frame found, starting capture")
                break

            last_packet_num = packet_num

        # Main reception loop
        while self._running:
            try:
                packet_num, byte_count, packet_data = self._read_data_packet()
                timeout_count = 0
            except socket.timeout:
                timeout_count += 1
                if timeout_count >= max_timeouts:
                    print(f"[mmWave] Data timeout ({timeout_count})")
                    timeout_count = 0
                continue
            except OSError:
                if not self._running:
                    return  # Socket closed, exit gracefully
                raise

            # Skip malformed/foreign datagrams (see first-frame search).
            # A skipped genuine-but-truncated packet leaves a sequence gap
            # that the loss detector below catches on the next packet.
            if packet_data.size != UINT16_IN_PACKET:
                continue

            # Packet loss detection
            if last_packet_num < packet_num - 1:
                lost_packets = True
                self.lost_frames += 1
                print("[mmWave] Packet lost! Searching for next frame...")

                # Find next valid frame start
                while self._running:
                    try:
                        packet_num, byte_count, packet_data = self._read_data_packet()
                    except socket.timeout:
                        continue
                    except OSError:
                        if not self._running:
                            return
                        raise

                    if packet_data.size != UINT16_IN_PACKET:
                        continue

                    after_packet_count = (byte_count + BYTES_IN_PACKET) % BYTES_IN_FRAME

                    if after_packet_count < BYTES_IN_PACKET:
                        # Fresh buffer: the aborted frame's partial data must
                        # not leak into the new frame
                        recent_frame = np.zeros(UINT16_IN_FRAME, dtype=np.int16)
                        recent_frame[0:after_packet_count // 2] = packet_data[(BYTES_IN_PACKET - after_packet_count) // 2:]
                        self.recent_cap_num = (byte_count + BYTES_IN_PACKET) // BYTES_IN_FRAME
                        recent_frame_collect_count = after_packet_count
                        print("[mmWave] Found new frame, resuming capture")
                        break

                # Restart the main loop with a fresh packet. The recovery
                # packet above has already been consumed into recent_frame —
                # falling through to the assembly code below would process the
                # same packet TWICE, inflating the collect count by one packet
                # and byte-shifting every subsequent frame (silent corruption).
                last_packet_num = packet_num
                continue

            # Check if frame is complete
            if recent_frame_collect_count + BYTES_IN_PACKET >= BYTES_IN_FRAME:
                frame_end_time = datetime.now().timestamp()
                recent_frame[recent_frame_collect_count // 2:] = packet_data[:(BYTES_IN_FRAME - recent_frame_collect_count) // 2]

                # Store completed frame
                self._store_frame(recent_frame, frame_end_time, lost_packets)

                # Prepare for next frame
                self.recent_cap_num = (byte_count + BYTES_IN_PACKET) // BYTES_IN_FRAME

                recent_frame = np.zeros(UINT16_IN_FRAME, dtype=np.int16)

                after_packet_count = (recent_frame_collect_count + BYTES_IN_PACKET) % BYTES_IN_FRAME
                recent_frame[0:after_packet_count // 2] = packet_data[(BYTES_IN_PACKET - after_packet_count) // 2:]
                recent_frame_collect_count = after_packet_count
                lost_packets = False

            else:
                # Continue collecting packets for current frame
                after_packet_count = (recent_frame_collect_count + BYTES_IN_PACKET) % BYTES_IN_FRAME
                recent_frame[recent_frame_collect_count // 2:after_packet_count // 2] = packet_data
                recent_frame_collect_count = after_packet_count

            last_packet_num = packet_num

    def get_frame(self) -> Tuple[Union[np.ndarray, str], float, int, bool]:
        """
        Get the next available frame from buffer.

        Returns:
            Tuple containing:
                - raw_data: numpy array of int16 ADC data, or error string
                - timestamp: frame capture timestamp
                - frame_num: frame sequence number
                - lost_packet: whether packet loss occurred for this frame
        """
        with self._lock:
            if self.buffer_overwritten:
                # Consumer fell behind and the circular buffer wrapped. Instead
                # of freezing on this error forever (the old behaviour), drop the
                # stale backlog and resync to the newest captured frame — correct
                # real-time "show latest" semantics, and self-heals after a hiccup.
                # (Unconditional: the old `latest_read_num != 0` guard skipped the
                # resync when the last-read radar frame index happened to be 0.)
                self.next_read_position = (self.next_cap_position - 1 + self.buffer_size) % self.buffer_size
                self.buffer_overwritten = False

            next_read_pos = (self.next_read_position + 1) % self.buffer_size

            # No new frame available yet
            if self.next_read_position == self.next_cap_position:
                return "wait new frame", 0.0, -2, False

            # Return buffered frame
            read_frame = self.buffer_array[self.next_read_position].copy()
            timestamp = self.timestamp_array[self.next_read_position]
            self.latest_read_num = self.item_num_array[self.next_read_position]
            lost_packet_flag = self.lost_packet_flag_array[self.next_read_position]

            self.next_read_position = next_read_pos

            return read_frame, timestamp, self.latest_read_num, lost_packet_flag

    def _store_frame(self, recent_frame: np.ndarray, frame_time: float, lost_packets: bool):
        """
        Store a completed frame in the circular buffer.

        Args:
            recent_frame: Complete frame data
            frame_time: Frame capture timestamp
            lost_packets: Whether packet loss occurred
        """
        with self._lock:
            self.buffer_array[self.next_cap_position] = recent_frame
            self.timestamp_array[self.next_cap_position] = frame_time
            self.item_num_array[self.next_cap_position] = self.recent_cap_num
            self.lost_packet_flag_array[self.next_cap_position] = lost_packets

            # Check for buffer overwrite
            if (self.next_read_position - 1 + self.buffer_size) % self.buffer_size == self.next_cap_position:
                self.buffer_overwritten = True

            self.next_cap_position = (self.next_cap_position + 1) % self.buffer_size
            self.total_frames += 1

    def _read_data_packet(self) -> Tuple[int, int, np.ndarray]:
        """
        Read a single UDP data packet.

        Returns:
            Tuple containing:
                - packet_num: Packet sequence number
                - byte_count: Cumulative byte count
                - packet_data: Raw ADC data as numpy array

        Raises:
            OSError: If socket is closed or unavailable
            socket.timeout: If no data received within timeout
        """
        data, addr = self.data_socket.recvfrom(MAX_PACKET_SIZE)

        # Unsigned: the DCA1000 packet counter is a uint32 — signed parsing
        # breaks loss detection when the counter passes 2^31 (~41 h of
        # continuous streaming)
        packet_num = struct.unpack('<1L', data[:4])[0]
        byte_count = struct.unpack('>Q', b'\x00\x00' + data[4:10][::-1])[0]
        packet_data = np.frombuffer(data[10:], dtype=np.uint16)

        return packet_num, byte_count, packet_data

    def stop(self):
        """Stop the capture thread and release resources."""
        self._running = False

        # Close sockets to unblock any pending recvfrom
        try:
            self.data_socket.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            self.data_socket.close()
        except OSError:
            pass

    def get_stats(self) -> dict:
        """Get capture statistics."""
        return {
            'total_frames': self.total_frames,
            'lost_frames': self.lost_frames,
            'buffer_position': self.next_cap_position,
            'loss_rate': self.lost_frames / max(1, self.total_frames)
        }

    @property
    def is_running(self) -> bool:
        """Check if capture thread is running."""
        return self._running and self.is_alive()
