import pytest
from unittest.mock import patch, MagicMock, PropertyMock


class TestExtractVisualContext:
    @patch("app.services.visual_audio.os.getenv")
    def test_missing_api_key(self, mock_getenv):
        mock_getenv.return_value = None
        from app.services.visual_audio import extract_visual_context
        import asyncio
        with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
            asyncio.run(extract_visual_context("/fake/path.mp4"))

    @patch("app.services.visual_audio.os.getenv")
    @patch("google.genai.Client")
    def test_upload_success_and_active(self, mock_client_class, mock_getenv, mock_video_path):
        mock_getenv.return_value = "test-gemini-key"
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client

        mock_file = MagicMock()
        mock_file.name = "files/test123"
        type(mock_file.state).name = PropertyMock(return_value="ACTIVE")
        mock_client.files.upload.return_value = mock_file
        mock_client.files.get.return_value = mock_file
        mock_client.models.generate_content.return_value.text = "Visual summary text"

        from app.services.visual_audio import extract_visual_context
        import asyncio
        result = asyncio.run(extract_visual_context(mock_video_path))
        assert result == "Visual summary text"

    @patch("app.services.visual_audio.os.getenv")
    @patch("google.genai.Client")
    def test_upload_then_processes_then_active(self, mock_client_class, mock_getenv, mock_video_path):
        mock_getenv.return_value = "test-gemini-key"
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client

        mock_processing_file = MagicMock()
        mock_processing_file.name = "files/test123"
        type(mock_processing_file.state).name = PropertyMock(return_value="PROCESSING")

        mock_active_file = MagicMock()
        mock_active_file.name = "files/test123"
        type(mock_active_file.state).name = PropertyMock(return_value="ACTIVE")

        mock_client.files.upload.return_value = mock_processing_file
        mock_client.files.get.side_effect = [mock_processing_file, mock_active_file]
        mock_client.models.generate_content.return_value.text = "Visual summary text"

        from app.services.visual_audio import extract_visual_context
        import asyncio
        result = asyncio.run(extract_visual_context(mock_video_path))
        assert result == "Visual summary text"

    @patch("app.services.visual_audio.os.getenv")
    @patch("google.genai.Client")
    def test_file_processing_failed(self, mock_client_class, mock_getenv, mock_video_path):
        mock_getenv.return_value = "test-gemini-key"
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client

        mock_file = MagicMock()
        mock_file.name = "files/test123"
        type(mock_file.state).name = PropertyMock(return_value="FAILED")
        mock_client.files.upload.return_value = mock_file
        mock_client.files.get.return_value = mock_file

        from app.services.visual_audio import extract_visual_context
        import asyncio
        with pytest.raises(RuntimeError, match="Gemini reported FAILED"):
            asyncio.run(extract_visual_context(mock_video_path))


class TestDeleteGeminiFile:
    @patch("app.services.visual_audio.os.getenv")
    @patch("google.genai.Client")
    def test_delete_success(self, mock_client_class, mock_getenv):
        mock_getenv.return_value = "test-gemini-key"
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client

        from app.services.visual_audio import delete_gemini_file
        delete_gemini_file("files/test123")
        mock_client.files.delete.assert_called_once_with(name="files/test123")

    @patch("app.services.visual_audio.os.getenv")
    def test_delete_no_key(self, mock_getenv):
        mock_getenv.return_value = None
        from app.services.visual_audio import delete_gemini_file
        delete_gemini_file("files/test123")
