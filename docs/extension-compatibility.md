# Merlin extension header compatibility

Verified on 2026-09-17. The adapter default is:

```dotenv
MERLIN_VERSION=merlin-extension-8.2.3
```

This value becomes the upstream `x-merlin-version` header. An existing `.env`
or process environment overrides the default; restart the adapter after changing
the setting.

## Official extension evidence

The installed Chrome extension has ID `camppjleccjaphfdbohjdohecfnoikec` and
manifest version `8.2.3`, matching the
[official Chrome Web Store listing](https://chromewebstore.google.com/detail/merlin-ai/camppjleccjaphfdbohjdohecfnoikec).
Its manifest uses Google's extension update service.

Both `background.js` and `chunks/sidepanel-Dt2U-t-U.js` define the literal
`merlin-extension-8.2.3` and bind it to `x-merlin-version` in their HTTP clients.
This is evidence from the installed extension's source, not an inferred header
based only on its version number or a capture of browser network traffic.

Source file SHA-256 hashes:

- `background.js`: `c214b9bb7c0412d1d1e6afdc31f096bff02b808bf403c8dbe49eeb4a3b775905`
- `chunks/sidepanel-Dt2U-t-U.js`: `6d6d2b4fbf07fd321dac3eebdcdf3a3493ffc27723d6937963635a2df5f836cc`

## Historical header comparison (pre-migration)

Two consecutive pre-migration runs used the same adapter, endpoint, prompts, two workers, and
models (`gpt-5.6-luna`, `claude-sonnet-5`), changing only `MERLIN_VERSION`.
Each model was tested with chat, streamed chat, required tool calls, and streamed
tool calls through FastAPI TestClient and the real Merlin upstream.

| Header value | Initial result | Failed checks |
| --- | --- | --- |
| `merlin-extension-8.0.11` | 6/8 passed | Luna tool call: HTTP 422; Sonnet streamed chat: expected reply absent |
| `merlin-extension-8.2.3` | 7/8 passed | Sonnet tool call: HTTP 422 |

The failed 8.2.3 Sonnet tool case passed on one targeted recheck using the updated
local `.env`. Keep the original failure in the record: these small, nondeterministic
samples establish working requests with the new header, not an improvement in
reliability or a fix for tool-call instability.

Smoke reports now include `merlin_version` to identify the header under test.
Local evidence is stored in the Git-ignored files:

- `logs/extension-header-source.json`
- `logs/extension-header-8.0.11.json`
- `logs/extension-header-8.2.3.json`
- `logs/extension-header-8.2.3-recheck.json`

Run a focused check with the effective environment setting:

```bash
uv run python scripts/smoke_test_models.py --models gpt-5.6-luna claude-sonnet-5 --modes chat chat-stream --out logs/extension-header-check.json
```

## Protocol scope

The extension's current side panel sends chat requests to `/v2/extension/chat`
under `https://www.getmerlin.in/arcane/api`. The adapter now uses the same
extension route and native `{model,messages,params,metadata}` payload shape.
It sends the extension Origin and version headers, without a Referer or the
old request timestamp header.

The adapter does not register the extension's built-in browser or MCP tools.
`params.tools` remains empty unless an OpenAI caller explicitly supplies tools.
User and tool string content is encoded as native text parts, and native SSE
errors or incomplete streams are surfaced as failures instead of successful
completions. Detailed migration evidence is in
[`extension-api-migration-review.md`](extension-api-migration-review.md).

The current live account check confirms text and text streaming. An adapter-only
`echo_probe` function schema still receives an upstream `INTERNAL_SERVER_ERROR`,
so custom tool calling remains unverified and is not included in the normal
smoke command.

This limitation concerns native caller tools. The optional `TOOL_CALL_MODE=emulated`
path has since passed OpenCode read-and-answer rounds for Luna and Sonnet using
text chat and local response validation; see [tool emulation](emulated-tool-calling.md).
