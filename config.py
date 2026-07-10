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

# RD/RA range-axis orientation for the processor.
#   False = preserved fft.py orientation (unchanged; what the regression golden + the pure-Python
#           capture use). For mmWave-Studio-sourced frames this renders near (range 0) at the TOP.
#   True  = flip so near is at the BOTTOM (Studio frames are range-mirrored vs the pure-Python path).
# ⚠️ This MUST match the orientation the ML model was TRAINED on (mmWave Studio recordings). Do NOT
# set by visual preference — verify against a real training-data RD sample first. Same array is
# displayed AND fed to the model AND written to HDF5, so a wrong value silently corrupts model input.
# VERIFIED 2026-06-22: =True matches the model's training data byte-for-byte. Training RDs were made by
# the original Studio-era mmwave_silent/fft.py, which always flips RD/RA [::-1] (DA not flipped). Proof:
# our processor(flip_range=True) on a training raw frame == that session's saved RD/*.npy to max-abs
# 1.2e-7; flip_range=False differed by 0.57.
MMWAVE_RD_FLIP_RANGE = True

# Camera Parameters
CAMERA_PARAMS = {
    'device': 0,        # Camera device ID (changed from 1 to 0)
    'width': 1280,      # Frame width
    'height': 720,      # Frame height
    'fps': 30           # Target frame rate
}

# Pure-Python mmWave trigger (replaces mmWave Studio). Off by default so the
# existing Studio workflow is unaffected. Enable with `python main.py --trigger`.
# When triggering, ADC_PARAMS['chirps'] is auto-set from the .cfg's frameCfg numLoops.
MMWAVE_TRIGGER = {
    'enable': False,
    'com_port': 'auto',                                       # radar CLI UART; 'auto' detects the XDS110 (Linux /dev/ttyACM0, macOS /dev/cu.usbmodem*, Windows COMx). Override with --trigger-com.
    'baud': 921600,                                           # no-DSP studio_cli firmware uses 921600 (mmw_demo was 115200)
    # No-DSP firmware profile: 256 samples x 255 loops, NO cfar/gui -> full 256x255 raw ADC, no detection-matrix cap.
    'cfg_file': 'mmwave_pure_python/studio_cli/src/profiles/profile_vomee_256x255_cont.cfg',
    'json_file': 'mmwave_pure_python/configFiles/cf.json',
    'stop_on_exit': True,                                     # sensorStop when Vomee closes
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

# Pose Estimation Configuration
# ViTPose is the skeleton-tracking framework (cross-platform: CUDA / Apple MPS / CPU).
POSE_PARAMS = {
    'backend': 'vitpose',           # 'vitpose'
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
