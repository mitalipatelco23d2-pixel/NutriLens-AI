from scripts.mobile.evaluate_android_mlkit_evidence import _box


def test_physical_mlkit_bounds_are_clipped_to_image_without_inventing_area() -> None:
    clipped = _box(
        {"left": -1, "top": -3, "right": 701, "bottom": 1402},
        image_width=700,
        image_height=1400,
    )

    assert clipped is not None
    assert clipped.model_dump() == {"x": 0, "y": 0, "width": 700, "height": 1400}
    assert (
        _box(
            {"left": -5, "top": -5, "right": 0, "bottom": 0},
            image_width=700,
            image_height=1400,
        )
        is None
    )
