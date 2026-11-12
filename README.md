# CaptureKit for Dify

[CaptureKit](https://www.capturekit.dev) loads web pages in a real browser on its own infrastructure. This plugin gives Dify agents, workflows and chatflows the content of any page as clean Markdown, screenshots and PDFs of it, and an AI profile of a website: summary, value proposition, features, audience and contact details.

**Author:** capturekitdev · **Source:** https://github.com/capturekitdev/dify-plugin-capturekit · **Contact:** contact@capturekit.dev

## Tools

| Tool | What it does |
| --- | --- |
| **Page Content** | Loads the page in a browser and returns it as Markdown, with its title, description and internal, external and social links. **Main Content Only** (on by default) drops menus, sidebars and footers. 1 credit. |
| **Screenshot** | Captures the page as PNG, JPEG or WebP, or a PDF, and returns the file. **Full Page** captures top to bottom; **Device** gives the view on an iPhone, Pixel, Galaxy or iPad. 1 credit. |
| **Analyze Page** | An AI profile of the page: summary, value proposition, key features, categories, use cases, target audience, emails and phone numbers. Optional custom question. 1 credit. |

**Page Content** and **Analyze Page** return a text message, which agents read, and a JSON message for workflow variables. **Screenshot** returns the image or PDF as a file, plus its details as JSON. Errors such as an invalid key, missing credits or a rate limit come back as a text message, and the API key never appears in it.

## Setup

1. Create an account and copy your API key at [app.capturekit.dev](https://app.capturekit.dev).
2. In Dify, install the **CaptureKit** plugin from the Marketplace.
3. Open **Tools → CaptureKit → Authorize** and paste the API key. Dify checks it with a request that costs no credits.
4. Add the tools to an agent, a workflow or a chatflow.

## Requirements

- Dify 1.0.0 or later.
- Outbound HTTPS access to `api.capturekit.dev`.
- A CaptureKit API key. Usage counts against your CaptureKit credits; see [www.capturekit.dev/pricing](https://www.capturekit.dev/pricing).

## Privacy

See [PRIVACY.md](PRIVACY.md).

## Development

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt pytest pyyaml
.venv/bin/pytest
```

The `Package` workflow builds the `.difypkg` with Dify's plugin CLI and attaches it to a GitHub release when the version in `manifest.yaml` changes.
