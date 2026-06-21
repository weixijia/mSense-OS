# RD「等距竖线」根因定位

> 对比对象
> - **Studio 版(参考,无竖线)**:`C:\Users\Chuang Yu\Desktop\Vomee`(PyQt5 GUI)+ mmWave Studio 触发(SPI 把 `rf_eval` 固件装进 RAM);录制 `session_20260621_181053`
> - **纯 Python 版(有竖线)**:`C:\Users\Chuang Yu\Documents\Vomee`(QML GUI)+ studio_cli flash 无 DSP 固件 + UART 触发;录制 `session_20260621_181732`、`session_20260621_194824`

## 结论(已确认)

**竖线来自纯 Python 的「采集/固件」环节,不是可视化。** 纯 Python 用的 studio_cli flash 固件,其**啁啾间相位相干性比 Studio 经 SPI 装入的 `rf_eval`(`xwr18xx_radarss.bin`+`xwr18xx_masterss.bin`)差约 10 倍**,把本应集中在零多普勒一根线上的静止杂波能量,周期性/宽带地散布到邻近多普勒 bin → 在 RD 上呈现为零多普勒线两侧的「等距竖线/裙边」。

> ⚠️ 修正:本文件早期版本曾错误地结论为「显示渲染问题、数据干净」。那是基于**整段平均** + **线性尺度** + **相邻列相关性**的分析,漏掉了低幅度宽带相位噪声。用户用对照实验推翻了它,后续运动控制分析确认了真因。下文为更正后的结论。

## 决定性证据

### 1. 对照实验(用户做的,最硬)
同一个**旧 PyQt5 可视化**(`Desktop\Vomee`):
- 喂 **Studio 采集** → **无竖线**
- 喂 **纯 Python 采集**(`trigger_only.py` 触发后接收)→ **有竖线**
- 纯 Python 在 SOP=001 和 SOP=011 下都有竖线;Studio 一直无。

→ 唯一变量是「谁来采集」。**可视化无辜,问题在采集链。**

### 2. 运动控制的相位相干性测量(`scratchpad/static_compare.py`)
两段录制拍的动作不同,整段平均会把「场景/运动」混进来。于是只取**静止帧**(用远多普勒能量筛掉有人移动的帧),再测近零多普勒「裙边/DC」比:

| 采集 | 静止帧 近零多普勒 skirt/DC |
|---|---|
| Studio(rf_eval 固件) | **0.0002**(刀锋尖峰,±3–4 bin 落底) |
| PurePy 194824(studio_cli) | **0.0017–0.0028**(裙边拖到 ±15–20 bin) |
| PurePy 181732(studio_cli) | **0.0017–0.0021**(裙边形状与上者一致) |

→ 纯 Python 静止帧把杂波能量散开 **≈10×**,且**两段录制完全一致** = 系统性、可复现。**排除丢包**(丢包是突发的,这个每帧都有)、**排除场景**(已做运动控制)、**排除配置**(cfg 已逐行核对一致,见下表)。这是**啁啾间相位不相干(相位噪声)**的典型特征。

### 3. 形态(`scratchpad/comb_period.py`)
是**宽带相位噪声裙边**,不是干净的等周期梳齿 → **没有"关掉第 N 个周期性进程"这种一行 cfg 便宜修法**。studio_cli 示例 cfg 里也无直接控制相位相干性的开关(`calibMonCfg` 是帧间校准,不碰帧内裙边)。

## `skeleton.lua` → `.cfg` 逐行转换(配置层已确认一致,排除为竖线成因)

cfg:`mmwave_pure_python/studio_cli/src/profiles/profile_vomee_256x255_cont.cfg`

| skeleton.lua | .cfg | 等价 |
|---|---|---|
| `ChanNAdcConfig(1,0,1,1,1,1,1,2,1,0)` | `channelCfg 15 5 0` + `adcCfg 2 1` | ✅ TX0+TX2、4RX、16bit、复数 |
| `ProfileConfig(...,65.998,0,256,4800,0,0,30)` | `profileCfg 0 77 20 6 60 0 0 65.998 0 256 4800 0 0 30` | ✅ 全一致 |
| `ChirpConfig(0,...,1,0,0)` / `(1,...,0,0,1)` | `chirpCfg 0 0 0 0 0 0 0 1` / `chirpCfg 1 1 0 0 0 0 0 4` | ✅ TX0 / TX2 |
| `FrameConfig(0,1,0,255,100,0,0,1)` | `frameCfg 0 1 255 0 100 1 0` | ✅ 255 loops、无限帧、100ms |
| `LPModConfig(0,0)` | `lowPower 0 0` | ✅ |
| `CaptureCardConfig_Mode/PacketDelay/EthInit` | `cf.json`(lvdsMode2、fmt3、delay5、IP/端口) | ✅ |

**新构建/无 cfg 单行对应(已报告)**:`sensorStop`/`flushCfg`/`dfeDataOutputMode 1`(mmw_demo CLI 框架);`adcbufCfg -1 0 1 1 1` 与 `lvdsStreamCfg -1 0 1 0`(等价替换 lua 的 `DataPathConfig`/`LvdsClkConfig`/`LVDSLaneConfig`)。lua 的 `DownloadBSSFw`/`DownloadMSSFw`/`RfInit` 等是**机制**,纯 Python 用 flash 固件替代——**而这正是相位相干性差异的来源**。

## 修复路径

**真正的修法 = 复刻 Studio:用 SPI/FTDI 把同一套 `rf_eval` `radarss.bin`+`masterss.bin` 装进 RAM**,而非用 flash 的 studio_cli 固件。
- 参考 `gaoweifan/pyRadar`:AWR mmwavelink-over-SPI(固件下载 + Profile/Chirp/Frame 配置 + StartFrame)。1843 当 2243 用。
- 跨平台:`pyftdi`(Linux/Mac/Windows),符合最终上 Ubuntu 的目标。
- 这是唯一能拿到与 Studio **相位级一致**数据的路。

低成本预试(长线希望不大):往 cfg 加 `calibMonCfg 1 1` 等校准命令,重抓静止场景看裙边是否收窄。

## 副作用问题(独立于竖线)
- **丢包**:`[mmWave] Packet lost!` 频繁——采集线程被主线程(ViTPose+FFT+渲染)经 GIL 抢占。会丢帧伤质量,但**不是竖线成因**(已用静止帧一致性排除)。

---
*分析脚本:`scratchpad/` 下 `static_compare.py`(决定性)、`comb_period.py`、`doppler_comb.py`、`per_frame_skirt.py`、`hi_contrast.py` 等*
