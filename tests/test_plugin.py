import ast
import importlib
from pathlib import Path

import pytest
import requests
import yaml
from conftest import ROOT
from dify_plugin.errors.tool import ToolProviderCredentialValidationError

from provider.capturekit import CaptureKitProvider

KEY = "test-key-not-real"
BASE = "https://api.capturekit.dev"
TOOLS = {
    "page_content": "CaptureKitPageContentTool",
    "screenshot": "CaptureKitScreenshotTool",
    "analyze_page": "CaptureKitAnalyzePageTool",
}


def run(tool_cls, params):
    return list(tool_cls.from_credentials({"api_key": KEY}).invoke(params))


def texts(messages):
    return [m.message.text for m in messages if m.type.value == "text"]


def jsons(messages):
    return [m.message.json_object for m in messages if m.type.value == "json"]


def test_credentials_check_calls_the_free_endpoint(http):
    http.reply(200, {"credits": 100})
    CaptureKitProvider()._validate_credentials({"api_key": f" {KEY} "})
    call = http.calls[0]
    assert (call["method"], call["url"]) == ("GET", BASE + "/v1/usage")
    assert call["headers"]["x-api-key"] == KEY
    assert call["timeout"] == 30


def test_credentials_check_rejects_a_bad_key_without_showing_it(http):
    http.reply(401, {"error": f"Invalid API key {KEY}"})
    with pytest.raises(ToolProviderCredentialValidationError) as error:
        CaptureKitProvider()._validate_credentials({"api_key": KEY})
    assert "401" in str(error.value) and "not valid" in str(error.value)
    assert KEY not in str(error.value)


def test_credentials_check_needs_a_key(http):
    with pytest.raises(ToolProviderCredentialValidationError):
        CaptureKitProvider()._validate_credentials({"api_key": "  "})
    assert http.calls == []


def test_network_error_has_a_clear_message(http):
    http.raise_error(requests.ConnectionError(f"failed with {KEY}"))
    with pytest.raises(ToolProviderCredentialValidationError) as error:
        CaptureKitProvider()._validate_credentials({"api_key": KEY})
    assert "api.capturekit.dev" in str(error.value) and KEY not in str(error.value)


def test_plugin_registers_provider_and_tools():
    from dify_plugin import DifyPluginEnv
    from dify_plugin.core.plugin_registration import PluginRegistration

    registration = PluginRegistration(DifyPluginEnv())
    assert registration.get_tool_provider_cls("capturekit").__name__ == "CaptureKitProvider"
    for tool, class_name in TOOLS.items():
        assert registration.get_tool_cls("capturekit", tool).__name__ == class_name


def test_each_tool_file_has_one_tool_class():
    for path in Path(ROOT, "tools").glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        assert len([n for n in tree.body if isinstance(n, ast.ClassDef)]) == 1, path.name


def test_manifest_and_tool_files_agree():
    manifest = yaml.safe_load(Path(ROOT, "manifest.yaml").read_text(encoding="utf-8"))
    provider = yaml.safe_load(Path(ROOT, "provider/capturekit.yaml").read_text(encoding="utf-8"))
    assert manifest["version"] == manifest["meta"]["version"]
    assert manifest["author"] == provider["identity"]["author"] == "capturekitdev"
    assert manifest["network"]["domains"] == ["api.capturekit.dev"]
    assert Path(ROOT, "_assets", manifest["icon"]).is_file()
    assert Path(ROOT, manifest["privacy"]).is_file()
    assert sorted(Path(f).stem for f in provider["tools"]) == sorted(TOOLS)
    for tool_file in provider["tools"]:
        tool = yaml.safe_load(Path(ROOT, tool_file).read_text(encoding="utf-8"))
        assert tool["identity"]["author"] == "capturekitdev"
        assert Path(ROOT, tool["extra"]["python"]["source"]).is_file()
        for param in tool["parameters"]:
            assert param["form"] in ("llm", "form")
            assert param["form"] == "form" or param.get("llm_description")


CASES = [
    (
        "analyze_page",
        "CaptureKitAnalyzePageTool",
        {"url": "https://example.com", "custom_prompt": "Who is it for?"},
        "GET",
        "/v1/analyze",
        {"url": "https://example.com", "custom_prompt": "Who is it for?"},
    )
]


@pytest.mark.parametrize("tool, cls_name, sample, method, url, values", CASES)
def test_tool_request(http, tool, cls_name, sample, method, url, values):
    http.reply(200, {"ok": True, "items": [1, 2]})
    cls = getattr(importlib.import_module(f"tools.{tool}"), cls_name)
    messages = run(cls, sample)
    call = http.calls[0]
    assert (call["method"], call["url"]) == (method, BASE + url)
    sent = call["params"] if method in ("GET", "DELETE") else call["json"]
    assert sent == values
    assert call["headers"]["x-api-key"] == KEY
    assert '"ok": true' in texts(messages)[0]
    assert jsons(messages) == [{"ok": True, "items": [1, 2]}]


@pytest.mark.parametrize("tool, cls_name, sample, method, url, values", CASES)
def test_required_inputs_are_checked_before_any_request(http, tool, cls_name, sample, method, url, values):
    cls = getattr(importlib.import_module(f"tools.{tool}"), cls_name)
    tool_yaml = yaml.safe_load(Path(ROOT, f"tools/{tool}.yaml").read_text(encoding="utf-8"))
    if not any(p["required"] for p in tool_yaml["parameters"]):
        pytest.skip("no required input")
    messages = run(cls, {})
    assert "is required" in texts(messages)[0] and jsons(messages) == []
    assert http.calls == []


def test_errors_are_returned_as_text(http):
    if not CASES:
        pytest.skip("covered by the brand tests")
    tool, cls_name, sample = CASES[0][:3]
    cls = getattr(importlib.import_module(f"tools.{tool}"), cls_name)
    http.reply(402, {"error": "No credits"})
    assert texts(run(cls, sample)) == ["CaptureKit error 402: Not enough credits. (No credits)"]


def test_timeout(http):
    if not CASES:
        pytest.skip("covered by the brand tests")
    tool, cls_name, sample = CASES[0][:3]
    cls = getattr(importlib.import_module(f"tools.{tool}"), cls_name)
    http.raise_error(requests.Timeout("slow"))
    assert texts(run(cls, sample)) == ["CaptureKit did not answer in time. Try again."]


from tools.page_content import CaptureKitPageContentTool  # noqa: E402
from tools.screenshot import CaptureKitScreenshotTool  # noqa: E402

CONTENT = {
    "success": True,
    "data": {
        "markdown": "# Example\n\nFor use in examples.",
        "metadata": {"title": "Example Domain", "description": "d", "favicon": "f"},
        "links": {"internal": ["https://example.com/a"], "external": [], "social": []},
    },
}


def test_page_content(http):
    http.reply(200, CONTENT)
    messages = run(CaptureKitPageContentTool, {"url": " https://example.com ", "main_content_only": True})
    call = http.calls[0]
    assert (call["url"], call["timeout"]) == (BASE + "/v1/content", 150)
    assert call["params"] == {
        "url": "https://example.com",
        "include_markdown": "true",
        "remove_cookie_banners": "true",
        "use_defuddle": "true",
    }
    assert texts(messages) == ["# Example Domain\n\n# Example\n\nFor use in examples."]
    assert jsons(messages)[0]["links"]["internal"] == ["https://example.com/a"]


def test_page_content_whole_page_and_cut(http):
    http.reply(200, CONTENT)
    data = jsons(
        run(CaptureKitPageContentTool, {"url": "https://example.com", "main_content_only": False, "max_characters": 9})
    )[0]
    assert "use_defuddle" not in http.calls[0]["params"]
    assert data["markdown"] == "# Example"


@pytest.mark.parametrize("url", ["", "example.com", "file:///etc/passwd"])
def test_bad_urls_never_reach_the_api(http, url):
    assert "absolute http(s) URL" in texts(run(CaptureKitScreenshotTool, {"url": url}))[0]
    assert "absolute http(s) URL" in texts(run(CaptureKitPageContentTool, {"url": url}))[0]
    assert http.calls == []


def test_screenshot_returns_the_file(http):
    http.reply(200, None, b"\x89PNG fake", "image/png")
    messages = run(
        CaptureKitScreenshotTool,
        {"url": "https://example.com", "full_page": True, "device": "iphone_14_pro", "format": "png"},
    )
    assert http.calls[0]["params"] == {
        "url": "https://example.com",
        "full_page": "true",
        "full_page_scroll": "true",
        "device": "iphone_14_pro",
        "format": "png",
    }
    assert [m.type.value for m in messages] == ["text", "blob", "json"]
    assert messages[1].message.blob == b"\x89PNG fake"
    assert messages[1].meta == {"mime_type": "image/png", "filename": "screenshot.png"}
    assert jsons(messages) == [{"url": "https://example.com", "format": "png", "mime_type": "image/png", "bytes": 9}]


def test_screenshot_that_is_not_an_image(http):
    http.reply(200, {"error": "x"}, b"{}", "application/json")
    assert texts(run(CaptureKitScreenshotTool, {"url": "https://example.com"})) == ["CaptureKit did not send an image."]


def test_screenshot_error(http):
    http.reply(402, {"error": "No credits"})
    assert texts(run(CaptureKitScreenshotTool, {"url": "https://example.com"})) == [
        "CaptureKit error 402: Not enough credits. (No credits)"
    ]
