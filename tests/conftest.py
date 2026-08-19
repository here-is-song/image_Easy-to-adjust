from __future__ import annotations

from pathlib import Path

import h5py
import numpy as np
import pytest


@pytest.fixture
def sample_ims(tmp_path: Path) -> Path:
    path = tmp_path / "sample.ims"
    with h5py.File(path, "w") as h5_file:
        image = h5_file.create_group("DataSetInfo/Image")
        image.attrs["X"] = np.bytes_("5")
        image.attrs["Y"] = np.bytes_("4")
        image.attrs["Z"] = np.bytes_("3")
        image.attrs["ExtMin0"] = np.bytes_("0")
        image.attrs["ExtMax0"] = np.bytes_("2.5")
        image.attrs["ExtMin1"] = np.bytes_("0")
        image.attrs["ExtMax1"] = np.bytes_("4")
        image.attrs["ExtMin2"] = np.bytes_("0")
        image.attrs["ExtMax2"] = np.bytes_("6")
        image.attrs["Unit"] = np.bytes_("um")
        image.attrs["RecordingDate"] = np.bytes_("2026-08-06 12:34:56")
        image.attrs["ManufactorString"] = np.bytes_("Olympus")
        image.attrs["ManufactorModel"] = np.bytes_("FV1200")
        image.attrs["ObjectiveName"] = np.bytes_("Uplansapo")
        image.attrs["LensPower"] = np.bytes_("10")
        image.attrs["NumericalAperture"] = np.bytes_("0.40")

        acquisition = h5_file.create_group("DataSetInfo/Olympus Acquisition Parameters Common")
        acquisition.attrs["SamplingClock"] = np.bytes_("100000")
        acquisition.attrs["ZoomValue"] = np.bytes_("1.5")
        z_axis = h5_file.create_group("DataSetInfo/Olympus Axis 3 Parameters Common")
        z_axis.attrs["AxisCode"] = np.bytes_("Z")
        z_axis.attrs["Interval"] = np.bytes_("2000")
        z_axis.attrs["PixUnit"] = np.bytes_("nm")

        channel_0_info = h5_file.create_group("DataSetInfo/Channel 0")
        channel_0_info.attrs["Name"] = np.asarray(list("Green"), dtype="S1")
        channel_0_info.attrs["Color"] = np.bytes_("0 1 0")
        channel_0_info.attrs["ColorRange"] = np.bytes_("0 20")
        channel_0_info.attrs["GammaCorrection"] = np.bytes_("0.5")
        channel_1_info = h5_file.create_group("DataSetInfo/Channel 1")
        channel_1_info.attrs["Name"] = np.bytes_("Red/Marker")
        channel_1_info.attrs["Color"] = np.bytes_("1 0 0")
        channel_1_info.attrs["ColorRange"] = np.bytes_("0 20")
        channel_1_info.attrs["GammaCorrection"] = np.bytes_("2.0")

        time_point = h5_file.create_group("DataSet/ResolutionLevel 0/TimePoint 0")
        green = np.zeros((3, 4, 5), dtype=np.uint16)
        green[0] = 2
        green[1] = 8
        green[2] = 15
        red = np.zeros((3, 4, 5), dtype=np.uint16)
        red[0] = 1
        red[1] = 10
        red[2] = 20
        time_point.create_dataset("Channel 0/Data", data=green)
        time_point.create_dataset("Channel 1/Data", data=red)
    return path
