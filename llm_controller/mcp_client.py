"""MCP client — connects to the robot MCP server via stdio."""

import json
import logging
from contextlib import asynccontextmanager
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from llm_controller.config import MCP_SERVER_CMD

logger = logging.getLogger(__name__)


class MCPClient:
    def __init__(self):
        self._session: ClientSession | None = None
        self._stdio_context = None
        self._session_context = None

    async def connect(self):
        server_params = StdioServerParameters(
            command=MCP_SERVER_CMD[0],
            args=MCP_SERVER_CMD[1:],
        )
        self._stdio_context = stdio_client(server_params)
        read_stream, write_stream = await self._stdio_context.__aenter__()

        self._session_context = ClientSession(read_stream, write_stream)
        self._session = await self._session_context.__aenter__()

        await self._session.initialize()
        logger.info("MCP client connected")

        # List available tools
        tools = await self._session.list_tools()
        tool_names = [t.name for t in tools.tools]
        logger.info("Available tools: %s", tool_names)

    async def call_tool(self, name: str, arguments: dict | None = None) -> dict:
        """Call an MCP tool and return the parsed JSON result."""
        if self._session is None:
            raise RuntimeError("MCP client not connected")

        result = await self._session.call_tool(name, arguments or {})

        # Extract text content from the result
        text = ""
        for content in result.content:
            if hasattr(content, "text"):
                text += content.text

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            logger.warning("Non-JSON response from tool %s: %s", name, text)
            return {"raw": text}

    async def disconnect(self):
        if self._session_context:
            await self._session_context.__aexit__(None, None, None)
        if self._stdio_context:
            await self._stdio_context.__aexit__(None, None, None)
        logger.info("MCP client disconnected")
