"""Command-line entry point for microscopy inspection and image export."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .dataset_loader import DatasetLoaderError, open_microscopy_dataset
from .exporter import (
    export_channels_and_merge,
    export_merge,
    export_single_channels,
    write_export_info,
    write_ppt_summary,
)
from .image_dataset import ImageDatasetError
from .ims_reader import IMSReaderError
from .models import (
    ExportSettings,
    ImageOutputSettings,
    IMSMetadata,
    ScaleBarSettings,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Inspect an OIB/IMS microscopy file and export publication image projections."
    )
    parser.add_argument("ims_file", type=Path, nargs="?", help="Path to a source .ims or .oib file")
    parser.add_argument(
        "--structure",
        action="store_true",
        help="Also print the recursive HDF5 structure and attributes",
    )
    parser.add_argument(
        "--channel",
        type=int,
        action="append",
        dest="channels",
        help="0-based channel index to export independently; repeat to select multiple channels",
    )
    parser.add_argument(
        "--merge",
        action="store_true",
        help="Export an RGB merge (all channels unless --channel is supplied)",
    )
    parser.add_argument("--z-start", type=int, default=1, help="First Z slice, 1-based and inclusive")
    parser.add_argument(
        "--z-end",
        type=int,
        help="Last Z slice, 1-based and inclusive (default: final slice)",
    )
    parser.add_argument("--output-dir", type=Path, help="Output directory")
    parser.add_argument(
        "--scale-bar-um",
        type=float,
        help="Use this scale-bar length in um instead of automatic selection",
    )
    parser.add_argument("--no-scale-bar", action="store_true", help="Do not draw a scale bar")
    parser.add_argument(
        "--format",
        choices=("tif", "png"),
        default="tif",
        dest="output_format",
        help="Output image format (default: tif)",
    )
    parser.add_argument(
        "--scale-bar-thickness-px",
        type=int,
        help="Scale-bar line thickness in full-resolution output pixels (default: auto)",
    )
    parser.add_argument(
        "--scale-bar-font-size-px",
        type=int,
        help="Scale-bar text size in full-resolution output pixels (default: auto)",
    )
    parser.add_argument(
        "--keep-red",
        action="store_true",
        help="Keep red channel colors instead of converting red-like colors to magenta",
    )
    return parser


def print_metadata(metadata: IMSMetadata) -> None:
    print(f"File: {metadata.source_path}")
    print(f"Image size: {metadata.size_x} × {metadata.size_y} × {metadata.size_z} (X × Y × Z)")
    voxel_text = " × ".join(
        f"{value:.6g}" if value is not None else "N/A"
        for value in (
            metadata.voxel_size_x_um,
            metadata.voxel_size_y_um,
            metadata.voxel_size_z_um,
        )
    )
    print(f"Voxel size: {voxel_text} um")
    print(f"Data type: {metadata.dtype}")
    print(f"Time points: {metadata.time_point_count} (TimePoint 0 is used)")
    objective = metadata.objective_detection
    if objective is not None and objective.objective_key is not None:
        print(f"Objective: {objective.objective_key} — {objective.model}")
        print(f"Objective detection: {objective.detection_source}, {objective.confidence} confidence")
    else:
        print("Objective: Unknown (manual selection required)")
    if objective is not None and objective.warning:
        print(f"Objective warning: {objective.warning}", file=sys.stderr)
    print(f"Channels: {metadata.channel_count}")
    for channel in metadata.channels:
        display_range = (
            f"{channel.display_min:.6g}–{channel.display_max:.6g}"
            if channel.display_min is not None and channel.display_max is not None
            else "not stored (selected data min/max fallback)"
        )
        color = ", ".join(f"{component:.3g}" for component in channel.color)
        print(f"  [{channel.index}] {channel.name}")
        print(f"      Color: ({color})")
        print(f"      ColorRange: {display_range}")
        print(f"      GammaCorrection: {channel.display_gamma:.6g}")
        print(f"      Dataset axes: {', '.join(channel.axis_order)}")
    for warning in metadata.warnings:
        print(f"Warning: {warning}", file=sys.stderr)


def run(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.ims_file is None:
        try:
            from .gui import launch_gui
        except ImportError as exc:
            print(
                "GUI dependencies are missing. Run: python -m pip install -r requirements.txt",
                file=sys.stderr,
            )
            print(f"Reason: {exc}", file=sys.stderr)
            return 1
        return launch_gui()
    try:
        with open_microscopy_dataset(
            args.ims_file,
            progress=lambda _fraction, phase: print(phase, file=sys.stderr),
        ) as session:
            reader = session.dataset
            if reader.metadata is None:
                raise ImageDatasetError("Microscopy metadata could not be read.")
            metadata = reader.metadata
            print_metadata(metadata)
            if args.structure:
                inspect_structure = getattr(getattr(reader, "backend", None), "reader", None)
                if inspect_structure is None or not hasattr(inspect_structure, "inspect_hdf5_structure"):
                    raise ImageDatasetError("--structure is available only when the active backend is IMS.")
                print("\nHDF5 structure:")
                print(inspect_structure.inspect_hdf5_structure())

            export_requested = bool(args.channels) or args.merge
            if not export_requested:
                return 0
            channels = tuple(dict.fromkeys(args.channels or range(metadata.channel_count)))
            settings = ExportSettings(
                z_start=args.z_start,
                z_end=args.z_end if args.z_end is not None else metadata.size_z,
                channel_indices=channels,
                red_to_magenta=not args.keep_red,
                scale_bar=ScaleBarSettings(
                    enabled=not args.no_scale_bar,
                    length_um=args.scale_bar_um,
                    thickness_px=args.scale_bar_thickness_px,
                    font_size_px=args.scale_bar_font_size_px,
                ),
                output=ImageOutputSettings(format=args.output_format),
            )
            results = []
            if args.channels and args.merge:
                results.extend(export_channels_and_merge(reader, settings, args.output_dir))
            elif args.channels:
                results.extend(export_single_channels(reader, settings, args.output_dir))
            elif args.merge:
                results.append(export_merge(reader, settings, args.output_dir))
            info_path = write_export_info(reader, settings, results, args.output_dir)
            summary_path = write_ppt_summary(reader, settings, args.output_dir)
            print("\nExport completed:")
            for result in results:
                scale = f", scale bar {result.scale_bar_um:g} um" if result.scale_bar_um else ""
                print(f"  {result.path} — shape {result.shape}, dtype {result.dtype}{scale}")
            print(f"  {info_path} - export settings record")
            print(f"  {summary_path} - PPT acquisition summary")
            print("\nPPT summary:")
            print(summary_path.read_text(encoding="utf-8"))
            return 0
    except (DatasetLoaderError, ImageDatasetError, IMSReaderError, OSError, ValueError) as exc:
        print("Unable to process microscopy file.", file=sys.stderr)
        print(f"Reason: {exc}", file=sys.stderr)
        return 1


def main() -> int:
    """Console-script entry point."""

    return run()


if __name__ == "__main__":
    raise SystemExit(main())
