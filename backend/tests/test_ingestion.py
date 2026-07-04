import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock, mock_open


@pytest.fixture
def mock_cookies_in_backend(tmp_path):
    cookies = tmp_path / "cookies.txt"
    cookies.write_text("# Netscape HTTP Cookie File\n")
    return cookies


class TestDownloadVideo:
    @patch("app.services.ingestion._COOKIES_FILE")
    @patch("app.services.ingestion.yt_dlp.YoutubeDL")
    def test_missing_cookies_handled_gracefully(self, mock_ydl, mock_cookies_file, tmp_path):
        mock_cookies_file.exists.return_value = False
        
        mock_ydl_instance = MagicMock()
        mock_ydl.return_value.__enter__.return_value = mock_ydl_instance
        mock_ydl_instance.extract_info.return_value = {"id": "test"}
        video_path = tmp_path / "video.mp4"
        video_path.write_bytes(b"fake video")
        mock_ydl_instance.prepare_filename.return_value = str(video_path)

        from app.services.ingestion import download_video
        import asyncio
        result_path, tmpdir, metadata = asyncio.run(download_video("https://instagram.com/reel/test"))
        assert result_path == str(video_path)
        tmpdir.cleanup()


    @patch("app.services.ingestion._COOKIES_FILE")
    @patch("app.services.ingestion.yt_dlp.YoutubeDL")
    def test_download_success(self, mock_ydl, mock_cookies_file, tmp_path):
        mock_cookies_file.exists.return_value = True
        mock_cookies_file.__str__.return_value = str(tmp_path / "cookies.txt")

        mock_ydl_instance = MagicMock()
        mock_ydl.return_value.__enter__.return_value = mock_ydl_instance

        mock_ydl_instance.extract_info.return_value = {"id": "test"}
        video_path = tmp_path / "video.mp4"
        video_path.write_bytes(b"fake video")
        mock_ydl_instance.prepare_filename.return_value = str(video_path)

        from app.services.ingestion import download_video
        import asyncio
        result_path, tmpdir, metadata = asyncio.run(download_video("https://instagram.com/reel/test"))
        assert result_path == str(video_path)
        tmpdir.cleanup()

    @patch("app.services.ingestion._COOKIES_FILE")
    @patch("app.services.ingestion.yt_dlp.YoutubeDL")
    def test_download_network_error(self, mock_ydl, mock_cookies_file, tmp_path):
        import yt_dlp
        mock_cookies_file.exists.return_value = True
        mock_cookies_file.__str__.return_value = str(tmp_path / "cookies.txt")

        mock_ydl_instance = MagicMock()
        mock_ydl.return_value.__enter__.return_value = mock_ydl_instance
        mock_ydl_instance.extract_info.side_effect = yt_dlp.utils.DownloadError(
            "network error: Unable to connect"
        )

        from app.services.ingestion import download_video
        import asyncio
        with pytest.raises(ConnectionError, match="yt-dlp network failure"):
            asyncio.run(download_video("https://instagram.com/reel/test"))


class TestTranscribeAudio:
    @patch("app.services.ingestion.os.getenv")
    def test_missing_api_key(self, mock_getenv):
        mock_getenv.return_value = None
        from app.services.ingestion import transcribe_audio
        import asyncio
        with pytest.raises(RuntimeError, match="GROQ_API_KEY"):
            asyncio.run(transcribe_audio("/fake/path.mp4"))

    @patch("app.services.ingestion._extract_audio")
    @patch("app.services.ingestion.os.getenv")
    @patch("groq.Groq")
    def test_transcription_success(self, mock_groq, mock_getenv, mock_extract, mock_video_path, tmp_path):
        mock_getenv.return_value = "test-groq-key"
        audio_path = tmp_path / "audio.mp3"
        audio_path.write_bytes(b"fake audio")
        mock_extract.return_value = str(audio_path)
        mock_client = MagicMock()
        mock_groq.return_value = mock_client
        mock_client.audio.transcriptions.create.return_value = "Hello world transcript"

        from app.services.ingestion import transcribe_audio
        import asyncio
        result = asyncio.run(transcribe_audio(mock_video_path))
        assert result == "Hello world transcript"

    @patch("app.services.ingestion._extract_audio")
    @patch("app.services.ingestion.os.getenv")
    @patch("groq.Groq")
    def test_transcription_api_error(self, mock_groq, mock_getenv, mock_extract, mock_video_path, tmp_path):
        mock_getenv.return_value = "test-groq-key"
        audio_path = tmp_path / "audio.mp3"
        audio_path.write_bytes(b"fake audio")
        mock_extract.return_value = str(audio_path)
        mock_client = MagicMock()
        mock_groq.return_value = mock_client
        mock_client.audio.transcriptions.create.side_effect = Exception("API error")

        from app.services.ingestion import transcribe_audio
        import asyncio
        with pytest.raises(RuntimeError, match="Groq Whisper API failed"):
            asyncio.run(transcribe_audio(mock_video_path))
