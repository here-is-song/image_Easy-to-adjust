# IMS Publication Figure Exporter

这是一个面向 Windows 的桌面和命令行工具，用于检查 Bitplane Imaris `.ims` 文件，并把指定通道和 Z 范围导出为论文制图用 TIFF 或 PNG。当前已完成需求文档的 Milestone 1–6；不包含批处理或 3D 渲染。

## 安装

需要 Python 3.11 或更高版本。在项目目录运行：

```powershell
python -m pip install -r requirements.txt
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

计算顺序固定为：原始强度 → 所选 Z 范围的 Maximum Intensity Projection → Display Adjustment。单通道始终是灰度图，不应用通道伪彩。

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

默认输出格式为 TIFF。GUI 可以在“Output”区域选择 TIFF 或 PNG；CLI 可通过 `--format tif` 或 `--format png` 选择格式。

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

界面支持打开 IMS、查看 metadata、选择通道和 1-based Z 范围、修改每个通道的 Display Min/Max、切换 Merge/单通道预览、自动或手动比例尺，以及红色转品红色。预览和导出都在后台线程运行，避免大文件计算时冻结界面。

预览区提供“−”“+”“100%”和“Fit”按钮，可缩小、放大、按原始预览尺寸显示或适应窗口。这里的缩放只改变屏幕显示，不会改变最终导出的像素尺寸和图像内容。

修改通道、Z 范围、显示范围、颜色或比例尺等参数后，预览会自动刷新。`Refresh limit` 下拉菜单用于限制刷新频率，可选择每秒最多 2 次、每秒最多 1 次、每 2 秒一次或每 5 秒一次；默认每秒最多 1 次。短时间内连续修改多个参数时，程序会合并这些变化，避免同时启动多个预览计算。

比例尺可在界面中启用或关闭，并可选择自动长度或手动长度。`Bar thickness` 和 `Text size` 设为 `Auto` 时由程序自动计算，也可输入像素值。比例尺会同时出现在预览和最终导出图中。

CLI 示例：

```powershell
python main.py sample.ims --channel 0 --merge --format png --scale-bar-thickness-px 6 --scale-bar-font-size-px 28
```

## 导出记录（Milestone 6）

每次图像导出会在同一输出文件夹额外生成 `export_info.json`，记录输出格式、源文件、Z 范围及物理位置、投影方式、比例尺及其粗细和文字大小、红转品红设置、每个通道实际使用的显示范围、原始/输出颜色和输出文件路径。CLI 与 GUI 都会生成该记录。
