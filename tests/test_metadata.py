import h5py

from app.ims_reader import IMSReader


def test_reads_normalized_metadata_without_loading_whole_file(sample_ims):
    with IMSReader(sample_ims) as reader:
        metadata = reader.metadata
        assert metadata is not None
        assert (metadata.size_x, metadata.size_y, metadata.size_z) == (5, 4, 3)
        assert (metadata.voxel_size_x_um, metadata.voxel_size_y_um, metadata.voxel_size_z_um) == (
            0.5,
            1.0,
            2.0,
        )
        assert metadata.origin_z_um == 0.0
        assert metadata.dtype == "uint16"
        assert metadata.channels[0].name == "Green"
        assert metadata.channels[0].color == (0.0, 1.0, 0.0)
        assert metadata.channels[0].display_min == 0.0
        assert metadata.channels[0].display_max == 20.0
        assert metadata.channels[0].axis_order == ("Z", "Y", "X")


def test_reads_only_requested_inclusive_z_range(sample_ims):
    with IMSReader(sample_ims) as reader:
        selected = reader.read_z_range(channel_index=0, z_start=2, z_end=3)
        assert selected.shape == (2, 4, 5)
        assert selected.dtype.name == "uint16"
        assert selected[:, 0, 0].tolist() == [8, 15]


def test_uses_resolution_level_shape_when_one_metadata_dimension_is_stale(sample_ims):
    with h5py.File(sample_ims, "r+") as h5_file:
        h5_file["DataSetInfo/Image"].attrs["Z"] = b"2"

    with IMSReader(sample_ims) as reader:
        metadata = reader.metadata
        assert metadata is not None
        assert metadata.size_z == 3
        assert any("Z: metadata=2, data=3" in warning for warning in metadata.warnings)
