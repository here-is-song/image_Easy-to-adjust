# image_easy-to-adjust (IEA)

这是一个面向 Windows 的桌面和命令行工具，用于打开 TIFF/OME-TIFF、Olympus `.oib` 和 Bitplane Imaris `.ims` 显微镜文件，并把指定通道和 Z 范围导出为论文制图用 TIFF 或 PNG。当前支持 OIB 自动建立同名 IMS 缓存、单文件和批量处理、可调预览、比例尺、导出尺寸/DPI 与可复现导出记录；不包含 3D 渲染。

当前版本为 `v0.3.0`，详细变化请参阅 [CHANGELOG.md](CHANGELOG.md)。

桌面界面默认使用黑灰色主题：主背景为 `#2A2A2A`，控件和面板为 `#3D3D3F`，菜单及深层区域为 `#232324`。文字、边框、悬停、选中、禁用、滑块、滚动条和进度条颜色均针对深色背景进行了配套调整；该主题只改变软件界面，不会改变预览数据或导出图像的颜色。

## 安装

需要 Python 3.11 或更高版本。在项目目录运行：

```powershell
python -m pip install -e .
```

安装后可使用 `iea` 命令运行 CLI，或使用 `iea-gui` 启动桌面窗口。根目录的 `python main.py` 和 BAT 启动方式继续兼容。

如需打开 OIB 并生成 IMS 缓存，请安装额外的 Bio-Formats 和官方 ImarisWriter 依赖：

```powershell
python -m pip install -e ".[oib]"
```

也可以运行 `python -m pip install -r requirements-oib.txt`。第一次读取 OIB 时，Bio-Formats 会下载约 189 MiB 的完整 Java 11 JDK 和所需 Java libraries，因此会比后续打开更慢。IEA 会在 Windows 中文安装路径下把很小的 JPype bridge 镜像到 ASCII 临时目录，原始 OIB 不会被移动。`bioio-bioformats` 使用 GPL-3.0 许可证；在分发包含该组件的程序前，请一并检查其许可证要求。

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

`IEA.spec` 已收集当前 OIB 运行时和 ImarisWriter 的 Python 模块、数据文件与本地库，但不同电脑上的 Java/Bio-Formats 首次启动仍应单独做一次真实 OIB 验证。

## OIB → IMS 缓存工作流

从 GUI 的 `File > Open Microscopy Files` 可以同时选择 `.oib` 和 `.ims` 文件。打开 `sample.oib` 时，IEA 只在同一文件夹检查 basename 完全相同、扩展名大小写不敏感的 `sample.ims`：

- 同名 IMS 有效：直接使用 IMS，不读取 OIB 像素、不运行 Auto Display、不改写缓存，并保留 IMS 已有的通道颜色、Min、Max 和 Gamma。
- 没有同名 IMS：使用 Bio-Formats 分块读取 OIB，逐通道估计显示范围，再由官方 PyImarisWriter 写入 `sample.ims.tmp`；只有写入完成后才原子重命名为 `sample.ims`。
- 同名 IMS 损坏：安全回退到原 OIB，并报告缓存无效；初版不会自动覆盖损坏的 IMS。
- 直接打开 IMS：不寻找 OIB，也不运行 Auto Display。

OIB 始终只读。第一次转换后的当前会话继续使用 Bio-Formats 数据集，下一次打开才优先使用 IMS 缓存。GUI 中读取、分析和写入在后台线程运行，并显示 `Reading OIB...`、`Analyzing display range...`、`Creating IMS...` 等进度。

软件内部使用统一的 `ImageDataset / ImageSession`，预览、比例尺、Z-stack、图像导出只访问格式无关的分块接口。IMS 是持久缓存和 Imaris 兼容格式，不是应用内部数据模型；`ImageSession` 已为未来的 segmentation、ROI 和 measurement layer 预留空集合，本版本没有实现这些分析功能。

首次 OIB 转换会逐通道执行 Imaris-like Auto Display：均匀抽取最多 32 个 Z 平面和有限数量 XY 像素；Min 使用对零峰、坏点和极端值有保护的第一个显著直方图 mode，失败时记录日志并回退到 P0.5；Max 使用采样 P99.8；Gamma 为 `1.0`。这些值只是显示映射，写入 IMS 的仍是未归一化、未缩放、未转换类型的原始 voxel。

## TIFF / OME-TIFF 读取

GUI 和 CLI 可直接打开 `.tif` 和 `.tiff`，支持单层灰度、RGB、普通多页 Z-stack，以及常见的多通道 OME-TIFF。TIFF 不会被转换为 IMS 缓存，原文件始终只读。程序优先读取 OME `PhysicalSizeX/Y/Z`，其次读取标准 TIFF `XResolution/YResolution/ResolutionUnit` 或 ImageJ 标定。缺少可靠的 X/Y 标定时不会猜测比例尺，可用 `File > Edit Image Metadata…` 手动填写实际视野宽高。

大多数普通 TIFF 不包含完整显微镜字段；此时 IEA 会使用实验流程默认值 `Olympus MVX10`、`MV PLAPO 2XC`、`Zoom 1.25X`，并在界面警告中提醒导出前核对。如果 OME-TIFF 已明确记录其他显微镜或物镜，则优先使用文件自身信息。当前读取第一个 TIFF image series；不含原生金字塔的 TIFF 会把该 series 载入内存，因此超大文件需要留意内存占用。

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

比例尺默认开启，使用 X 方向体素尺寸计算。自动长度最接近图像物理宽度的 15%，候选从 1 µm 扩展到 50 mm。长度达到 1000 µm 时会自动改用 mm 显示，例如 `1000 µm` 写为 `1 mm`、`1500 µm` 写为 `1.5 mm`。

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

- 导出始终使用 `ResolutionLevel 0`；交互预览会按屏幕实际像素需求自动选择 IMS 金字塔层级。当前仍只使用 `TimePoint 0`，多时间点文件会显示警告。
- OIB 初版使用第一个 Bio-Formats scene；多 scene 文件会显示警告。
- OIB 转 IMS 目前只接受官方 PyImarisWriter 原生支持的 `uint8`、`uint16` 和 `float32`；其他类型不会被静默转换或归一化。
- 多层 OIB 如果缺少可靠的 PhysicalSizeZ，或任何 OIB 缺少 PhysicalSizeX/Y，将停止创建科学尺度不可靠的 IMS；缺失 metadata 保持为 `None`，不会猜测。
- Bio-Formats 能读取但官方 ImarisWriter 标准字段无法表达的厂商私有 metadata，会保留在当前运行时 metadata 中，但不会私自写入未知 IMS HDF5 字段。
- 仓库不提交真实 OIB 实验数据；自动测试使用合成后端，并额外通过官方 ImarisWriter 写入/IMSReader 读回验证原始体素和显示 metadata。本地真实样本已完成逐 voxel 验证。
- 只做 Maximum Intensity Projection。
- 支持 NumPy 可识别的整数和浮点图像数据；主要目标是常见的 `uint8`、`uint16`。
- 需要 `DataSetInfo/Image` 中可靠的物理 extent 才能生成科学上正确的比例尺。
- 如果 X/Y/Z 尺寸相同，HDF5 dataset 的轴顺序可能无法仅靠 shape 唯一判定；程序会明确警告并优先采用常见的 Z/Y/X 存储顺序。真实样本应通过 `--structure` 核对。

## 测试

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest
```

真实 OIB 建议按以下方式验收：先备份样本并确认同目录没有同名 IMS，运行 `python main.py "D:\data\sample.oib"` 或从 GUI 打开；观察四个阶段和同目录新建的 IMS。记录 OIB 的文件大小、修改时间和校验值，确认转换前后完全一致；关闭后再次打开同一个 OIB，确认状态显示 `Using existing IMS cache` 且不再分析 histogram。最后分别在 IEA 和 Imaris Viewer 中检查尺寸、通道名称/颜色、Min/Max/Gamma、比例尺，并抽查几个 T/C/Z/Y/X 坐标的原始强度。

## GUI（Milestone 5）

安装依赖后，不带参数运行即可启动桌面界面：

```powershell
python main.py
```

Windows 下推荐双击项目目录中的 `image_easy-to-adjust.lnk` 启动；该快捷方式使用 `IEA.ico` 图标并调用 `image_easy-to-adjust.bat`。旧的 `图像处理.bat` 作为兼容入口保留。

菜单栏末尾的 `Help > Open GitHub Repository` 会在默认浏览器中打开项目仓库；`Help > About IEA` 显示软件版本、作者与 Codex 协作说明、联系邮箱和源代码地址。

`File > Edit Image Metadata…` 用于非破坏地修正当前文件的物理标定。实际像素宽高、Z 层数、通道数和数据类型由存储数据决定，因此保持只读；可以单独覆盖物理视野宽度、物理视野高度和 Z spacing，程序会自动换算 X/Y 的 µm/pixel。修正会按源文件路径记忆，并用于 Preview 比例尺、物镜辅助判断、最终导出、PPT 摘要和 Fiji OME-TIFF。点击 `Use Source Metadata` 可恢复源文件记录值。IEA 不会写回或修改原始 IMS/OIB；`export_info.json` 会同时记录 source、effective 和 manual correction，便于追溯。

界面支持打开 IMS、查看 metadata、选择通道和 1-based Z 范围、修改每个通道的 Display Min/Max/Gamma、切换 Merge/单通道预览、自动或手动比例尺，以及红色转品红色。`Channels` 中通道名称旁的复选框控制该通道是否参与处理；菜单栏的 `Output Images` 是本次导出图片清单，按 `Three-color Merge`、`Two-color Merge` 和 `Single-color` 分类列出所有可选通道组合，每项都可以独立勾选。勾选子选项后菜单会保持展开，便于连续选择；鼠标移出整个菜单和子菜单区域后自动收起。一次导出可以同时生成多个不同 Merge 和指定单通道图，例如同时勾选红+蓝、绿+红、绿+红+蓝和绿色单通道；相同清单会按通道名称应用到所有批量文件。每张 Merge 使用包含通道名称的文件名，例如 `sample_Merge_Green_Red.tif`。Preview 下拉框会列出当前选中的各张 Merge，方便逐一检查。每个通道的 Min、Max 和 Gamma 都同时提供精确数值框与横向滑块；任一方式调整后都会触发受刷新频率限制的预览更新。Gamma 范围与 Imaris 一致，为 `0.1–5.0`。预览和导出都在后台线程运行，避免大文件计算时冻结界面。

每个通道名称旁的颜色色块可以点击，打开 RGB 颜色选择器。手动选择的颜色会立即用于预览和最终导出，批量处理时与 Min/Max/Gamma 一样按通道名称匹配。手动 RGB 被视为最终颜色，不再受 `Convert red to magenta` 二次转换；如果为单通道 TIFF 选择了自定义颜色，该文件会输出为 RGB TIFF，以保证与预览一致。

当 IMS 没有记录通道颜色时，程序会识别常用染料名称：`Alexa Fluor 488` 使用绿色、`Alexa Fluor 594` 使用红色、`DRAQ5` 使用蓝色。`Channels` 模块底部的 `Convert red to magenta` 开启时，会把红色通道转换为品红色，并同时作用于预览和导出；关闭后保持原始红色。IMS 读取警告显示在窗口左下方，并用四个空格连接为单行，鼠标悬停时也可查看完整内容。

预览默认使用 `Merge: Selected Channels`，并始终跟随 `Channels` 中当前勾选的通道：三个通道显示三色 Merge，两个通道显示对应双色 Merge，只剩一个通道时仍显示该通道的伪彩色图像而不是灰度图。该默认预览独立于 `Output Images` 导出清单。预览渲染器会读取 IMS 中可用的 `ResolutionLevel`：缩小时使用足以覆盖屏幕像素的较低层级，放大后自动切换到更高层级，避免把低分辨率缩略图机械放大。预览区提供“−”“+”“100%”“Fit”和“0°”按钮。鼠标滚轮、“−”“+”“100%”和“Fit”只改变屏幕上的 View 缩放，用于查看细节，不进入导出参数；左键拖动平移也仅影响屏幕查看。`Output size` 数值框是独立的输出缩放，会同时作用于 Preview 与最终导出：放大以图像中心为基准并裁掉超出边界的部分，缩小时用黑色补足画布。右键拖动和 `Rotation` 数值框会改变 Preview 与导出旋转，旋转会扩展画布以保留整幅图像。“0°”用于重置旋转；按 `Ctrl+B` 可恢复 View 100%、输出旋转 0° 并重新居中，不会改动 `Output size`。状态标签会分别显示 View 与 Output 百分比。

左侧参数区域和右侧 Preview 区域之间有一条竖向分隔线。按住分隔线并左右拖动，可以随时调整两部分的宽度占比；两侧都设有最小宽度，不会被意外完全折叠。

左侧的 `Batch Files`、`Channels`、`Z Range` 和 `Scale Bar` 都是可折叠分组。点击分组标题或标题旁的箭头即可展开或收起；每个分组的状态会立即保存，关闭并重新打开软件后仍保持上次的展开状态。

修改通道、Z 范围、显示范围、颜色或比例尺等参数后，预览会自动刷新。菜单栏的 `Preview > Refresh Limit` 子菜单用于限制刷新频率，可选择每秒最多 2 次、每秒最多 1 次、每 2 秒一次、每 5 秒一次或 `Paused`；默认每秒最多 1 次。`Paused` 只暂停自动刷新，仍可用 `Refresh Preview` 手动刷新。短时间内连续修改多个参数时，程序会合并这些变化，避免同时启动多个预览计算。每次自动或手动刷新完成时，当前视图旋转会被固化到新预览，比例尺随后重新放在右下角；仅用鼠标旋转而不刷新时，比例尺会继续跟随图像旋转。

### Cell Counting Plugin Demo

打开显微镜文件后，可从 `Analysis > Cell Counting Plugin Demo` 启动计数 Demo。它采用“分割一次、测量多通道”的工作流：检测通道用于生成一张整数标签图，`0` 是背景，`1、2、3…` 分别代表细胞；随后在同一批细胞区域内测量所有勾选通道的归一化平均/最大强度，并按平均强度阈值给出每个通道的阳性数量和阳性率。程序会优先把名称含 `DRAQ`、`DAPI`、`Hoechst`、`Nucleus`、`Nuclei` 或 `DNA` 的通道自动选作检测通道，也允许手动选择一个或多个检测输入通道。

ROI 支持 `Full image`、`Automatic foreground rectangle` 和 `Manual rectangle`。手动模式既可填写相对原图的 X/Y/Width/Height 百分比，也可直接在对话框中的预览图上按住左键拖画矩形；ROI 最终以相对原图坐标保存并用于 Level 0 数据。结果窗口提供青色细胞边界、黄色中心点、橙色 ROI、通道汇总和逐细胞结果，并可导出带 UTF-8 BOM 的 CSV，方便 Excel 打开。

当前内置的 `Threshold + connected components (Demo)` 使用 Otsu/手动阈值、简单形态清理、连通域和面积过滤，不会可靠拆分互相接触的细胞，因此必须检查 Overlay，尚不能代替经过验证的科研分析流程。插件接口要求分割器返回与 Cellpose 相同语义的整数 label image；以后接入 Cellpose 时，只需增加新的 `iea.cell_counting` entry point，ROI、通道测量、阳性分类、表格和 CSV 不需要重写。

### Fiji Bridge

`Analysis > Fiji Bridge > Open Selected Data in Fiji` 会把当前文件、`Channels` 中勾选的原始通道和当前 Z 范围流式写入临时 OME-TIFF，再交给独立的 Fiji 进程打开。通道名称、X/Y 像素尺寸和 Z 间距会写入 OME metadata；IEA 的 Display Min/Max/Gamma 不会烧入原始强度。这样可以在 Fiji 中使用其完整菜单、ROI 工具和已安装插件，同时避免 Fiji 的 Java/Swing 环境干扰 IEA 读取 OIB 所使用的 Java 进程。

IEA 会记住 Fiji 安装目录，并会自动检查用户目录及 Windows 各磁盘下的 `Fiji/Fiji.app`。如果没有找到，或以后移动了 Fiji，请使用 `Analysis > Fiji Bridge > Configure Fiji Installation`，选择包含 `fiji-windows-x64.exe` 的 `Fiji.app` 文件夹。桥接文件保存在系统临时目录的 `image_easy-to-adjust/fiji-bridge` 子目录；它是分析用副本，不会修改原始 IMS/OIB。

基础桥接不需要另装 Fiji 插件。安装其他插件时，优先在 Fiji 中选择 `Help > Update… > Manage update sites`，勾选插件要求的 update site，关闭列表后选择 `Apply changes` 并重启 Fiji。没有 update site 的 `.jar` 插件可以使用 `Plugins > Install Plugin…`，或复制到 `Fiji.app/plugins` 后重启。IEA 目前负责把数据交给 Fiji；在 Fiji 中保存的结果不会自动覆盖或导回 IEA。

菜单栏的 `File > Open Microscopy Files` 可一次选择一个或多个 IMS/OIB 文件。程序会记住最近一次成功打开显微镜文件的文件夹，下次打开文件选择窗口时从该文件夹开始；如果文件夹已不存在，则使用系统默认位置。文件会显示在左侧 `Batch Files` 列表中，当前选中行用于 Preview；自动预览只计算这一张，避免批量文件同时刷新。每个文件会在软件当前运行期间分别缓存通道勾选、颜色、Min/Max/Gamma、输出组合、Z 范围、比例尺、物镜选择以及 Preview 的图像、缩放、旋转和滚动位置；在列表中切换后再切回时会直接恢复，关闭软件后释放，不修改原图。每个文件的 `Process` 和 `Export` 默认都勾选：取消 `Process` 会同时取消导出，重新勾选 `Export` 会自动恢复 `Process`。`Batch` 菜单可批量全选或清空这两列。当前界面参数会统一应用到所有最终勾选导出的文件；文件的 Z 层数较少时，程序会自动限制到该文件的有效范围。

批量处理时，通道和 Display Min/Max/Gamma 会优先按通道名称匹配，而不是直接套用通道编号。因此，即使不同文件中的通道排列顺序不同，参数仍会应用到同名通道。遇到缺失或重名通道时，程序会显示警告并跳过无法可靠匹配的项。

TIFF/OME-TIFF 与 IMS/OIB 一样可从 `File > Open Microscopy Files` 批量选择，也会记住最近一次成功打开文件的文件夹。

### FV1200 物镜自动识别

打开 IMS 后，`Objective` 折叠分组会显示自动检测结果、NA、浸液类型、Z spacing、XY FOV、来源和置信度。检测顺序为：原文件明确记录的物镜信息优先；多层文件其次使用标准化 Z voxel depth；单层文件或 Z 证据无效时，使用图片像素尺寸、物理比例（µm/pixel）和 ScanZoom 计算 `长轴物理视野 × ScanZoom`，再与实验室 FV1200 的 ScanZoom 1.0 视野校准比较。仅有 `512 × 512` 或 `1024 × 1024` 等像素尺寸、没有物理比例或 ScanZoom 时不会猜测物镜。相对误差不超过 3% 为 High，3%–7% 为 Medium，超过 7% 不自动确认；候选过于接近时会降低置信度或要求手动确认。Z spacing 与 XY FOV 结论冲突时仍保留优先级更高的 Z 结果，但降为 Medium 并提示手动核对。

`Objective` 下拉菜单包含 `Auto`、`10X`、`20X`、`30X`、`60X` 和 `Unknown`。手动选择只覆盖本次处理和导出，不修改原始 IMS；自动检测结果与最终选择会分别写入 `export_info.json`，其中也包含实测 XY FOV、ScanZoom、归一化 FOV 和 XY 相对误差。固定物镜参数集中保存在 `iea/fv1200_calibration.py`。当前 XY 基准来自已知 20X、ScanZoom 1.0 文件的 635.9045 µm 视野，并按物镜倍率反比得到其余初始值；以后取得各物镜的标准图后，可直接逐项替换 `expected_fov_um` 进行独立校准。

`Export > Export Image Settings` 会打开导出设置窗口，可调整最终宽度、高度、DPI、TIFF/PNG 格式、保存文件夹、宽高比策略，以及是否在导出后把合并图复制到系统剪贴板。宽高比策略包括保留比例并留边（Fit）、拉伸（Stretch）和保留比例后裁剪（Crop）。GUI 默认设置为 `1000 × 1000 px`、`300 DPI`、TIFF 和 Fit；保存位置留空时使用每个源 IMS 文件旁的默认导出目录。导出设置和 `Preview > Refresh Limit` 会在修改时保存，关闭并重新打开程序后仍保持上次状态。

`Export > Export Images` 用于执行导出，快捷键为 `Ctrl+C`。导出过程中窗口底部会显示进度；可以点击 `Cancel`，程序会在当前文件处理完成后停止，并保留此前已经成功导出的文件。启用 `Copy merged image to Clipboard after export` 后，导出完成时会把合并图复制到剪贴板；批量导出时复制最后一张成功导出的合并图。如果本次只选择单通道输出、没有生成 Merge，程序会跳过剪贴板复制并明确提示。各通道图和合并图仍会正常保存到文件夹中。

比例尺可在界面中启用或关闭，并可选择自动长度或手动长度。GUI 默认使用 `Bar thickness: 10 px` 和 `Text size: 50 px`；两个字段仍可手动修改，设为 `Auto` 时则由程序自动计算。程序会按字体的实际边界移动文字和比例尺，防止大字号文字超出图像；请求字号大到无法容纳时，会自动使用能够完整显示的最大字号。比例尺会同时出现在预览和最终导出图中；标签会根据长度自动使用 `µm` 或 `mm`。

CLI 示例：

```powershell
python main.py sample.ims --channel 0 --merge --format png --scale-bar-thickness-px 6 --scale-bar-font-size-px 28
```

## 导出记录（Milestone 6）

每次图像导出会在同一输出文件夹额外生成 `export_info.json`，记录输出格式、像素尺寸、DPI、缩放倍率、旋转角度、源文件、Z 范围及物理位置、投影方式、比例尺及其粗细和文字大小、红转品红设置、每个通道实际使用的 Min/Max/Gamma、原始/输出颜色、所有单通道及 Merge 通道组合和输出文件路径。CLI 与 GUI 都会生成该记录；CLI 可使用 `--zoom 1.5 --rotation 30` 指定 150% 中心放大和顺时针 30° 旋转。

每个源文件还会生成一个 `<源文件名>_PPT_summary.txt`，用于直接复制到 PowerPoint。IMS/OIB 工作流程使用 `Olympus FV1200`；缺少仪器 metadata 的 TIFF 使用 `Olympus MVX10`、`MV PLAPO 2XC` 和 `Zoom 1.25X`。如果 OME-TIFF 已明确记录其他仪器，会使用文件中的值。程序会读取原始采集日期和像素扫描速度。对于多层文件，结合所选 Z 范围计算导出堆栈厚度；对于只有一个 Z 层的文件，摘要只写 `single-layer image`。无法可靠识别的字段会显示为 `Not available`，不会根据文件名猜测。单文件 GUI 导出完成后，摘要内容也会直接显示在完成提示中。

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
  plugins/
    cell_counting/    可替换的细胞分割插件接口、注册表与阈值 Demo
  settings_store.py   GUI 设置的读取和保存
  batch.py            批量文件的通道匹配
  fv1200_calibration.py  FV1200 固定物镜 calibration profile
  objective_detector.py 独立物镜检测与手动覆盖逻辑
  image_dataset.py     统一 ImageDataset / ImageSession 和分块像素接口
  dataset_loader.py    IMS/OIB/TIFF 统一加载与 OIB 缓存流程
  tiff_backend.py      TIFF/OME-TIFF 轴、通道和物理标定读取
  bioformats_reader.py Bio-Formats OIB lazy/block reader
  java_runtime.py      Windows Java/JPype 中文路径兼容层
  ims_backend.py       现有 IMSReader 的统一后端适配器
  imaris_writer.py     官方 PyImarisWriter 流式写入适配器
  auto_display.py      逐通道采样直方图与 Imaris-like Auto Display
  memory_backend.py    测试和未来生成数据层使用的内存后端
  ims_reader.py       IMS 读取与分块 MIP
  exporter.py         渲染与导出流程
tests/                 自动化测试
main.py                兼容旧启动方式的入口
pyproject.toml          安装、命令入口和构建配置
IEA.spec                Windows 单文件程序打包配置
```
