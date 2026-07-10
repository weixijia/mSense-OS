"""Typed configuration for Vomee (dataclasses), mirroring the legacy ``config.py``.

During the rebuild migration the module-level ``config.py`` remains the source of truth
for the OLD app; these immutable dataclasses mirror it for the NEW pipeline and add the
rebuild-specific :class:`RecordCfg` / :class:`ComputeCfg`. :meth:`AppConfig.from_legacy`
syncs from ``config.py`` so the two cannot drift; :meth:`AppConfig.load` returns defaults.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Tuple


@dataclass(frozen=True)
class AdcCfg:
    chirps: int = 255
    rx: int = 4
    tx: int = 2
    samples: int = 256
    iq: int = 2
    bytes: int = 2

    @property
    def virtual_antennas(self) -> int:
        return 2 * self.rx  # first 2 TX used


@dataclass(frozen=True)
class CameraCfg:
    device: int = 0
    width: int = 1280
    height: int = 720
    fps: int = 30


@dataclass(frozen=True)
class TriggerCfg:
    enable: bool = False
    com_port: str = "auto"
    baud: int = 921600
    cfg_file: str = "mmwave_pure_python/studio_cli/src/profiles/profile_vomee_256x255_cont.cfg"
    json_file: str = "mmwave_pure_python/configFiles/cf.json"
    stop_on_exit: bool = True


@dataclass(frozen=True)
class NetworkCfg:
    pc_ip: str = "192.168.33.30"
    radar_ip: str = "192.168.33.180"
    data_port: int = 4098
    config_port: int = 4096


@dataclass(frozen=True)
class BufferCfg:
    mmwave_buffer_size: int = 100
    camera_buffer_size: int = 1
    file_queue_size: int = 100


@dataclass(frozen=True)
class PoseCfg:
    backend: str = "vitpose"
    vitpose_model: str = "s"
    vitpose_dataset: str = "wholebody"
    keypoint_group: str = "body"
    yolo_size: int = 320
    device: str = "auto"
    confidence_threshold: float = 0.3
    skeleton_thickness: int = 2


@dataclass(frozen=True)
class DisplayCfg:
    update_rate_hz: int = 30
    rd_size: Tuple[int, int] = (256, 255)
    ra_size: Tuple[int, int] = (256, 256)


@dataclass(frozen=True)
class RecordCfg:
    """Per-stream data-collection toggles (rebuild). Show != Save (independent)."""

    save_raw: bool = True
    save_rd: bool = True
    save_ra: bool = True
    save_da: bool = False
    save_skeleton: bool = False
    save_rgb: bool = False
    show_skeleton: bool = True
    show_rgb: bool = True
    base_dir: str = "./recordings"


@dataclass(frozen=True)
class ComputeCfg:
    prefer_device: Optional[str] = None  # None -> auto (cuda > mps > cpu)


@dataclass(frozen=True)
class DspCfg:
    """RD/RA orientation — MUST match the model's training data.

    Mirrors legacy ``config.MMWAVE_RD_FLIP_RANGE`` (byte-for-byte verified
    True on 2026-06-22; see the warning block in config.py). A wrong value
    silently corrupts model input.
    """
    rd_flip_range: bool = True


@dataclass(frozen=True)
class AppConfig:
    adc: AdcCfg = field(default_factory=AdcCfg)
    camera: CameraCfg = field(default_factory=CameraCfg)
    trigger: TriggerCfg = field(default_factory=TriggerCfg)
    network: NetworkCfg = field(default_factory=NetworkCfg)
    buffers: BufferCfg = field(default_factory=BufferCfg)
    pose: PoseCfg = field(default_factory=PoseCfg)
    display: DisplayCfg = field(default_factory=DisplayCfg)
    record: RecordCfg = field(default_factory=RecordCfg)
    compute: ComputeCfg = field(default_factory=ComputeCfg)
    dsp: DspCfg = field(default_factory=DspCfg)

    @classmethod
    def load(cls) -> "AppConfig":
        """Defaults (mirror of legacy config.py at the time of writing)."""
        return cls()

    @classmethod
    def from_legacy(cls) -> "AppConfig":
        """Build from the legacy module-level ``config.py`` so the new typed config
        cannot drift from the old one during migration. Falls back to defaults if a
        block/key is absent."""
        try:
            import config as L  # the legacy module at repo root
        except Exception:
            return cls()

        def block(name):
            return getattr(L, name, {}) or {}

        a, c = block("ADC_PARAMS"), block("CAMERA_PARAMS")
        t, n = block("MMWAVE_TRIGGER"), block("NETWORK_PARAMS")
        b, p = block("BUFFER_PARAMS"), block("POSE_PARAMS")
        d = block("DISPLAY_PARAMS")

        defaults = cls()
        adc = AdcCfg(chirps=a.get("chirps", defaults.adc.chirps), rx=a.get("rx", defaults.adc.rx),
                     tx=a.get("tx", defaults.adc.tx), samples=a.get("samples", defaults.adc.samples),
                     iq=a.get("IQ", defaults.adc.iq), bytes=a.get("bytes", defaults.adc.bytes))
        cam = CameraCfg(device=c.get("device", defaults.camera.device), width=c.get("width", defaults.camera.width),
                        height=c.get("height", defaults.camera.height), fps=c.get("fps", defaults.camera.fps))
        trig = TriggerCfg(enable=t.get("enable", defaults.trigger.enable), com_port=t.get("com_port", defaults.trigger.com_port),
                          baud=t.get("baud", defaults.trigger.baud), cfg_file=t.get("cfg_file", defaults.trigger.cfg_file),
                          json_file=t.get("json_file", defaults.trigger.json_file), stop_on_exit=t.get("stop_on_exit", defaults.trigger.stop_on_exit))
        net = NetworkCfg(pc_ip=n.get("pc_ip", defaults.network.pc_ip), radar_ip=n.get("radar_ip", defaults.network.radar_ip),
                         data_port=n.get("data_port", defaults.network.data_port), config_port=n.get("config_port", defaults.network.config_port))
        buf = BufferCfg(mmwave_buffer_size=b.get("mmwave_buffer_size", defaults.buffers.mmwave_buffer_size),
                        camera_buffer_size=b.get("camera_buffer_size", defaults.buffers.camera_buffer_size),
                        file_queue_size=b.get("file_queue_size", defaults.buffers.file_queue_size))
        pose = PoseCfg(backend=p.get("backend", defaults.pose.backend), vitpose_model=p.get("vitpose_model", defaults.pose.vitpose_model),
                       vitpose_dataset=p.get("vitpose_dataset", defaults.pose.vitpose_dataset), keypoint_group=p.get("keypoint_group", defaults.pose.keypoint_group),
                       yolo_size=p.get("yolo_size", defaults.pose.yolo_size), device=p.get("device", defaults.pose.device),
                       confidence_threshold=p.get("confidence_threshold", defaults.pose.confidence_threshold),
                       skeleton_thickness=p.get("skeleton_thickness", defaults.pose.skeleton_thickness))
        disp = DisplayCfg(update_rate_hz=d.get("update_rate_hz", defaults.display.update_rate_hz),
                          rd_size=tuple(d.get("rd_size", defaults.display.rd_size)),
                          ra_size=tuple(d.get("ra_size", defaults.display.ra_size)))
        dsp = DspCfg(rd_flip_range=getattr(L, "MMWAVE_RD_FLIP_RANGE",
                                           defaults.dsp.rd_flip_range))
        return cls(adc=adc, camera=cam, trigger=trig, network=net, buffers=buf,
                   pose=pose, display=disp, dsp=dsp)


__all__ = [
    "AdcCfg", "CameraCfg", "TriggerCfg", "NetworkCfg", "BufferCfg", "PoseCfg",
    "DisplayCfg", "RecordCfg", "ComputeCfg", "DspCfg", "AppConfig",
]
