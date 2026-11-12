from collections.abc import Generator
from typing import Any

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

from capturekit_api import call


class CaptureKitAnalyzePageTool(Tool):
    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage, None, None]:
        yield from call(
            self,
            tool_parameters,
            "GET",
            "/v1/analyze",
            {"url": "url", "custom_prompt": "custom_prompt"},
            required=("url",),
            timeout=150,
        )
