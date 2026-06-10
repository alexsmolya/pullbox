from pullbox.models.series import SeriesType


def test_graphic_novel_ui_display_name_is_spelled_out() -> None:
    assert SeriesType.GRAPHIC_NOVEL.ui_display_name == "Graphic Novel"


def test_graphic_novel_backend_display_name_remains_short() -> None:
    assert SeriesType.GRAPHIC_NOVEL.display_name == "GN"
