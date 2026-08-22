from __future__ import annotations

from types import SimpleNamespace

from iea.bioformats_reader import _extract_original_dye_names, _fallback_color


def original_metadata(key: str, value: str):
    return SimpleNamespace(
        namespace="openmicroscopy.org/OriginalMetadata",
        value=SimpleNamespace(
            any_elements=(
                SimpleNamespace(
                    children=(
                        SimpleNamespace(qname="{ome}Key", text=key),
                        SimpleNamespace(qname="{ome}Value", text=value),
                    )
                ),
            )
        ),
    )


def test_extracts_reliable_olympus_dye_names_from_original_metadata() -> None:
    ome = SimpleNamespace(
        structured_annotations=(
            original_metadata("[Channel 1 Parameters] DyeName", "Alexa Fluor 488"),
            original_metadata("[GUI Channel 2 Parameters] DyeName", "Alexa Fluor 594"),
            original_metadata("[Channel 3 Parameters] DyeName", "DRAQ5"),
            original_metadata("[Channel 4 Parameters] DyeName", "None"),
        )
    )

    assert _extract_original_dye_names(ome, 3) == {
        0: "Alexa Fluor 488",
        1: "Alexa Fluor 594",
        2: "DRAQ5",
    }


def test_known_dye_color_has_priority_over_approximate_wavelength() -> None:
    assert _fallback_color("Alexa Fluor 488", 0, 520.0, 473.0) == (0.0, 1.0, 0.0)
    assert _fallback_color("Alexa Fluor 594", 1, 618.0, 559.0) == (1.0, 0.0, 0.0)
    assert _fallback_color("DRAQ5", 2, 683.0, 635.0) == (0.0, 0.0, 1.0)
