"""
Async File Writer Module

Queue-based file writer for non-blocking I/O operations.
Handles writing of mmWave data, heatmaps, camera frames, and skeleton data.
"""

import threading
import queue
import numpy as np
import json
from pathlib import Path
from typing import Optional, Dict, Any, Union
from dataclasses import dataclass
from enum import Enum

import sys
sys.path.append('..')
from config import BUFFER_PARAMS


class DataType(Enum):
    """Types of data that can be written."""
    RAW_MMWAVE = "raw_mmwave"
    RD_HEATMAP = "rd_heatmap"
    RA_HEATMAP = "ra_heatmap"
    DA_HEATMAP = "da_heatmap"
    CAMERA_FRAME = "camera_frame"
    SKELETON = "skeleton"


@dataclass
class WriteTask:
    """Task for the file writer queue."""
    data_type: DataType
    path: Path
    data: Union[np.ndarray, dict, bytes]
    frame_num: int


class FileWriter(threading.Thread):
    """
    Async queue-based file writer.

    Runs in a separate thread to prevent file I/O from blocking
    the main capture loop. Drops oldest frames if queue is full.
    """

    def __init__(self, queue_size: int = None):
        """
        Initialize file writer thread.

        Args:
            queue_size: Maximum queue size (default from config)
        """
        threading.Thread.__init__(self, daemon=True)

        self.queue_size = queue_size or BUFFER_PARAMS['file_queue_size']
        self._queue = queue.Queue(maxsize=self.queue_size)
        self._running = True
        self._lock = threading.Lock()

        # Statistics
        self._writes_completed = 0
        self._writes_dropped = 0
        self._bytes_written = 0

        # Raw mmWave file handle
        self._raw_file = None
        self._raw_file_path = None

    def run(self):
        """Main writer loop."""
        while self._running:
            try:
                task = self._queue.get(timeout=0.1)
                self._process_task(task)
                self._queue.task_done()
            except queue.Empty:
                continue
            except Exception as e:
                print(f"FileWriter error: {e}")

        # Process remaining items
        while not self._queue.empty():
            try:
                task = self._queue.get_nowait()
                self._process_task(task)
                self._queue.task_done()
            except queue.Empty:
                break

        # Close raw file if open
        self._close_raw_file()

    def _process_task(self, task: WriteTask):
        """
        Process a single write task.

        Args:
            task: WriteTask to process
        """
        try:
            if task.data_type == DataType.RAW_MMWAVE:
                self._write_raw_mmwave(task.path, task.data)
            elif task.data_type == DataType.RD_HEATMAP:
                self._write_numpy(task.path, task.data)
            elif task.data_type == DataType.RA_HEATMAP:
                self._write_numpy(task.path, task.data)
            elif task.data_type == DataType.DA_HEATMAP:
                self._write_numpy(task.path, task.data)
            elif task.data_type == DataType.CAMERA_FRAME:
                self._write_numpy(task.path, task.data)
            elif task.data_type == DataType.SKELETON:
                self._write_json(task.path, task.data)

            with self._lock:
                self._writes_completed += 1

        except Exception as e:
            print(f"Error writing {task.data_type.value}: {e}")

    def _write_raw_mmwave(self, path: Path, data: np.ndarray):
        """
        Write raw mmWave data to binary file.

        Appends to existing file for efficient streaming.

        Args:
            path: File path
            data: Raw ADC data as int16 array
        """
        # Open file if not already open or if path changed
        if self._raw_file is None or self._raw_file_path != path:
            self._close_raw_file()
            self._raw_file = open(path, 'ab')  # Append binary
            self._raw_file_path = path

        # Write data
        data_bytes = data.tobytes()
        self._raw_file.write(data_bytes)

        with self._lock:
            self._bytes_written += len(data_bytes)

    def _write_numpy(self, path: Path, data: np.ndarray):
        """
        Write numpy array to .npy file.

        Args:
            path: File path
            data: Numpy array to save
        """
        np.save(path, data)

        with self._lock:
            self._bytes_written += data.nbytes

    def _write_json(self, path: Path, data: dict):
        """
        Write dictionary to JSON file.

        Args:
            path: File path
            data: Dictionary to save
        """
        with open(path, 'w') as f:
            json.dump(data, f)

        with self._lock:
            self._bytes_written += len(json.dumps(data))

    def _close_raw_file(self):
        """Close the raw mmWave file if open."""
        if self._raw_file:
            self._raw_file.close()
            self._raw_file = None
            self._raw_file_path = None

    def submit(self, data_type: DataType, path: Path, data: Any, frame_num: int) -> bool:
        """
        Submit a write task to the queue.

        Args:
            data_type: Type of data
            path: File path
            data: Data to write
            frame_num: Frame number

        Returns:
            True if submitted, False if dropped
        """
        task = WriteTask(
            data_type=data_type,
            path=path,
            data=data,
            frame_num=frame_num
        )

        try:
            self._queue.put_nowait(task)
            return True
        except queue.Full:
            # Drop oldest item and add new one
            try:
                self._queue.get_nowait()
                self._queue.put_nowait(task)
                with self._lock:
                    self._writes_dropped += 1
                return True
            except queue.Empty:
                return False

    def write_raw_mmwave(self, path: Path, data: np.ndarray, frame_num: int) -> bool:
        """Submit raw mmWave data for writing."""
        return self.submit(DataType.RAW_MMWAVE, path, data, frame_num)

    def write_rd_heatmap(self, path: Path, data: np.ndarray, frame_num: int) -> bool:
        """Submit Range-Doppler heatmap for writing."""
        return self.submit(DataType.RD_HEATMAP, path, data, frame_num)

    def write_ra_heatmap(self, path: Path, data: np.ndarray, frame_num: int) -> bool:
        """Submit Range-Azimuth heatmap for writing."""
        return self.submit(DataType.RA_HEATMAP, path, data, frame_num)

    def write_da_heatmap(self, path: Path, data: np.ndarray, frame_num: int) -> bool:
        """Submit Doppler-Azimuth heatmap for writing."""
        return self.submit(DataType.DA_HEATMAP, path, data, frame_num)

    def write_camera_frame(self, path: Path, data: np.ndarray, frame_num: int) -> bool:
        """Submit camera frame for writing."""
        return self.submit(DataType.CAMERA_FRAME, path, data, frame_num)

    def write_skeleton(self, path: Path, data: dict, frame_num: int) -> bool:
        """Submit skeleton data for writing."""
        return self.submit(DataType.SKELETON, path, data, frame_num)

    def stop(self):
        """Stop the writer thread."""
        self._running = False

    def wait_completion(self, timeout: float = None):
        """
        Wait for all pending writes to complete.

        Args:
            timeout: Maximum time to wait in seconds
        """
        self._queue.join()

    def get_stats(self) -> Dict[str, Any]:
        """Get writer statistics."""
        with self._lock:
            return {
                "writes_completed": self._writes_completed,
                "writes_dropped": self._writes_dropped,
                "bytes_written": self._bytes_written,
                "queue_size": self._queue.qsize(),
                "queue_capacity": self.queue_size,
                "drop_rate": self._writes_dropped / max(1, self._writes_completed + self._writes_dropped)
            }

    def reset_stats(self):
        """Reset statistics."""
        with self._lock:
            self._writes_completed = 0
            self._writes_dropped = 0
            self._bytes_written = 0

    @property
    def is_running(self) -> bool:
        """Check if writer thread is running."""
        return self._running and self.is_alive()

    @property
    def queue_utilization(self) -> float:
        """Get queue utilization as a fraction."""
        return self._queue.qsize() / self.queue_size
