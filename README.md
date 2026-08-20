# image_easy-to-adjust (IEA)

这是一个面向 Windows 的桌面和命令行工具，用于检查 Bitplane Imaris `.ims` 文件，并把指定通道和 Z 范围导出为论文制图用 TIFF 或 PNG。当前支持单文件和批量处理、可调预览、比例尺、导出尺寸/DPI 与可复现导出记录；不包含 3D 渲染。

当前版本为 `v0.3.0`，详细变化请参阅 [CHANGELOG.md](CHANGELOG.md)。

桌面界面默认使用黑灰色主题：主背景为 `#2A2A2A`，控件和面板为 `#3D3D3F`，菜单及深层区域为 `#232324`。文字、边框、悬停、选中、禁用、滑块、滚动条和进度条颜色均针对深色背景进行了配套调整；该主题只改变软件界面，不会改变预览数据或导出图像的颜色。

## 安装

需要 Python 3.11 或更高版本。在项目目录运行：

```powershell
python -m pip install -e .
```

安装后可使用 `iea` 命令运行 CLI，或使用 `iea-gui` 启动桌面窗口。根目录的 `python main.py` 和 BAT 启动方式继续兼容。

构建 Python wheel/source package：

```powershell
python -m pip install -e ".[dev]"
python -m build
```

构建带 `IEA.ico` 的 Windows 单文件程序：

```powershell
python -m pip install -e ".[package]"
pyinstaller --clean IEA.spec
```

## Milestone 1：检查 IMS metadata

```powershell
python main.py D:\data\sample.ims
```

程序会显示图像尺寸、体素尺寸、Z 层数、时间点、数据类型，以及每个通道的名称、颜色、`ColorRange` 和 `GammaCorrection`。通道编号从 `0` 开始，与 IMS 内部的 `Channel 0`、`Channel 1` 一致。

需要诊断未知 IMS 结构时，可额外打印所有 group、dataset 和 attribute：

```powershell
python main.py D:\data\sample.ims --structure
```

## Milestone 2：单通道 MIP TIFF

以下命令读取第 1–20 层（用户输入为 1-based、首尾都包含），导出 `Channel 0` 的 8-bit 灰度 TIFF：

```powershell
python main.py D:\data\sample.ims --channel 0 --z-start 1 --z-end 20
```

可重复使用 `--channel` 同时导出多个单通道文件：

```powershell
python main.py D:\data\sample.ims --channel 0 --channel 2 --z-start 10 --z-end 40
```

计算顺序固定为：原始强度 → 所选 Z 范围的 Maximum Intensity Projection → Display Adjustment。MIP 会按 Z 轴分块读取，因此不需要把完整 Z 堆栈一次性载入内存。单通道 TIFF 保持 8-bit 灰度；单通道 PNG 默认使用 IMS 中该通道的对应颜色，并遵守红色转品红色设置。

`ColorRange` 代表 Imaris Display Adjustment 的最小值和最大值，`GammaCorrection` 代表同一通道的 Gamma。工具会读取这三个原始显示参数，并同时用于预览和最终导出；它们只改变显示图，不修改 IMS 或原始强度。如果文件没有保存有效 `ColorRange`，工具会明确警告并使用所选原始 Z 数据的 min/max；如果 Gamma 缺失或无效，则使用线性值 `1.0`。

## Milestone 3：比例尺

比例尺默认开启，使用 X 方向体素尺寸计算。自动长度最接近图像物理宽度的 15%，候选为 1、2、5、10、20、50、100、200、500、1000 µm。

指定 50 µm 或关闭比例尺：

```powershell
python main.py D:\data\sample.ims --channel 0 --scale-bar-um 50
python main.py D:\data\sample.ims --channel 0 --no-scale-bar
```

比例尺为白色、右下角、文字位于横线上方。字体依次尝试 Arial、Segoe UI 和 Pillow 默认字体。

## Milestone 4：Merge

合并所有通道：

```powershell
python main.py D:\data\sample.ims --merge --z-start 1 --z-end 30
```

只合并指定通道，并同时生成这些通道的独立 TIFF：

```powershell
python main.py D:\data\sample.ims --channel 0 --channel 1 --merge --z-start 1 --z-end 30
```

Merge 使用 IMS 保存的 RGB 颜色做 additive merge，最后 clip 到 0–255。红色或接近红色的通道默认转换为品红色；添加 `--keep-red` 可保留原颜色。

## 输出

默认输出格式为 TIFF。GUI 可以在 `Export > Export Image Settings` 窗口选择 TIFF 或 PNG；CLI 可通过 `--format tif` 或 `--format png` 选择格式。

默认目录位于源 IMS 同级：

```text
sample_Export/
  sample_CD31.tif
  sample_RUNX1.tif
  sample_Merge.tif
  sample_PPT_summary.txt
  export_info.json
```

也可使用 `--output-dir D:\figures` 指定目录。非法 Windows 文件名字符会替换为 `_`。为避免破坏之前的科研图片，已有输出不会被静默覆盖，而会自动添加 `_2`、`_3` 等后缀。源 `.ims` 始终以只读方式打开。

## 当前限制

- 只使用 `ResolutionLevel 0` 和 `TimePoint 0`；多时间点文件会显示警告。
- 只做 Maximum Intensity Projection。
- 支持 NumPy 可识别的整数和浮点图像数据；主要目标是常见的 `uint8`、`uint16`。
- 需要 `DataSetInfo/Image` 中可靠的物理 extent 才能生成科学上正确的比例尺。
- 如果 X/Y/Z 尺寸相同，HDF5 dataset 的轴顺序可能无法仅靠 shape 唯一判定；程序会明确警告并优先采用常见的 Z/Y/X 存储顺序。真实样本应通过 `--structure` 核对。

## 测试

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest
```

## GUI（Milestone 5）

安装依赖后，不带参数运行即可启动桌面界面：

```powershell
python main.py
```

Windows 下推荐双击项目目录中的 `image_easy-to-adjust.lnk` 启动；该快捷方式使用 `IEA.ico` 图标并调用 `image_easy-to-adjust.bat`。旧的 `图像处理.bat` 作为兼容入口保留。

菜单栏末尾的 `Help > Open GitHub Repository` 会在默认浏览器中打开项目仓库；`Help > About IEA` 显示软件版本、作者与 Codex 协作说明、联系邮箱和源代码地址。

界面支持打开 IMS、查看 metadata、选择通道和 1-based Z 范围、修改每个通道的 Display Min/Max/Gamma、切换 Merge/单通道预览、自动或手动比例尺，以及红色转品红色。`Channels` 中通道名称旁的复选框控制该通道是否参与处理；菜单栏的 `Output Images` 是本次导出图片清单，按 `Three-color Merge`、`Two-color Merge` 和 `Single-color` 分类列出所有可选通道组合，每项都可以独立勾选。勾选子选项后菜单会保持展开，便于连续选择；鼠标移出整个菜单和子菜单区域后自动收起。一次导出可以同时生成多个不同 Merge 和指定单通道图，例如同时勾选红+蓝、绿+红、绿+红+蓝和绿色单通道；相同清单会按通道名称应用到所有批量文件。每张 Merge 使用包含通道名称的文件名，例如 `sample_Merge_Green_Red.tif`。Preview 下拉框会列出当前选中的各张 Merge，方便逐一检查。每个通道的 Min、Max 和 Gamma 都同时提供精确数值框与横向滑块；任一方式调整后都会触发受刷新频率限制的预览更新。Gamma 范围与 Imaris 一致，为 `0.1–5.0`。预览和导出都在后台线程运行，避免大文件计算时冻结界面。

当 IMS 没有记录通道颜色时，程序会识别常用染料名称：`Alexa Fluor 488` 使用绿色、`Alexa Fluor 594` 使用红色、`DRAQ5` 使用蓝色。`Channels` 模块底部的 `Convert red to magenta` 开启时，会把红色通道转换为品红色，并同时作用于预览和导出；关闭后保持原始红色。IMS 读取警告显示在窗口左下方，并用四个空格连接为单行，鼠标悬停时也可查看完整内容。

预览区提供“−”“+”“100%”和“Fit”按钮，可缩小、放大、按原始预览尺寸显示或适应窗口。这里的缩放只改变屏幕显示，不会改变最终导出的像素尺寸和图像内容。

左侧参数区域和右侧 Preview 区域之间有一条竖向分隔线。按住分隔线并左右拖动，可以随时调整两部分的宽度占比；两侧都设有最小宽度，不会被意外完全折叠。

左侧的 `Batch Files`、`Channels`、`Z Range` 和 `Scale Bar` 都是可折叠分组。点击分组标题或标题旁的箭头即可展开或收起；每个分组的状态会立即保存，关闭并重新打开软件后仍保持上次的展开状态。

修改通道、Z 范围、显示范围、颜色或比例尺等参数后，预览会自动刷新。菜单栏的 `Preview > Refresh Limit` 子菜单用于限制刷新频率，可选择每秒最多 2 次、每秒最多 1 次、每 2 秒一次或每 5 秒一次；默认每秒最多 1 次。短时间内连续修改多个参数时，程序会合并这些变化，避免同时启动多个预览计算。

菜单栏的 `File > Open IMS Files` 可一次选择一个或多个 IMS 文件。程序会记住最近一次成功打开 IMS 的文件夹，下次打开文件选择窗口时从该文件夹开始；如果文件夹已不存在，则使用系统默认位置。文件会显示在左侧 `Batch Files` 列表中，当前选中行用于 Preview；自动预览只计算这一张，避免批量文件同时刷新。每个文件的 `Process` 和 `Export` 默认都勾选：取消 `Process` 会同时取消导出，重新勾选 `Export` 会自动恢复 `Process`。`Batch` 菜单可批量全选或清空这两列。当前界面参数会统一应用到所有最终勾选导出的文件；文件的 Z 层数较少时，程序会自动限制到该文件的有效范围。

批量处理时，通道和 Display Min/Max/Gamma 会优先按通道名称匹配，而不是直接套用通道编号。因此，即使不同文件中的通道排列顺序不同，参数仍会应用到同名通道。遇到缺失或重名通道时，程序会显示警告并跳过无法可靠匹配的项。

### FV1200 物镜自动识别

打开 IMS 后，`Objective` 折叠分组会显示自动检测结果、NA、浸液类型、Z spacing、XY FOV、来源和置信度。检测顺序为：原文件明确记录的物镜信息优先；多层文件其次使用标准化 Z voxel depth；单层文件或 Z 证据无效时，使用图片像素尺寸、物理比例（µm/pixel）和 ScanZoom 计算 `长轴物理视野 × ScanZoom`，再与实验室 FV1200 的 ScanZoom 1.0 视野校准比较。仅有 `512 × 512` 或 `1024 × 1024` 等像素尺寸、没有物理比例或 ScanZoom 时不会猜测物镜。相对误差不超过 3% 为 High，3%–7% 为 Medium，超过 7% 不自动确认；候选过于接近时会降低置信度或要求手动确认。Z spacing 与 XY FOV 结论冲突时仍保留优先级更高的 Z 结果，但降为 Medium 并提示手动核对。

`Objective` 下拉菜单包含 `Auto`、`10X`、`20X`、`30X`、`60X` 和 `Unknown`。手动选择只覆盖本次处理和导出，不修改原始 IMS；自动检测结果与最终选择会分别写入 `export_info.json`，其中也包含实测 XY FOV、ScanZoom、归一化 FOV 和 XY 相对误差。固定物镜参数集中保存在 `iea/fv1200_calibration.py`。当前 XY 基准来自已知 20X、ScanZoom 1.0 文件的 635.9045 µm 视野，并按物镜倍率反比得到其余初始值；以后取得各物镜的标准图后，可直接逐项替换 `expected_fov_um` 进行独立校准。

`Export > Export Image Settings` 会打开导出设置窗口，可调整最终宽度、高度、DPI、TIFF/PNG 格式、保存文件夹、宽高比策略，以及是否在导出后把合并图复制到系统剪贴板。宽高比策略包括保留比例并留边（Fit）、拉伸（Stretch）和保留比例后裁剪（Crop）。GUI 默认设置为 `1000 × 1000 px`、`300 DPI`、TIFF 和 Fit；保存位置留空时使用每个源 IMS 文件旁的默认导出目录。导出设置和 `Preview > Refresh Limit` 会在修改时保存，关闭并重新打开程序后仍保持上次状态。

`Export > Export Images` 用于执行导出，快捷键为 `Ctrl+C`。导出过程中窗口底部会显示进度；可以点击 `Cancel`，程序会在当前文件处理完成后停止，并保留此前已经成功导出的文件。启用 `Copy merged image to Clipboard after export` 后，导出完成时会把合并图复制到剪贴板；批量导出时复制最后一张成功导出的合并图。如果本次只选择单通道输出、没有生成 Merge，程序会跳过剪贴板复制并明确提示。各通道图和合并图仍会正常保存到文件夹中。

比例尺可在界面中启用或关闭，并可选择自动长度或手动长度。GUI 默认使用 `Bar thickness: 10 px` 和 `Text size: 50 px`；两个字段仍可手动修改，设为 `Auto` 时则由程序自动计算。程序会按字体的实际边界移动文字和比例尺，防止大字号文字超出图像；请求字号大到无法容纳时，会自动使用能够完整显示的最大字号。比例尺会同时出现在预览和最终导出图中。

CLI 示例：

```powershell
python main.py sample.ims --channel 0 --merge --format png --scale-bar-thickness-px 6 --scale-bar-font-size-px 28
```

## 导出记录（Milestone 6）

每次图像导出会在同一输出文件夹额外生成 `export_info.json`，记录输出格式、像素尺寸、DPI、源文件、Z 范围及物理位置、投影方式、比例尺及其粗细和文字大小、红转品红设置、每个通道实际使用的 Min/Max/Gamma、原始/输出颜色、所有单通道及 Merge 通道组合和输出文件路径。CLI 与 GUI 都会生成该记录。

每个 IMS 文件还会生成一个 `<源文件名>_PPT_summary.txt`，用于直接复制到 PowerPoint。PPT 摘要中的显微镜名称固定为实验室实际使用的 `Olympus FV1200`；原始 IMS 记录的厂家和型号仍保留在 `export_info.json`。程序会读取原始采集日期和像素扫描速度，物镜使用 GUI 最终选择（Auto 或手动覆盖）。对于多层 IMS，Z 间隔使用本次检测所采用的标准化 voxel depth，并结合所选 Z 范围计算导出堆栈厚度；对于原文件本身只有一个 Z 层的 IMS，摘要只写 `single-layer image`，不显示 Z 间隔或堆栈厚度。无法可靠识别的字段会显示为 `Not available`，不会根据文件名猜测。单文件 GUI 导出完成后，摘要内容也会直接显示在完成提示中。

```text
Date: 260806
Microscope: Olympus FV1200
Scan speed: 10 μsecond/pixel, Size: 1024×1024
Objective lens: Uplansapo 10X (N.A.0.40), Z-sectioning interval: 4.77 μm, Z-stack thickness: 18 μm;
```

## 项目结构

```text
iea/
  cli.py              命令行入口
  gui.py              GUI 公共入口
  gui_window.py       主窗口和界面交互
  gui_dialogs.py      设置对话框
  gui_workers.py      后台预览与导出任务
  settings_store.py   GUI 设置的读取和保存
  batch.py            批量文件的通道匹配
  fv1200_calibration.py  FV1200 固定物镜 calibration profile
  objective_detector.py 独立物镜检测与手动覆盖逻辑
  ims_reader.py       IMS 读取与分块 MIP
  exporter.py         渲染与导出流程
tests/                 自动化测试
main.py                兼容旧启动方式的入口
pyproject.toml          安装、命令入口和构建配置
IEA.spec                Windows 单文件程序打包配置
```
