# 更新日志

本文件记录 image_easy-to-adjust（IEA）的重要功能更新与修复。

## 未发布

### 新增功能

- 新增 Olympus OIB 打开与同目录、同 basename IMS 持久缓存工作流；已有有效 IMS 时完全跳过 OIB 像素读取和 Auto Display。
- 新增格式无关的 `ImageDataset / ImageSession`、Bio-Formats lazy/block 后端、IMS 后端适配器和 Memory 后端，为后续格式及分析模块保留统一接口。
- 新增逐通道 Imaris-like Auto Display：第一个显著 histogram mode、P99.8 和 Gamma 1.0，采用有上限的 Z/XY 采样且不修改原始 voxel。
- 接入官方 PyImarisWriter，以分块方式写入原始像素、物理尺度、通道名称/颜色及 Min/Max/Gamma；临时文件完成后再原子重命名。
- OIB 转换使用 GUI 后台 worker，支持批量选择、进度显示、取消和安全错误清理。
- 新增 IMS 多分辨率预览；缩放时会根据屏幕像素需求自动选择合适的 `ResolutionLevel`。
- 新增预览鼠标交互：滚轮缩放、左键拖动平移、右键拖动二维旋转，以及 `Ctrl+B` 恢复正常大小和角度。
- 新增可扩展的细胞计数插件接口和 `Threshold + connected components (Demo)`，支持多检测/测量通道、全图/自动/手动画框 ROI、细胞标签 Overlay、阳性统计和 CSV 导出，并为后续 Cellpose 插件复用统一 label image 约定。
- 新增外部 Fiji Bridge：将当前勾选通道和 Z 范围流式导出为保留原始强度与物理标定的 OME-TIFF，再由独立 Fiji 进程打开。
- Fiji Bridge 支持自动发现及记忆 Fiji 安装目录、后台进度和安全取消；无需把 Fiji 移入项目或与 IEA 共用 Java 进程。
- `File > Edit Image Metadata` 支持按文件非破坏地修正物理视野宽高和 Z spacing，自动换算 µm/pixel，并同步作用于比例尺、物镜辅助判断、导出、PPT 摘要和 Fiji 标定。

### 界面与交互改进

- 预览状态会显示实际使用的金字塔层级；屏幕缩放、平移和旋转不会改变最终导出内容。
- `Analysis` 菜单新增细胞计数 Demo 和 Fiji Bridge，Fiji 安装位置可在菜单中重新指定。
- 细胞计数结果窗口同时显示细胞边界、中心点、ROI、各通道阳性汇总和逐细胞测量结果。
- 手动物理标定会按源文件路径记忆，可一键恢复源 metadata；导出记录同时保存 source、effective 和 manual correction。

### 安全与兼容性

- 损坏的同名 IMS 会安全回退到 OIB，且不会自动覆盖损坏缓存。
- OIB 原文件始终只读；转换失败会删除临时 IMS。
- IMSReader 支持识别并裁剪官方 ImarisWriter 的 HDF5 chunk padding，同时保留逻辑图像尺寸。
- 增加 OIB 缓存 A–E、自动显示、统一数据集、流式写入及官方 writer 逐体素往返测试。

### 修复

- 修复 Bio-Formats 默认下载精简 JRE、缺少 `jar.exe` 而无法首次初始化的问题；现在默认使用完整 Java 11 JDK。
- 修复 Windows 项目路径包含中文时，JPype 本地库无法被 JVM 加载的问题；仅将 Java bridge 镜像到 ASCII 临时目录，原始 OIB 不移动。
- 修复 Bio-Formats JVM 与 PyImarisWriter 多线程同时存在时，单层 OIB 可能长期停留在 IMS finalize 的问题；缓存 writer 默认使用稳定的单线程模式。
- 预览默认使用当前启用通道的彩色 Merge；调整 Channels 后会自动切换为对应三色、双色或单通道伪彩色预览，不再意外退回灰度图。

### 验证

- 使用真实三通道 IMS 样本验证 Fiji OME-TIFF 桥接、通道顺序和物理标定。
- 自动化测试扩展至 101 项，全部通过。

## v0.3.0 - 2026-08-20

### 新增功能

- 新增黑灰色桌面主题，并为文字、菜单、按钮、滑块、滚动条、进度条和禁用状态适配深色界面。
- 新增 `Output Images` 菜单，可按三色合并、双色合并和单色图片连续选择多个输出组合，并支持批量文件。
- 新增 FV1200 单层图像物镜辅助识别：在 Z spacing 无法使用时，可结合 XY 物理视野、像素尺寸和 ScanZoom 进行判断。
- 新增 `Help` 菜单，可打开项目 GitHub 仓库并查看 IEA 版本、用途、作者和联系方式。
- 记住最近一次成功打开 IMS 文件的文件夹，下次从该位置开始选择文件。
- 为缺少颜色 metadata 的 `Alexa Fluor 488`、`Alexa Fluor 594` 和 `DRAQ5` 提供稳定的绿色、红色和蓝色映射。

### 界面与交互改进

- `Output Images` 子菜单支持连续勾选，并在鼠标移出菜单区域后收起。
- 将 `Convert red to magenta` 移至 `Channels` 模块底部；开关同时影响预览和最终导出。
- IMS metadata 警告移至窗口左下方，以四个空格连接为单行，并通过悬停提示显示完整内容。
- 比例尺默认粗细改为 `10 px`、文字大小改为 `50 px`。
- 比例尺会根据实际文字边界自动调整位置和字号，避免文字超出图像。
- 物镜信息区域增加 XY FOV、ScanZoom、归一化视野、判断来源和置信度显示。

### 导出与记录改进

- 支持一次导出多个自定义单通道和 Merge 通道组合，并在文件名中记录实际合并的通道名称。
- 多个输出组合复用已经计算的通道投影，避免重复读取和计算同一通道。
- `export_info.json` 增加单通道清单、Merge 组合、XY FOV 和物镜识别依据等记录。
- PPT 摘要中的显微镜统一为 `Olympus FV1200`。
- 原文件只有一个 Z 层时，PPT 摘要显示 `single-layer image`，不再输出 Z 间隔和堆栈厚度。
- 只导出单通道图片时，剪贴板复制会明确跳过，而不是误报已复制 Merge 图片。

### 修复

- 修复批量文件中通道顺序不一致时 Display Min、Max 和 Gamma 可能匹配错误的问题。
- 修复较大 Scale Bar 字号可能导致文字被图像边界裁切的问题。
- 修复切换 IMS 文件后 `Convert red to magenta` 选项可能从 Channels 模块消失的问题。
- 修复 Alexa Fluor 594 在缺少颜色 metadata 时直接记录为品红色的问题；现在原始颜色保持红色，仅在转换开关开启时显示和导出为品红色。

### 发布与验证

- 项目版本升级至 `0.3.0`。
- 生成 Windows x64 单文件程序、ZIP 分享包、Python wheel 和源码包，同时保留 `v0.2.0` 本地安装包。
- 完整自动化测试共 75 项，全部通过。
