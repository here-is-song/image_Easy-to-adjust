# image_easy-to-adjust (IEA)

这是一个面向 Windows 的桌面和命令行工具，用于检查 Bitplane Imaris `.ims` 文件，并把指定通道和 Z 范围导出为论文制图用 TIFF 或 PNG。当前支持单文件和批量处理、可调预览、比例尺、导出尺寸/DPI 与可复现导出记录；不包含 3D 渲染。

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

程序会显示图像尺寸、体素尺寸、Z 层数、时间点、数据类型，以及每个通道的名称、颜色和 `ColorRange`。通道编号从 `0` 开始，与 IMS 内部的 `Channel 0`、`Channel 1` 一致。

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

计算顺序固定为：原始强度 → 所选 Z 范围的 Maximum Intensity Projection → Display Adjustment。MIP 会按 Z 轴分块读取，因此不需要把完整 Z 堆栈一次性载入内存。单通道始终是灰度图，不应用通道伪彩。

`ColorRange` 代表 Imaris Display Adjustment 的最小值和最大值。它只改变导出的显示图，不修改 IMS 或原始强度。如果文件没有保存有效 `ColorRange`，工具会明确警告，并使用所选原始 Z 数据的 min/max。

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

只合并指定通道，并同时生成这些通道的灰度 TIFF：

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

界面支持打开 IMS、查看 metadata、选择通道和 1-based Z 范围、修改每个通道的 Display Min/Max、切换 Merge/单通道预览、自动或手动比例尺，以及红色转品红色。预览和导出都在后台线程运行，避免大文件计算时冻结界面。

预览区提供“−”“+”“100%”和“Fit”按钮，可缩小、放大、按原始预览尺寸显示或适应窗口。这里的缩放只改变屏幕显示，不会改变最终导出的像素尺寸和图像内容。

左侧参数区域和右侧 Preview 区域之间有一条竖向分隔线。按住分隔线并左右拖动，可以随时调整两部分的宽度占比；两侧都设有最小宽度，不会被意外完全折叠。

修改通道、Z 范围、显示范围、颜色或比例尺等参数后，预览会自动刷新。菜单栏的 `Preview > Refresh Limit` 子菜单用于限制刷新频率，可选择每秒最多 2 次、每秒最多 1 次、每 2 秒一次或每 5 秒一次；默认每秒最多 1 次。短时间内连续修改多个参数时，程序会合并这些变化，避免同时启动多个预览计算。

菜单栏的 `File > Open IMS Files` 可一次选择一个或多个 IMS 文件。文件会显示在左侧 `Batch Files` 列表中，当前选中行用于 Preview；自动预览只计算这一张，避免批量文件同时刷新。每个文件的 `Process` 和 `Export` 默认都勾选：取消 `Process` 会同时取消导出，重新勾选 `Export` 会自动恢复 `Process`。`Batch` 菜单可批量全选或清空这两列。当前界面参数会统一应用到所有最终勾选导出的文件；文件的 Z 层数较少时，程序会自动限制到该文件的有效范围。

批量处理时，通道和 Display Range 会优先按通道名称匹配，而不是直接套用通道编号。因此，即使不同文件中的通道排列顺序不同，参数仍会应用到同名通道。遇到缺失或重名通道时，程序会显示警告并跳过无法可靠匹配的项。

`Export > Export Image Settings` 会打开导出设置窗口，可调整最终宽度、高度、DPI、TIFF/PNG 格式、保存文件夹、宽高比策略，以及是否在导出后把合并图复制到系统剪贴板。宽高比策略包括保留比例并留边（Fit）、拉伸（Stretch）和保留比例后裁剪（Crop）。GUI 默认设置为 `1000 × 1000 px`、`300 DPI`、TIFF 和 Fit；保存位置留空时使用每个源 IMS 文件旁的默认导出目录。导出设置和 `Preview > Refresh Limit` 会在修改时保存，关闭并重新打开程序后仍保持上次状态。

`Export > Export Images` 用于执行导出，快捷键为 `Ctrl+C`。导出过程中窗口底部会显示进度；可以点击 `Cancel`，程序会在当前文件处理完成后停止，并保留此前已经成功导出的文件。启用 `Copy merged image to Clipboard after export` 后，导出完成时会把合并图复制到剪贴板；批量导出时复制最后一张成功导出的合并图。各通道图和合并图仍会正常保存到文件夹中。

比例尺可在界面中启用或关闭，并可选择自动长度或手动长度。`Bar thickness` 和 `Text size` 设为 `Auto` 时由程序自动计算，也可输入像素值。比例尺会同时出现在预览和最终导出图中。

CLI 示例：

```powershell
python main.py sample.ims --channel 0 --merge --format png --scale-bar-thickness-px 6 --scale-bar-font-size-px 28
```

## 导出记录（Milestone 6）

每次图像导出会在同一输出文件夹额外生成 `export_info.json`，记录输出格式、像素尺寸、DPI、源文件、Z 范围及物理位置、投影方式、比例尺及其粗细和文字大小、红转品红设置、每个通道实际使用的显示范围、原始/输出颜色和输出文件路径。CLI 与 GUI 都会生成该记录。

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
  ims_reader.py       IMS 读取与分块 MIP
  exporter.py         渲染与导出流程
tests/                 自动化测试
main.py                兼容旧启动方式的入口
pyproject.toml          安装、命令入口和构建配置
IEA.spec                Windows 单文件程序打包配置
```
