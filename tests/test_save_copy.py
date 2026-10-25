"""Tests for the safe file copy helper used by Save As."""
from pdffiller.gui.main_window import save_filled_copy


def test_save_copy(tmp_path):
    source = tmp_path / "a.pdf"
    source.write_bytes(b"data")
    target = tmp_path / "b.pdf"
    save_filled_copy(str(source), str(target))
    assert target.read_bytes() == b"data"


def test_save_same_file_is_noop(tmp_path):
    source = tmp_path / "a.pdf"
    source.write_bytes(b"data")
    save_filled_copy(str(source), str(source))  # must not raise
    assert source.read_bytes() == b"data"


def test_save_same_file_via_symlink_is_noop(tmp_path):
    source = tmp_path / "a.pdf"
    source.write_bytes(b"data")
    link = tmp_path / "link.pdf"
    link.symlink_to(source)
    save_filled_copy(str(source), str(link))  # must not raise
    assert source.read_bytes() == b"data"
