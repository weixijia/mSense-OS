export const languages = [
  { code: 'en', label: 'English', flag: 'US' },
  { code: 'cn', label: '简体中文', flag: 'CN' }
]

const PAPER = 'https://doi.org/10.1145/3737904.3768536'
const REPO = 'https://github.com/weixijia/Vomee'

const translations = {
  en: {
    nav: { modalities: 'Modalities', architecture: 'Architecture', citation: 'Citation', github: 'GitHub' },
    hero: {
      badge: 'MobiCom ’25',
      title1: 'Raw mmWave signals,',
      title2: 'in pure Python.',
      subtitle1: 'The first open-source multimodal platform with direct access to raw mmWave data —',
      subtitle2: 'time-aligned with RGB video, audio, and real-time skeleton.',
      btnDownload: 'View on GitHub',
      btnPaper: 'Read the Paper',
    },
    modalities: {
      eyebrow: 'Modalities',
      title1: 'Four signals,',
      title2: 'one timeline.',
      subtitle: 'Every stream is captured against a shared clock, so the modalities stay aligned frame for frame.',
      items: [
        { icon: '🎥', title: 'Video', desc: 'High-resolution camera capture at 1280×720 / 30 fps, exported to MP4 or AVI.' },
        { icon: '🎙️', title: 'Audio', desc: 'Multi-channel audio recording, exported to WAV or MP3 alongside the video timeline.' },
        { icon: '📡', title: 'mmWave', desc: 'TI IWR/AWR radar point clouds with Range-Doppler and Range-Azimuth heatmaps, stored as HDF5.' },
        { icon: '🦴', title: 'Skeleton', desc: 'ViTPose 2D keypoints per person — [x, y, confidence] — tagged with backend, dataset, and group, as JSON.' },
      ],
    },
    capabilities: {
      eyebrow: 'Capabilities',
      title1: 'Built for rigorous',
      title2: 'capture.',
      subtitle: 'Research-grade synchronization, a pure-Python radar pipeline, and a live dashboard — no proprietary tooling required.',
      items: [
        { title: 'Precise synchronization', desc: 'Timestamp alignment across all modalities, with optional microcontroller hardware sync for exact sampling and multi-radar use without interference.' },
        { title: 'Pure-Python mmWave', desc: 'Drive TI AWR1843 + DCA1000 directly — no mmWave Studio. Raw ADC over UDP, FFT on PyTorch (CUDA / CPU) with a NumPy fallback.' },
        { title: 'Live desktop dashboard', desc: 'PySide6 + Qt Quick: camera with a telemetry HUD on the left, Range-Doppler and Range-Azimuth heatmaps on the right, streaming the moment you launch.' },
      ],
    },
    architecture: {
      eyebrow: 'Architecture',
      title1: 'Capture, synchronize,',
      title2: 'export.',
      subtitle: 'A source → processing → sink pipeline keeps every modality on one master clock from sensor to disk.',
      cards: [
        { step: '01', title: 'Capture', desc: 'Independent sources stream camera, audio, radar, and pose in parallel, each stamped on the host clock.' },
        { step: '02', title: 'Synchronize', desc: 'A master clock aligns streams within a configurable tolerance; a microcontroller can drive hardware-level sampling.' },
        { step: '03', title: 'Export', desc: 'Aligned data is written to MP4/AVI, WAV/MP3, HDF5 radar cubes, and per-frame skeleton JSON — ready for analysis.' },
      ],
    },
    citation: {
      eyebrow: 'Citation',
      title1: 'Academic references.',
      subtitleVomee: 'Vomee is a research platform from our MobiCom ’25 paper. If you use it in your work, please cite:',
      subtitleVitpose: 'Skeleton tracking is powered by ViTPose (via easy_ViTPose). Please credit the authors when you use the pose modality:',
      subtitleYolo: 'Person detection uses Ultralytics YOLO. Please cite their work if you use the detector:',
    },
    footer: {
      brandDesc: 'A multimodal sensing platform for synchronized video, audio, mmWave, and skeleton capture.',
      copyright: '© 2026 Xijia Wei. Released under the MIT License.',
      columns: [
        { title: 'Platform', links: [
          { label: 'Modalities', href: '#modalities' },
          { label: 'Architecture', href: '#architecture' },
          { label: 'GitHub', href: REPO },
          { label: 'Releases', href: REPO + '/releases' },
        ] },
        { title: 'Resources', links: [
          { label: 'Paper (DOI)', href: PAPER },
          { label: 'Contact (Xijia Wei)', href: 'mailto:xijia.wei.21@ucl.ac.uk' },
          { label: 'Issues', href: REPO + '/issues' },
        ] },
      ],
    },
  },
  cn: {
    nav: { modalities: '感知模态', architecture: '系统架构', citation: '学术引用', github: 'GitHub' },
    hero: {
      badge: 'MobiCom ’25',
      title1: '原始毫米波信号，纯 Python 实现。',
      title2: '',
      subtitle1: '首个可直接访问原始毫米波数据的开源多模态平台 ——',
      subtitle2: '与 RGB 视频、音频和实时骨骼时间对齐。',
      btnDownload: '在 GitHub 上查看',
      btnPaper: '阅读论文',
    },
    modalities: {
      eyebrow: '感知模态',
      title1: '四路信号，同一时间轴。',
      title2: '',
      subtitle: '所有数据流共用同一时钟采集，逐帧对齐，模态之间始终同步。',
      items: [
        { icon: '🎥', title: '视频', desc: '1280×720 / 30 fps 高分辨率相机采集，导出为 MP4 或 AVI。' },
        { icon: '🎙️', title: '音频', desc: '多通道音频录制，与视频时间轴对齐，导出为 WAV 或 MP3。' },
        { icon: '📡', title: '毫米波', desc: 'TI IWR/AWR 雷达点云，含 Range-Doppler 与 Range-Azimuth 热力图，存储为 HDF5。' },
        { icon: '🦴', title: '骨骼', desc: 'ViTPose 每人 2D 关键点 —— [x, y, 置信度] —— 标注后端、数据集与关键点组，存为 JSON。' },
      ],
    },
    capabilities: {
      eyebrow: '核心能力',
      title1: '为严谨采集而构建。',
      title2: '',
      subtitle: '研究级同步、纯 Python 雷达管线，以及实时仪表盘 —— 无需任何专有工具链。',
      items: [
        { title: '精确同步', desc: '所有模态基于时间戳对齐，并可选微控制器硬件同步，实现精确采样与多雷达无干扰协同。' },
        { title: '纯 Python 毫米波', desc: '直接驱动 TI AWR1843 + DCA1000，无需 mmWave Studio。原始 ADC 经 UDP 传输，FFT 跑在 PyTorch（CUDA / CPU），并有 NumPy 兜底。' },
        { title: '实时桌面仪表盘', desc: 'PySide6 + Qt Quick：左侧相机带遥测 HUD，右侧 Range-Doppler 与 Range-Azimuth 热力图，启动即实时预览。' },
      ],
    },
    architecture: {
      eyebrow: '系统架构',
      title1: '采集、同步、导出。',
      title2: '',
      subtitle: 'source → processing → sink 管线让每个模态从传感器到磁盘都处于同一主时钟之上。',
      cards: [
        { step: '01', title: '采集', desc: '相机、音频、雷达与姿态由独立 source 并行采集，各自打上主机时钟时间戳。' },
        { step: '02', title: '同步', desc: '主时钟在可配置容差内对齐各数据流；微控制器还可驱动硬件级采样。' },
        { step: '03', title: '导出', desc: '对齐后的数据写入 MP4/AVI、WAV/MP3、HDF5 雷达数据立方与逐帧骨骼 JSON，可直接用于分析。' },
      ],
    },
    citation: {
      eyebrow: '学术引用',
      title1: '学术引用。',
      subtitleVomee: 'Vomee 是我们 MobiCom ’25 论文中的研究平台。如果您在工作中使用了它，请引用：',
      subtitleVitpose: '骨骼追踪由 ViTPose（经 easy_ViTPose）驱动。如果使用姿态模态，请致谢原作者：',
      subtitleYolo: '人体检测使用 Ultralytics YOLO。如果使用检测器，请引用他们的工作：',
    },
    footer: {
      brandDesc: '一个多模态感知平台，用于同步采集视频、音频、毫米波与骨骼数据。',
      copyright: '© 2026 Xijia Wei. 基于 MIT 协议开源。',
      columns: [
        { title: '平台', links: [
          { label: '感知模态', href: '#modalities' },
          { label: '系统架构', href: '#architecture' },
          { label: 'GitHub', href: REPO },
          { label: '发布版本', href: REPO + '/releases' },
        ] },
        { title: '资源', links: [
          { label: '论文 (DOI)', href: PAPER },
          { label: '联系方式 (魏熙佳)', href: 'mailto:xijia.wei.21@ucl.ac.uk' },
          { label: '问题反馈', href: REPO + '/issues' },
        ] },
      ],
    },
  },
}

export function getTranslation(langCode) {
  return translations[langCode] || translations['en']
}
