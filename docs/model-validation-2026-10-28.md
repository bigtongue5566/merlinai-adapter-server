# Model catalog validation — 2026-10-28

Merlin official configuration publishes 18 active text models. Added `claude-haiku-5.5` and `gemini-4-argon`; removed seven archived IDs from `/v1/models`. Unknown/archived IDs retain the existing pass-through behavior and generic budget; no aliases are invented.

Limits were refreshed from exact first-party provider records in [models.dev](https://models.dev/api.json). These metadata and configured budgets do not prove Merlin can deliver the full advertised capacity.

| Model | Context | Input (if specified) | Output |
|---|---:|---:|---:|
| `claude-haiku-5.5` | 1000000 | — | 128000 |
| `claude-opus-5.5` | 1000000 | — | 128000 |
| `claude-sonnet-5.5` | 1000000 | — | 128000 |
| `deepseek-v4-flash` | 1048576 | — | 393216 |
| `deepseek-v4-pro` | 1048576 | — | 393216 |
| `gemini-3.1-flash-lite` | 1048576 | — | 65536 |
| `gemini-3.8-flash` | 1048576 | — | 65536 |
| `gemini-4-argon` | 1048576 | — | 32768 |
| `glm-5.3` | 1000000 | — | 131072 |
| `glm-5.3-flash` | 1000000 | — | 131072 |
| `gpt-6-astra` | 1050000 | 922000 | 128000 |
| `gpt-6-luna` | 1050000 | 922000 | 128000 |
| `gpt-6-sol` | 1050000 | 922000 | 128000 |
| `gpt-6.1-sol` | 1050000 | 922000 | 128000 |
| `grok-4.7` | 500000 | — | 500000 |
| `kimi-k3` | 1048576 | — | 1048576 |
| `minimax-m3` | 1000000 | — | 524288 |
| `qwen-3.8-max` | 1000000 | — | 131072 |

Validation: 99 offline tests passed, including catalog/snapshot equality, transport budgets, streaming and tool behavior. Real upstream smoke tests: Claude Haiku 5.5 passed chat, streaming chat, required tool, streaming required tool (4/4). Gemini 4 Argon failed all four probes with upstream `INTERNAL_SERVER_ERROR`; a minimal raw transport probe failed both with and without an empty tools array. This is a published model with an unavailable upstream route in these tests, not a verified working model. Existing provider limits changed for DeepSeek v4 context (1,048,576) and MiniMax M3 output (524,288).

Sources: [Merlin official constants](https://cdn.jsdelivr.net/gh/foyer-work/cdn-files@latest/merlin_constants.json), [models.dev](https://models.dev/api.json). Source hashes and exact provider mappings are retained in the adjacent dated JSON snapshots. Credentials and raw reasoning are excluded.
