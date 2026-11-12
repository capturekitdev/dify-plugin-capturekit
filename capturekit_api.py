"""Calls to the CaptureKit API and conversion of its responses to tool output.

The provider and the tools share this module. A tool file must hold only one
Tool subclass, so the shared code is here and not in tools/.
"""

import json
from collections.abc import Generator
from typing import Any
from urllib.parse import quote

import requests

API_BASE = "https://api.capturekit.dev"
USER_AGENT = "capturekit-dify-plugin/0.0.1"
CREDENTIALS_PATH = "/v1/usage"
CREDENTIALS_TIMEOUT = 30
DEFAULT_TIMEOUT = 60
MAX_TEXT = 20000


class ApiError(Exception):
    """An error message that is safe to show to the user and to the model. It never contains the key."""


def api_key(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ApiError("A CaptureKit API key is required.")
    return value.strip()


def _headers(secret: str) -> dict:
    headers = {"Accept": "application/json", "User-Agent": USER_AGENT}
    headers["x-api-key"] = secret
    return headers


def _error_message(response: requests.Response) -> str:
    detail = ""
    try:
        body = response.json()
    except ValueError:
        body = None
    if isinstance(body, dict):
        error = body.get("error") or body.get("message") or ""
        if isinstance(error, dict):
            error = error.get("message") or ""
        detail = str(error)
    status = response.status_code
    if status == 401 and "rate limit" in detail.lower():
        label = "Rate limit exceeded. Try again soon."
    elif status == 401:
        label = "The API key is not valid."
    elif status == 402:
        label = "Not enough credits."
    elif status == 429:
        label = "Rate limit exceeded. Try again soon."
    else:
        label = "The request failed."
    return f"CaptureKit error {status}: {label}" + (f" ({detail[:300]})" if detail and detail not in label else "")


def request(
    method: str,
    path: str,
    key: Any,
    params: dict | None = None,
    body: dict | None = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> requests.Response:
    """Call API_BASE + path with the key, and return the successful response."""
    secret = api_key(key)
    try:
        response = requests.request(
            method, API_BASE + path, params=params, json=body, headers=_headers(secret), timeout=timeout
        )
    except requests.Timeout:
        raise ApiError("CaptureKit did not answer in time. Try again.") from None
    except requests.RequestException:
        raise ApiError("Could not connect to api.capturekit.dev. Check the network.") from None
    if response.status_code >= 400:
        raise ApiError(_error_message(response).replace(secret, "***"))
    return response


def check_credentials(key: Any) -> None:
    """The credentials endpoint costs no credits and fails when the key is not valid."""
    request("GET", CREDENTIALS_PATH, key, timeout=CREDENTIALS_TIMEOUT)


def body_json(response: requests.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        raise ApiError("CaptureKit sent a response that is not JSON.") from None


def _value(value: Any) -> Any:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def collect(params: dict, fields: dict[str, str], required: tuple = ()) -> dict:
    """Map tool parameters to API parameters, skipping empty values and checking the required ones."""
    out = {}
    for name, api_name in fields.items():
        value = _value(params.get(name))
        if value is None or value == "":
            if name in required:
                raise ApiError(f"{name} is required.")
            continue
        out[api_name] = value
    return out


def fill_path(path: str, values: dict) -> str:
    """Move values named in the path ("/jobs/{id}") into it, escaped."""
    for name in list(values):
        if "{" + name + "}" in path:
            path = path.replace("{" + name + "}", quote(str(values.pop(name)), safe=""))
    return path


def query_values(values: dict) -> dict:
    """Booleans as true/false, as the API expects them in a query string."""
    return {k: ("true" if v else "false") if isinstance(v, bool) else v for k, v in values.items()}


def as_text(data: Any) -> str:
    text = json.dumps(data, ensure_ascii=False, indent=2)
    return text if len(text) <= MAX_TEXT else text[:MAX_TEXT] + "\n… (cut)"


def call(
    tool,
    params: dict,
    method: str,
    path: str,
    fields: dict[str, str],
    required: tuple = (),
    fixed: dict | None = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> Generator:
    """Run one API call for a tool: a text message for agents, then a JSON message for workflows."""
    try:
        values = {**(fixed or {}), **collect(params, fields, required)}
        path = fill_path(path, values)
        in_query = method in ("GET", "DELETE")
        if in_query:
            values = query_values(values)
        response = request(
            method,
            path,
            tool.runtime.credentials.get("api_key"),
            params=values if in_query else None,
            body=None if in_query else values,
            timeout=timeout,
        )
        data = body_json(response)
    except ApiError as error:
        yield tool.create_text_message(str(error))
        return
    yield tool.create_text_message(as_text(data))
    yield tool.create_json_message(data if isinstance(data, dict) else {"results": data})


# Pages and screenshots

import re  # noqa: E402

EXTENSIONS = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp", "application/pdf": "pdf"}
PAGE_TIMEOUT = 150


def page_url(params: dict) -> str:
    value = params.get("url")
    url = value.strip() if isinstance(value, str) else ""
    if not re.match(r"^https?://[^/\s]+", url, re.IGNORECASE):
        raise ApiError(f"Use an absolute http(s) URL, such as https://example.com; got {url!r}.")
    return url


def _limit(params: dict) -> int:
    try:
        return max(int(params.get("max_characters") or 20000), 1)
    except (TypeError, ValueError):
        return 20000


def page_content(tool, params: dict):
    """The page as Markdown, with its title, description and links."""
    try:
        url = page_url(params)
        query = {"url": url, "include_markdown": "true", "remove_cookie_banners": "true"}
        if params.get("main_content_only") is not False:
            query["use_defuddle"] = "true"
        response = request(
            "GET", "/v1/content", tool.runtime.credentials.get("api_key"), params=query, timeout=PAGE_TIMEOUT
        )
        body = body_json(response)
    except ApiError as error:
        yield tool.create_text_message(str(error))
        return
    data = body.get("data") if isinstance(body, dict) else None
    if not isinstance(data, dict) or not isinstance(data.get("markdown"), str):
        yield tool.create_text_message("CaptureKit sent an unexpected response; expected the page Markdown.")
        return
    metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
    markdown = data["markdown"][: _limit(params)]
    page = {
        "url": url,
        "title": str(metadata.get("title") or ""),
        "description": str(metadata.get("description") or ""),
        "markdown": markdown,
        "links": data.get("links") if isinstance(data.get("links"), dict) else {},
    }
    yield tool.create_text_message(f"# {page['title'] or url}\n\n{markdown or '(The page has no readable text.)'}")
    yield tool.create_json_message(page)


def screenshot(tool, params: dict):
    """Capture the page and return the image or PDF as a file."""
    try:
        url = page_url(params)
        query = {"url": url}
        if params.get("full_page") is True:
            query["full_page"] = "true"
            query["full_page_scroll"] = "true"
        for name in ("device", "format"):
            value = params.get(name)
            if isinstance(value, str) and value.strip():
                query[name] = value.strip()
        response = request(
            "GET", "/v1/capture", tool.runtime.credentials.get("api_key"), params=query, timeout=PAGE_TIMEOUT
        )
    except ApiError as error:
        yield tool.create_text_message(str(error))
        return
    mime = str(response.headers.get("Content-Type") or "").split(";")[0].strip().lower()
    extension = EXTENSIONS.get(mime)
    if not extension or not response.content:
        yield tool.create_text_message("CaptureKit did not send an image.")
        return
    yield tool.create_text_message(f"Screenshot of {url} ({extension}, {len(response.content)} bytes).")
    yield tool.create_blob_message(response.content, meta={"mime_type": mime, "filename": f"screenshot.{extension}"})
    yield tool.create_json_message({"url": url, "format": extension, "mime_type": mime, "bytes": len(response.content)})
