# 模型輸出上限（2026-09-20）

來源：[models.dev API](https://models.dev/api.json)。使用原廠 provider 的精確模型紀錄；這是目錄資料，不是 Merlin 上限驗證。

| Adapter 模型 | 來源 provider / model | Context | Max output tokens |
| --- | --- | ---: | ---: |
| `claude-opus-5` | `anthropic/claude-opus-5` | 1,000,000 | 128,000 |
| `claude-sonnet-5` | `anthropic/claude-sonnet-5` | 1,000,000 | 128,000 |
| `deepseek-v4-flash` | `deepseek/deepseek-v4-flash` | 1,000,000 | 384,000 |
| `deepseek-v4-pro` | `deepseek/deepseek-v4-pro` | 1,000,000 | 384,000 |
| `gemini-3.1-flash-lite` | `google/gemini-3.1-flash-lite` | 1,048,576 | 65,536 |
| `gemini-3.8-flash` | `google/gemini-3.8-flash` | 1,048,576 | 65,536 |
| `glm-5.3` | `zai/glm-5.3` | 1,000,000 | 131,072 |
| `glm-5.3-flash` | `zai/glm-5.3-flash` | 1,000,000 | 131,072 |
| `gpt-5.5` | `openai/gpt-5.5` | 1,050,000 | 128,000 |
| `gpt-5.6-luna` | `openai/gpt-5.6-luna` | 1,050,000 | 128,000 |
| `gpt-5.6-sol` | `openai/gpt-5.6-sol` | 1,050,000 | 128,000 |
| `gpt-5.6-terra` | `openai/gpt-5.6-terra` | 1,050,000 | 128,000 |
| `gpt-6-astra` | `openai/gpt-6-astra` | 1,050,000 | 128,000 |
| `grok-4.6` | `xai/grok-4.6` | 500,000 | 500,000 |
| `kimi-k3` | `moonshotai/kimi-k3` | 1,048,576 | 131,072 |
| `minimax-m3` | `minimax/MiniMax-M3` | 1,048,576 | 512,000 |
| `qwen-3.8-max` | `alibaba/qwen3.8-max` | 1,000,000 | 131,072 |

同模型不同供應商可能不同。例如 Kimi K3：Moonshot 紀錄為 131072，但 Alibaba 紀錄為 1048576；本表採原廠值，不取所有供應商最大值。

JSON 的欄位名稱是 `limit.output`，對應模型目錄的最大輸出；不代表 Merlin 接受名為 `max_output_tokens` 的欄位。此 adapter 目前接收並傳遞 `max_tokens`。

OpenCode 的 provider transform 有預設 `OUTPUT_TOKEN_MAX = 32000`。隔離測試提高上限時，同時設定模型 `limit.output` 和程序環境變數 `OPENCODE_EXPERIMENTAL_OUTPUT_TOKEN_MAX`，再檢查實際送出的 `max_tokens`。
來源：[OpenCode provider transform](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/provider/transform.ts)。

GLM 5.3 實測已確認 adapter 收到 65536／131072。131072 組完整完成一次原始場景任務，
但最高單輪只用 25111 output tokens，因此仍不能推定 Merlin 能實際產生到 131072；
詳見 [完整測試及限制](reliability-2026-09-20.md)。

Adapter 已依使用者要求將本表的 output 值設為各模型的預設值與設定上限，集中在
`merlinai_adapter_server/models_catalog.py` 的 `MODEL_LIMITS`，統一保存 context、output 與已知 input；輸出上限由此衍生。
請求省略 `max_tokens` 或傳 null 時使用模型上限；指定相容的較小值則保留（Qwen 的過低設定例外見下方）；超過設定上限回 422，
不默默裁切或增加。未知模型維持 10000 預設，明確指定值仍透傳。
此設定不是 Merlin 上限的驗證證據，也不會覆蓋上游的上下文／供應商限制。
高上限仍受 adapter 整體時限、回應大小限制及剩餘上下文約束。

可重跑：`python scripts/research_model_limits.py --input logs/models-dev-2026-09-20.json --out logs/model-limits-refresh.json`。機器可讀快照見 [JSON](model-limits-2026-09-20.json)。

`GET /v1/models` 會透過額外的 `limit` 欄位公開容量。來源未提供獨立 input 時省略該欄位。Context 是整體容量，不是傳給 Merlin 的請求參數；沒有精確 tokenizer／上游計量契約時，不依字數猜測後拒絕或裁切歷史。實際 context 是否超限仍由上游判斷，長輸入也不保證能同時使用最大 output。呼叫端可能忽略這個擴充欄位，OpenCode 明確模型設定仍需保留。

Qwen3.8 Max 的 Merlin 路由經重複實測：16384 失敗、16385 成功，因此正整數設定低於 16385 時，相容處理為模型預設 131072（原先回 422 的行為已修正）。這是已觀察到的傳輸限制，不是模型原廠的最低輸出規格。一般請求、更正與 smoke 測試統一採模型設定；更正只扣已消耗用量，不另設固定低上限。
