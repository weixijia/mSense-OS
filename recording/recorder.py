"""
Recording Session Manager Module

Handles session creation, directory structure, and metadata management.
"""

import os
import json
import threading
from datetime import datetime
from typing import Optional, Dict, Any
from pathlib import Path

import sys
sys.path.append('..')
from config import ADC_PARAMS, CAMERA_PARAMS


class Recorder:
    """
    Recording session manager.

    Creates session directories, manages metadata, and coordinates
    with FileWriter for data persistence.
    """

    def __init__(self, base_path: str = None):
        """
        Initialize recorder.

        Args:
            base_path: Base directory for recording sessions (default: ./recordings)
        """
        self.base_path = Path(base_path) if base_path else Path("./recordings")
        self.current_session = None
        self.session_path = None
        self.metadata = {}
        self.frame_count = 0
        self.start_time = None

    def start_session(self, skeleton_enabled: bool = False,
                      capture_info: Dict[str, Any] = None) -> str:
        """
        Start a new recording session.

        Creates session directory structure and initializes metadata.

        Args:
            skeleton_enabled: Whether skeleton detection is enabled
            capture_info: Optional dict describing the active mmWave capture
                backend (name, timestamp/frame_num semantics) — recorded in
                metadata so datasets are interpretable offline

        Returns:
            Session directory path
        """
        # Generate session name. Millisecond suffix guarantees unique
        # session paths even on immediate restart (the file writer refuses
        # to reopen paths from a finalized session).
        now = datetime.now()
        timestamp = now.strftime("%Y%m%d_%H%M%S") + f"_{now.microsecond // 1000:03d}"
        self.current_session = f"session_{timestamp}"
        self.session_path = self.base_path / self.current_session

        # Create directory structure
        self._create_directory_structure()

        # Initialize metadata
        self.start_time = datetime.now()
        self.frame_count = 0
        self.metadata = self._create_metadata(skeleton_enabled)
        if capture_info:
            self.metadata["capture_info"] = capture_info

        # Save initial metadata
        self._save_metadata()

        return str(self.session_path)

    def _create_directory_structure(self):
        """Create session directory structure."""
        directories = [
            self.session_path,
            self.session_path / "raw",
            self.session_path / "heatmaps" / "rd",
            self.session_path / "heatmaps" / "ra",
            self.session_path / "camera",
            self.session_path / "skeleton"
        ]

        for directory in directories:
            directory.mkdir(parents=True, exist_ok=True)

    def _create_metadata(self, skeleton_enabled: bool) -> Dict[str, Any]:
        """
        Create session metadata.

        Args:
            skeleton_enabled: Whether skeleton detection is enabled

        Returns:
            Metadata dictionary
        """
        return {
            "session_id": self.current_session,
            "start_time": self.start_time.isoformat(),
            "end_time": None,
            "duration_seconds": None,
            "frame_count": 0,
            "skeleton_enabled": skeleton_enabled,
            "adc_params": dict(ADC_PARAMS),   # snapshot (--trigger mutates chirps)
            "camera_params": CAMERA_PARAMS,
            "software_version": "2.0.0",
            "format_version": 2,
            "raw_record_format": (
                "Each raw frame: header '<4sIdBI' "
                "(magic b'VMRF', frame_num uint32, timestamp float64, "
                "lost_packet uint8, payload_bytes uint32) followed by "
                "int16 ADC payload."
            ),
            "notes": ""
        }

    def _save_metadata(self):
        """Save metadata to JSON file."""
        if self.session_path:
            metadata_path = self.session_path / "metadata.json"
            with open(metadata_path, 'w') as f:
                json.dump(self.metadata, f, indent=2)

    def stop_session(self) -> Dict[str, Any]:
        """
        Stop the current recording session.

        Updates and saves final metadata.

        Returns:
            Final session metadata
        """
        if not self.current_session:
            return {}

        end_time = datetime.now()
        duration = (end_time - self.start_time).total_seconds()

        self.metadata["end_time"] = end_time.isoformat()
        self.metadata["duration_seconds"] = duration
        self.metadata["frame_count"] = self.frame_count

        self._save_metadata()

        result = self.metadata.copy()

        # Reset state
        self.current_session = None
        self.session_path = None
        self.metadata = {}
        self.frame_count = 0
        self.start_time = None

        return result

    def increment_frame_count(self):
        """Increment the frame counter."""
        self.frame_count += 1

    def get_frame_path(self, frame_num: int, data_type: str) -> Optional[Path]:
        """
        Get file path for a specific frame and data type.

        Args:
            frame_num: Frame number
            data_type: Type of data ('rd', 'ra', 'camera', 'skeleton')

        Returns:
            Path object or None if no session active
        """
        if not self.session_path:
            return None

        filename = f"{frame_num:05d}"

        if data_type == "rd":
            return self.session_path / "heatmaps" / "rd" / f"{filename}.npy"
        elif data_type == "ra":
            return self.session_path / "heatmaps" / "ra" / f"{filename}.npy"
        elif data_type == "camera":
            return self.session_path / "camera" / f"{filename}.npy"
        elif data_type == "skeleton":
            return self.session_path / "skeleton" / f"{filename}.json"
        else:
            return None

    def get_raw_path(self) -> Optional[Path]:
        """Get path for raw mmWave data file."""
        if not self.session_path:
            return None
        return self.session_path / "raw" / "mmwave.bin"

    def get_timestamps_path(self) -> Optional[Path]:
        """Get path for timestamps CSV file."""
        if not self.session_path:
            return None
        return self.session_path / "timestamps.csv"

    def add_note(self, note: str):
        """Add a note to the session metadata."""
        if self.metadata:
            if self.metadata["notes"]:
                self.metadata["notes"] += "\n" + note
            else:
                self.metadata["notes"] = note
            self._save_metadata()

    @property
    def is_recording(self) -> bool:
        """Check if a session is active."""
        return self.current_session is not None

    @property
    def session_info(self) -> Dict[str, Any]:
        """Get current session info."""
        if not self.current_session:
            return {}

        elapsed = (datetime.now() - self.start_time).total_seconds() if self.start_time else 0

        return {
            "session_id": self.current_session,
            "path": str(self.session_path),
            "frame_count": self.frame_count,
            "elapsed_seconds": elapsed,
            "skeleton_enabled": self.metadata.get("skeleton_enabled", False)
        }


class TimestampLogger:
    """
    Logs timestamps for recorded frames.

    Writes frame number, mmWave timestamp, and camera timestamp to CSV.
    """

    def __init__(self, filepath: Path):
        """
        Initialize timestamp logger.

        Args:
            filepath: Path to timestamps CSV file
        """
        self.filepath = filepath
        self.file = None
        # The mmWave worker thread logs while the GUI thread may close the
        # file at session stop — every access must hold the lock
        self._lock = threading.Lock()

    def open(self):
        """Open the timestamp file and write header."""
        with self._lock:
            self.file = open(self.filepath, 'w')
            self.file.write("frame_num,mmwave_ts,camera_ts,diff_ms,lost_packet\n")

    def log(self, frame_num: int, mmwave_ts: float, camera_ts: float,
            lost_packet: bool = False):
        """
        Log a timestamp entry.

        Args:
            frame_num: Frame number
            mmwave_ts: mmWave timestamp
            camera_ts: Camera timestamp (0 if no camera frame available)
            lost_packet: Whether frames/packets were lost before this frame
        """
        with self._lock:
            if not self.file:
                return
            has_both = camera_ts > 0 and mmwave_ts > 0
            diff_ms = abs(mmwave_ts - camera_ts) * 1000 if has_both else -1
            self.file.write(f"{frame_num},{mmwave_ts:.6f},{camera_ts:.6f},"
                            f"{diff_ms:.2f},{1 if lost_packet else 0}\n")
            # Flush per line (10 Hz) so a crash never loses the whole log
            self.file.flush()

    def close(self):
        """Close the timestamp file."""
        with self._lock:
            if self.file:
                self.file.close()
                self.file = None

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False
