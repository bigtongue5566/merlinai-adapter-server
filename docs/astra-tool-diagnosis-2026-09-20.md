# Astra tool diagnosis

## Further native transport investigation

`logs/astra-native-variants.json`: standard nested schema, strict=true, flattened schema, MCP disabled, string message content, and omitted output budget all returned INTERNAL_SERVER_ERROR from the extension streaming endpoint. These diagnostic variations do not change production token settings.

`logs/astra-rpc-document-read.json`: replacing the adapter's first and last instructions with a consistent external-operation document contract still failed the real OpenCode read test. Caller messages were preserved. No tools executed.

The alternate `/arcane/api/v2/extension/chat/completions` endpoint was observed in the user-provided HAR. It rejects string content with BAD_REQUEST and accepts text-part arrays. Both nested and top-level parameter probes returned HTTP 200. The inspected nested response (`logs/astra-alternate-endpoint-body.json`) only contained `data.content` saying echo_probe was unavailable, with no tool calls. Thus a successful HTTP response does not establish native tool support.

No viable native fallback or general OpenCode workaround was established. The probes remain isolated under logs; no production endpoint, user prompt, model limit, or NAS deployment was changed. A successful Astra tool-use capture from the official client would provide new evidence to compare; the Gemini capture alone cannot establish Astra's contract.

Evidence: `logs/astra-tool-diagnosis.json`, real Merlin requests, `gpt-6-astra`, max_tokens=128000. No tools were executed. Raw reasoning was not saved.

Both emulated required and auto modes returned a valid message envelope saying: "I can’t call echo_probe because it isn’t an available tool in this session."
The responses completed normally, with output counts 61 and 72. Thus the required-mode failure is a tool-choice contract violation, not malformed JSON or exhausted output budget. The adapter correctly rejects a message-only answer when a tool is required.

The adapter declares emulated tools in message text while sending no native definitions. Astra's observed answer treats that declaration as insufficient. Whether this behavior originates in the model or Merlin's injected instructions cannot be distinguished from these responses.

Native auto mode with the actual echo schema instead produced an upstream SSE error, so native mode is not yet a verified fallback. A previous alternating empty-array/omitted-field comparison failed in both cases; omission alone does not fix this issue.

## Client RPC clarification experiment

Added an Astra-only adapter instruction explaining that the assistant serializes a request for an external client to validate and execute; it does not invoke a tool on the inference server or claim execution. No user prompt changes or token reductions.

`logs/astra-rpc-probes.json`: two clarification variants generated correct echo call envelopes. The first variant was applied locally. `logs/astra-rpc-fix-controls.json`: chat, streamed chat, required tool and streamed required tool passed 4/4 at max_tokens=128000. 81 regression tests passed.

However, real OpenCode read tests failed: `logs/astra-rpc-opencode-read.json` and `logs/astra-rpc-opencode-read-v2.json`. Both returned a message saying the local file was inaccessible, with no tool events. The extra file-specific wording in v2 did not help and was removed. The retained clarification improves the simple tool probe but is not a verified workaround for general coding-agent use. No calls were fabricated and required tool choice was not downgraded.
