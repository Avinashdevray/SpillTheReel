import os
import pytest
from pathlib import Path
from app.services.ingestion import _resolve_actual_path


class TestResolveActualPath:
    def test_exact_path_exists(self, tmp_path):
        expected = tmp_path / "video.mp4"
        expected.write_bytes(b"content")
        result = _resolve_actual_path(str(expected), str(tmp_path))
        assert result == str(expected)

    def test_mp4_variant(self, tmp_path):
        mp4_file = tmp_path / "video.mp4"
        mp4_file.write_bytes(b"content")
        result = _resolve_actual_path(str(tmp_path / "video.mkv"), str(tmp_path))
        assert result == str(mp4_file)

    def test_largest_file_fallback(self, tmp_path):
        (tmp_path / "small.txt").write_text("small")
        large = tmp_path / "large.mp4"
        large.write_bytes(b"x" * 1000)
        result = _resolve_actual_path(str(tmp_path / "nonexistent.mp4"), str(tmp_path))
        assert result == str(large)

    def test_no_files_raises_error(self, tmp_path):
        with pytest.raises(RuntimeError, match="No video file found"):
            _resolve_actual_path(str(tmp_path / "nonexistent.mp4"), str(tmp_path))
