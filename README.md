# image_easy-to-adjust (IEA)

IEA 是一个面向 Windows 的显微图像查看、调整和批量导出工具，支持 Bitplane Imaris `.ims`、Olympus `.oib` 以及 TIFF/OME-TIFF 文件。项目由 Song Xuanyu 根据自己的科研工作流和实际使用习惯开发，并在 Codex 协助下持续完善。

> **使用范围说明**
>
> 本项目目前主要供作者自用，功能和默认值与作者自己的科研工作流相符，并不是面向所有显微镜、实验室或分析流程的通用解决方案。自动显示范围、物镜识别、仪器信息补全、细胞计数 Demo 和 PPT 摘要都可能不适用于其他数据。请在正式使用、分享图片或引用结果前，逐项核对原始 metadata、比例尺、通道、显示范围和导出文件。IEA 不用于临床诊断，也不能替代经过验证的科研分析软件或人工判断。

当前版本为 `0.3.0`。版本变化见 [CHANGELOG.md](CHANGELOG.md)。

## 主要功能

### 文件读取与数据处理

- 打开 IMS、OIB、TIFF 和 OME-TIFF；GUI 支持一次选择多个文件。
- 读取图像尺寸、物理像素尺寸、Z 层、通道名称、通道颜色以及可用的显示范围和 Gamma。
- IMS 预览可根据窗口所需像素自动选择已有的 `ResolutionLevel`；最终导出仍读取最高分辨率数据。
- OIB 通过 Bio-Formats 读取，并可在源文件旁创建同名 IMS 缓存，以加快后续打开速度。
- TIFF 支持常见的灰度、RGB、多页 Z-stack 和多通道 OME-TIFF；当前只读取第一个 image series。
- 在指定 Z 范围内执行 Maximum Intensity Projection（MIP）。Z 数据按块读取，避免一次加载完整 Z-stack。
- 当前只处理 `TimePoint 0`；多时间点文件会显示提示。

### 通道与显示调整

- 按通道调整 Display Min、Max 和 Gamma；数值框和滑块同步更新预览。
- 点击通道色块可设置自定义 RGB 颜色，预览和导出使用同一颜色。
- 支持把红色通道转换为品红；可关闭该选项以保留红色。
- 支持单色、双色、三色及自定义通道组合，并可在一次操作中导出多个组合。
- 单通道 PNG 默认按通道颜色输出；为单通道 TIFF 设置自定义颜色时，会输出 RGB TIFF 以保留颜色。
- 缺少颜色信息时，可按已知染料名称为 `Alexa Fluor 488`、`Alexa Fluor 594` 和 `DRAQ5` 提供绿色、红色和蓝色后备值；这些映射仍需人工确认。

### 预览与图像变换

- 黑灰色桌面界面，参数区与 Preview 区之间可拖动分隔条。
- 鼠标滚轮、`+`、`-`、`100%` 和 `Fit` 只改变屏幕查看倍率，不影响导出。
- 左键拖动平移预览；查看倍率和位置只是临时视图状态。
- `Output size` 是独立的输出缩放，会同时反映在预览和最终导出中。
- 右键拖动或输入角度可旋转图像；旋转会影响最终导出，并扩展画布以保留完整图像。
- `Ctrl+B` 恢复 100% 查看倍率、居中预览并把输出旋转重置为 0°，但不修改 `Output size`。
- 可设置 Preview 刷新频率上限或暂停自动刷新；刷新后比例尺重新定位到右下角。

### 比例尺与导出

- 比例尺可关闭、自动选择长度或手动指定长度。
- 可调整线条粗细和文字大小；GUI 默认值为 `10 px` 和 `50 px`。
- 标签根据长度自动使用 `µm` 或 `mm`，并尽量保证完整文字位于图像内。
- 导出格式可选 TIFF 或 PNG，可设置宽度、高度、DPI 和保存位置。
- 宽高比策略包括 Fit（留边）、Stretch（拉伸）和 Crop（裁剪）。
- 支持把最后一张成功生成的合并图复制到剪贴板。
- 导出时显示进度并可取消；取消前已完成的文件会保留。
- 已存在的输出文件不会静默覆盖，而会追加编号。
- `Ctrl+C` 是执行导出的快捷键，不是普通的复制快捷键。

### 批量处理与状态记忆

- 可同时打开多个文件，选择处理和导出的文件集合。
- 通道显示参数、颜色和通道组合按通道名称匹配到批量文件。
- 同一程序会话中，切换文件后会保留各文件已经调整的状态。
- 导出尺寸、DPI、格式、目录、Preview 刷新限制、折叠面板状态、上次打开目录和 Fiji 路径等 GUI 设置会保存到 Qt 本地设置中。
- 批量导出以当前界面设置为基础应用到所选文件。通道命名或采集条件不同的文件应逐一检查，不能假设自动匹配一定正确。

### Metadata、仪器辅助信息与导出记录

- `File > Edit Image Metadata…` 可在 IEA 内非破坏性地修正物理视野宽高和 Z spacing；不会改写源 IMS/OIB/TIFF。
- 每次导出生成 `export_info.json`，记录源文件、输出文件、Z 范围、通道参数、颜色、图像变换、比例尺和相关 metadata。
- 每个源文件还会生成 `<文件名>_PPT_summary.txt`，方便整理到 PowerPoint；单层图像写为 `single-layer image`。
- IMS/OIB 工作流中的显微镜摘要默认按作者的 Olympus FV1200 流程处理；缺少仪器信息的普通 TIFF 可使用 Olympus MVX10、MV PLAPO 2XC、Zoom 1.25X 的个人流程后备值。
- FV1200 物镜辅助判断可综合文件 metadata、Z spacing、像素尺寸、比例尺、ScanZoom 和个人校准视野。它是经验性提示，不是可靠的物镜自动识别；冲突、低置信度或其他实验室数据必须手动确认。

### 实验性分析与 Fiji 桥接

- 内置可替换的细胞计数插件接口，以及一个阈值/连通区域 Demo。
- Demo 支持多通道检测、矩形 ROI、Otsu 或手动阈值、面积过滤、边缘对象排除、标记阳性判断、结果叠加预览和逐细胞 CSV。
- 该 Demo 主要用于验证界面、ROI、测量和未来 Cellpose 接口，尚未经过生物学计数验证，也不是 Cellpose。
- 可把当前选择的原始通道和 Z 范围临时写成 OME-TIFF 并在外部 Fiji 中打开。Fiji 自身插件由 Fiji 管理，IEA 不承诺兼容所有 ImageJ/Fiji 插件。

## 安装与启动

需要 Python 3.11 或更高版本。建议在虚拟环境中安装：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
```

启动 GUI：

```powershell
python main.py
```

安装后也可以使用：

```powershell
iea-gui
```

项目中的 `image_easy-to-adjust.bat` 和旧版兼容入口 `图像处理.bat` 也可以启动程序。快捷方式或 BAT 的图标显示受 Windows 对脚本和快捷方式的限制，应用窗口使用项目中的 `IEA.ico`。

### OIB 额外依赖

读取 OIB 和生成 IMS 缓存需要 Bio-Formats 与 PyImarisWriter：

```powershell
python -m pip install -e ".[oib]"
```

也可以安装 `requirements-oib.txt`。首次使用 Bio-Formats 时可能下载 Java 和相关库，因此需要网络连接、额外磁盘空间，并可能明显慢于后续启动。分发带有这些依赖的程序前，请自行核对各第三方组件的许可证。

## OIB 与 IMS 缓存行为

打开 `example.oib` 时，IEA 会在同一目录查找 `example.ims`：

1. 同名 IMS 有效：直接使用已有 IMS，不重新读取 OIB 像素或计算 Auto Display。
2. 没有同名 IMS：分块读取 OIB，估计显示范围，写入 `example.ims.tmp`，成功后再改名为 `example.ims`。
3. 同名 IMS 无效：回退到 OIB 并显示警告；程序不会自动覆盖损坏的 IMS。

源 OIB 以只读方式访问，但创建缓存会在源文件夹写入体积可能很大的 IMS 文件。当前首次转换完成后的会话仍使用 Bio-Formats 数据，下一次打开才优先使用 IMS 缓存。

OIB 的 Auto Display 通过有限 Z/XY 采样估计 histogram mode、P99.8 和 Gamma 1.0。它只影响显示映射，不改变原始体素；它是近似策略，不保证与 Imaris 或显微镜软件的自动显示完全一致。

## 命令行示例

只查看 metadata：

```powershell
python main.py "D:\data\example.ims"
```

导出第 1–20 层的两个单通道和合并 PNG：

```powershell
python main.py "D:\data\example.ims" `
  --channel 0 --channel 1 --merge `
  --z-start 1 --z-end 20 `
  --format png `
  --output-dir "D:\data\example_export"
```

添加手动比例尺、输出缩放和旋转：

```powershell
python main.py "D:\data\example.ims" `
  --channel 0 --merge `
  --scale-bar-um 50 `
  --scale-bar-thickness-px 10 `
  --scale-bar-font-size-px 50 `
  --zoom 1.5 --rotation 30
```

CLI 通道编号从 0 开始，Z 范围从 1 开始且首尾都包含。`--zoom` 表示写入输出图像的中心缩放，不是 GUI 中仅用于查看的滚轮缩放。完整选项请运行：

```powershell
python main.py --help
```

## 输出文件

未指定输出位置时，程序通常在源文件旁创建 `<源文件名>_Export` 文件夹，例如：

```text
example_Export/
  example_Channel_1.tif
  example_Merge_Channel_1_Channel_2.tif
  example_PPT_summary.txt
  export_info.json
```

实际文件名由通道名称和所选组合决定，Windows 文件名不允许的字符会替换为 `_`。

## 数据与隐私

- IEA 没有遥测、账户登录或云端上传功能，图像处理默认在本机完成。
- 安装依赖、Bio-Formats 首次准备 Java，以及用户主动打开 GitHub 时可能访问网络。
- `export_info.json` 可能包含源文件和输出文件的**绝对路径**、通道名、采集参数、仪器信息和人工修正值；分享前请先检查并按需删减。
- Fiji 桥接会把所选原始强度数据写入系统临时目录中的 OME-TIFF。共享电脑上使用时，应注意临时文件可能保留实验数据。
- `.gitignore` 已忽略常见 IMS/OIB/TIFF/PNG、导出目录和导出记录，但这不能替代提交前运行 `git status` 并人工检查。
- 不要把真实实验数据、受试者信息、实验编号、私人路径、账号凭据、API key 或访问令牌提交到公开仓库。

## 已知限制

- 当前只提供二维 MIP，不提供正交切片、体绘制或完整 3D 交互。
- 只使用 `TimePoint 0`；OIB 当前只使用第一个 Bio-Formats scene，TIFF 只读取第一个 image series。
- 不含原生金字塔的 TIFF 可能把整个 series 加载到内存，超大文件可能占用较多内存。
- 导出使用最高分辨率数据；大图、多 Z 层、多通道、多输出组合和旋转会增加时间与内存占用。
- 缺少可靠物理尺寸时，比例尺无法保证正确。手动 metadata 修正只保存在 IEA 本地，不会修复源文件。
- 轴尺寸相同或 metadata 不完整时，存储轴顺序可能存在歧义，程序会给出警告；应使用已知样本核对方向和尺寸。
- OIB 转 IMS 只接受 PyImarisWriter 原生支持的数据类型；程序不会静默归一化不支持的数据。
- FV1200 校准、MVX10 后备 metadata、染料颜色和 PPT 摘要都与作者的个人流程有关，不应直接作为其他数据的事实依据。
- 请只打开可信来源的显微图像文件，并保留原始数据备份。

## 测试与打包

安装开发依赖并运行自动测试：

```powershell
python -m pip install -e ".[dev]"
python -m pytest
```

测试主要使用合成数据、mock 后端和小型临时文件，覆盖核心读取、显示、导出、GUI 设置、计数接口和缓存逻辑；测试通过不代表所有厂商文件、采集设置或科研结论都已验证。新增真实格式时，建议在 IEA、原厂软件和 Fiji/Imaris 中交叉核对尺寸、方向、通道、体素值和比例尺。

构建 Python 包：

```powershell
python -m pip install -e ".[dev]"
python -m build
```

构建 Windows 单文件程序：

```powershell
python -m pip install -e ".[package]"
pyinstaller --clean IEA.spec
```

PyInstaller 输出位于 `dist`。由于 Java、Bio-Formats、PyImarisWriter 和不同电脑环境较复杂，发布前仍应在一台没有开发环境的 Windows 电脑上测试 IMS、TIFF、OIB 和 Fiji 桥接。

## 项目结构

```text
iea/
  cli.py                    CLI 入口
  gui.py                    GUI 启动入口
  gui_window.py             主窗口与交互
  gui_dialogs.py            设置、metadata、ROI 和结果对话框
  gui_workers.py            后台读取、预览、导出和 Fiji 任务
  settings_store.py         GUI 设置保存
  dataset_loader.py         IMS/OIB/TIFF 统一加载
  image_dataset.py          统一数据集和会话接口
  ims_backend.py            IMS 后端
  bioformats_reader.py      OIB/Bio-Formats 后端
  tiff_backend.py           TIFF/OME-TIFF 后端
  imaris_writer.py          IMS 缓存写入
  auto_display.py           OIB 显示范围估计
  exporter.py               MIP、渲染和导出
  objective_detector.py     物镜辅助判断
  fv1200_calibration.py     个人 FV1200 校准参数
  fiji_bridge.py            Fiji OME-TIFF 桥接
  plugins/cell_counting/    计数插件接口与阈值 Demo
tests/                      自动测试
main.py                     兼容启动入口
pyproject.toml              安装和构建配置
IEA.spec                    Windows 打包配置
```

## 项目关系与贡献

IEA 不是 Olympus、Evident、Imaris、Bitplane、Fiji、ImageJ 或 Cellpose 的官方项目，也未获得这些项目或公司的认可。相关名称只用于说明文件兼容性和工作流程。

项目按 Song Xuanyu 的个人需求维护，不应预期长期兼容性、技术支持或特定功能路线。若要报告问题，请在 GitHub Issue 中使用可公开的最小复现信息，不要上传真实实验数据或包含个人信息的日志。

## 许可证

仓库目前没有 `LICENSE` 文件。源代码可被公开查看并不等同于已经授予复制、修改或分发许可。若以后希望接受外部使用或贡献，应先选择合适的开源许可证，并同时核对 Bio-Formats、PyImarisWriter、Qt/PySide6 等第三方依赖的许可证和分发条件。
