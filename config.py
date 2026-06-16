# Vomee Multi-Modal Data Capture System Configuration

# Radar frame sampling period (ms) - 100ms = 10 Hz
periodicity = 100

# TI IWR1843 mmWave Radar ADC Parameters
ADC_PARAMS = {
    'chirps': 255,      # Number of chirps per frame
    'rx': 4,            # Number of receive antennas
    'tx': 2,            # Number of transmit antennas
    'samples': 256,     # Range samples per chirp
    'IQ': 2,            # I and Q components
    'bytes': 2          # 16-bit integers
}

# Camera Parameters
CAMERA_PARAMS = {
    'device': 0,        # Camera device ID (changed from 1 to 0)
    'width': 1280,      # Frame width
    'height': 720,      # Frame height
    'fps': 30           # Target frame rate
}

# Network Configuration for mmWave Radar
NETWORK_PARAMS = {
    'pc_ip': '192.168.33.30',       # PC static IP
    'radar_ip': '192.168.33.180',   # Radar ADC IP
    'data_port': 4098,              # UDP data port
    'config_port': 4096             # UDP config port
}

# Buffer Configuration
BUFFER_PARAMS = {
    'mmwave_buffer_size': 100,      # Circular buffer for mmWave frames
    'camera_buffer_size': 1,        # Camera buffer (low latency)
    'file_queue_size': 100          # Async file writer queue size
}

# MediaPipe Configuration (fallback pose backend)
MEDIAPIPE_PARAMS = {
    'model_complexity': 1,          # 0=Lite, 1=Full, 2=Heavy
    'min_detection_confidence': 0.5,
    'min_tracking_confidence': 0.5,
    'process_width': 640,           # Downscale for processing
    'process_height': 480
}

# Pose Estimation Configuration
# ViTPose is the default skeleton-tracking framework; MediaPipe is a fallback.
POSE_PARAMS = {
    'backend': 'vitpose',           # 'vitpose' (default) or 'mediapipe'
    'vitpose_model': 's',           # ViTPose size: 's' (smallest/fastest), 'b', 'l', 'h'
    'vitpose_dataset': 'wholebody', # 'wholebody' (133 kpts) or 'coco' (17 body kpts)
    'keypoint_group': 'body',       # default view: 'body', 'body_face', 'body_hands', 'wholebody'
    'yolo_size': 320,               # YOLO detector input size
    'device': 'auto',               # 'auto' -> cuda > mps > cpu
    'confidence_threshold': 0.3,    # min keypoint confidence to draw/record
    'skeleton_thickness': 2
}

# Display Configuration
DISPLAY_PARAMS = {
    'update_rate_hz': 30,           # GUI update rate
    'rd_size': (256, 255),          # Range-Doppler heatmap size
    'ra_size': (256, 256)           # Range-Azimuth heatmap size
}

# Synchronization Configuration
SYNC_PARAMS = {
    'max_timestamp_diff_ms': 50,    # Max allowed timestamp difference for sync
    'master_clock': 'mmwave'        # Master clock source
}
