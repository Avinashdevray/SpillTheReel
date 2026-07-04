import pytest
import unittest
from unittest.mock import patch, MagicMock, AsyncMock


class TestGenerateUnifiedSummary:
    @patch("app.services.brain.os.getenv")
    def test_missing_api_key(self, mock_getenv):
        mock_getenv.return_value = None
        from app.services.brain import generate_unified_summary
        import asyncio
        with pytest.raises(RuntimeError, match="GROQ_API_KEY"):
            asyncio.run(generate_unified_summary("audio transcript", "visual context"))

    @patch("app.services.brain.os.getenv")
    @patch("groq.Groq")
    def test_summary_success(self, mock_groq, mock_getenv):
        mock_getenv.return_value = "test-groq-key"
        mock_client = MagicMock()
        mock_groq.return_value = mock_client
        mock_response = MagicMock()
        mock_response.choices[0].message.content = "Unified summary paragraph."
        mock_client.chat.completions.create.return_value = mock_response

        from app.services.brain import generate_unified_summary
        import asyncio
        result = asyncio.run(generate_unified_summary("audio transcript", "visual context"))
        assert result == "Unified summary paragraph."

    @patch("app.services.brain.os.getenv")
    @patch("groq.Groq")
    def test_summary_api_error(self, mock_groq, mock_getenv):
        mock_getenv.return_value = "test-groq-key"
        mock_client = MagicMock()
        mock_groq.return_value = mock_client
        mock_client.chat.completions.create.side_effect = Exception("API error")

        from app.services.brain import generate_unified_summary
        import asyncio
        with pytest.raises(RuntimeError, match="Groq failed"):
            asyncio.run(generate_unified_summary("audio transcript", "visual context"))


class TestSaveToMemory:
    @pytest.mark.asyncio
    async def test_save_success(self):
        import sys
        from app.services.brain import save_to_memory

        cognee_mock = MagicMock()
        cognee_mock.add = AsyncMock()

        with unittest.mock.patch.dict(sys.modules, {"cognee": cognee_mock}):
            await save_to_memory("https://ig.com/reel/test", "Unified summary")
            cognee_mock.add.assert_called_once()
            # cognee.cognify is intentionally skipped — see save_to_memory docstring

    @pytest.mark.asyncio
    async def test_save_connection_error(self):
        import sys
        from app.services.brain import save_to_memory
        cognee_mock = MagicMock()
        cognee_mock.add = AsyncMock(side_effect=Exception("Connection refused to neo4j"))
        with unittest.mock.patch.dict(sys.modules, {"cognee": cognee_mock}):
            with pytest.raises(ConnectionError, match="Neo4j unreachable"):
                await save_to_memory("https://ig.com/reel/test", "Summary")


class TestQueryMemory:
    async def _run_query(self, question, cognee_mock):
        import sys
        from app.services.brain import query_memory

        search_type_mock = MagicMock()
        search_type_mock.HYBRID_COMPLETION = "HYBRID_COMPLETION"

        cognee_module = MagicMock()
        cognee_module.search = cognee_mock.search

        modules = {
            "cognee": cognee_module,
            "cognee.modules": MagicMock(),
            "cognee.modules.search": MagicMock(),
            "cognee.modules.search.types": MagicMock(),
            "cognee.modules.search.types.SearchType": search_type_mock,
        }

        with unittest.mock.patch.dict(sys.modules, modules):
            return await query_memory(question)

    @pytest.mark.asyncio
    async def test_query_success(self):
        cognee_mock = MagicMock()
        cognee_mock.search = AsyncMock(return_value=["result1", "result2"])
        results = await self._run_query("What was in this reel?", cognee_mock)
        assert results == ["result1", "result2"]

    @pytest.mark.asyncio
    async def test_empty_graph_sentinel(self):
        cognee_mock = MagicMock()
        cognee_mock.search = AsyncMock(side_effect=Exception("unable to open database file"))
        result = await self._run_query("Any reels?", cognee_mock)
        assert result == "__EMPTY_GRAPH__"
