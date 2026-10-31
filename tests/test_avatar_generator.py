"""Tests for the initials avatar generator."""

import pytest

avatar_generator = pytest.importorskip("tool_modules.aa_meet_bot.src.avatar_generator")


@pytest.mark.parametrize(
    ("name", "expected"),
    [("Ada Lovelace", "AL"), ("Ada Byron Lovelace", "AL"), ("Bob", "BO"), ("x", "X"), ("", "?")],
)
def test_get_initials(name, expected):
    """Initials come from the first and last words, or the single word."""
    assert avatar_generator.get_initials(name) == expected


def test_color_is_stable_and_case_insensitive():
    """The name colour is a fixed function of the lower-cased name."""
    color = avatar_generator.get_color_for_name("Ada Lovelace")
    assert color == avatar_generator.get_color_for_name("ada lovelace")
    assert color == (75, 153, 216)


def test_cache_path_keeps_existing_names(tmp_path, monkeypatch):
    """Cache file names match those written by earlier versions."""
    monkeypatch.setattr(avatar_generator, "AVATAR_CACHE_DIR", tmp_path)
    cache_path = vars(avatar_generator)["_get_cache_path"]("Ada Lovelace", 64)
    assert cache_path == tmp_path / "03f339ae9cfc_64.png"


def test_avatar_shapes_and_alpha():
    """BGR, BGRA and texture outputs have the documented shapes."""
    bgr = avatar_generator.generate_initials_avatar("Ada", 64, use_cache=False)
    rgba = avatar_generator.generate_initials_avatar_rgba("Ada", 64)
    texture, width, height = avatar_generator.generate_avatar_texture_data("Ada", None, 64)
    assert bgr.shape == (64, 64, 3)
    assert rgba.shape == (64, 64, 4)
    assert texture.shape == (64, 64, 4)
    assert (width, height) == (64, 64)
    assert rgba[0, 0, 3] == 0
    assert rgba[32, 5, 3] == 255


def test_cached_avatar_round_trips(tmp_path, monkeypatch):
    """A cached avatar is written once and read back unchanged."""
    monkeypatch.setattr(avatar_generator, "AVATAR_CACHE_DIR", tmp_path)
    first = avatar_generator.generate_initials_avatar("Ada", 32)
    assert list(tmp_path.iterdir())
    assert (avatar_generator.generate_initials_avatar("Ada", 32) == first).all()
