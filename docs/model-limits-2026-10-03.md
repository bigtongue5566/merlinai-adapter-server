# 模型容量與輸出上限（2026-10-03）

模型清單依 [Merlin 官方設定](https://cdn.jsdelivr.net/gh/foyer-work/cdn-files@latest/merlin_constants.json) 的 `textLLMs` 中 `archived=false` 核對，共 23 個模型。

容量來源：[models.dev API](https://models.dev/api.json) 的原廠 provider 精確模型紀錄。這些數值是 adapter 的設定容量與輸出政策，尚未驗證 Merlin 能實際使用到最大容量。

| Adapter 模型 | 來源 provider / model | Context | Input | Max output tokens |
| --- | --- | ---: | ---: | ---: |
| `claude-opus-5` | `anthropic/claude-opus-5` | 1,000,000 | 未列出 | 128,000 |
| `claude-opus-5.5` | `anthropic/claude-opus-5-5` | 1,000,000 | 未列出 | 128,000 |
| `claude-sonnet-5` | `anthropic/claude-sonnet-5` | 1,000,000 | 未列出 | 128,000 |
| `claude-sonnet-5.5` | `anthropic/claude-sonnet-5-5` | 1,000,000 | 未列出 | 128,000 |
| `deepseek-v4-flash` | `deepseek/deepseek-v4-flash` | 1,000,000 | 未列出 | 393,216 |
| `deepseek-v4-pro` | `deepseek/deepseek-v4-pro` | 1,000,000 | 未列出 | 393,216 |
| `gemini-3.1-flash-lite` | `google/gemini-3.1-flash-lite` | 1,048,576 | 未列出 | 65,536 |
| `gemini-3.8-flash` | `google/gemini-3.8-flash` | 1,048,576 | 未列出 | 65,536 |
| `glm-5.3` | `zai/glm-5.3` | 1,000,000 | 未列出 | 131,072 |
| `glm-5.3-flash` | `zai/glm-5.3-flash` | 1,000,000 | 未列出 | 131,072 |
| `gpt-5.5` | `openai/gpt-5.5` | 1,050,000 | 922,000 | 128,000 |
| `gpt-5.6-luna` | `openai/gpt-5.6-luna` | 1,050,000 | 922,000 | 128,000 |
| `gpt-5.6-sol` | `openai/gpt-5.6-sol` | 1,050,000 | 922,000 | 128,000 |
| `gpt-5.6-terra` | `openai/gpt-5.6-terra` | 1,050,000 | 922,000 | 128,000 |
| `gpt-6-astra` | `openai/gpt-6-astra` | 1,050,000 | 922,000 | 128,000 |
| `gpt-6-luna` | `openai/gpt-6-luna` | 1,050,000 | 922,000 | 128,000 |
| `gpt-6-sol` | `openai/gpt-6-sol` | 1,050,000 | 922,000 | 128,000 |
| `gpt-6.1-sol` | `openai/gpt-6.1-sol` | 1,050,000 | 922,000 | 128,000 |
| `grok-4.6` | `xai/grok-4.6` | 500,000 | 未列出 | 500,000 |
| `grok-4.7` | `xai/grok-4.7` | 500,000 | 未列出 | 500,000 |
| `kimi-k3` | `moonshotai/kimi-k3` | 1,048,576 | 未列出 | 1,048,576 |
| `minimax-m3` | `minimax/MiniMax-M3` | 1,000,000 | 未列出 | 512,000 |
| `qwen-3.8-max` | `alibaba/qwen3.8-max` | 1,000,000 | 未列出 | 131,072 |

## 本次更新

- 新增 `claude-opus-5.5`、`claude-sonnet-5.5`、`gpt-6-luna`、`gpt-6-sol`、`gpt-6.1-sol`、`grok-4.7`；原有 17 個模型仍在官方現行清單。
- DeepSeek V4 Flash／Pro 的 output：384,000 → 393,216。
- Kimi K3 的 output：131,072 → 1,048,576。
- MiniMax M3 的 context：1,048,576 → 1,000,000。

Claude 5.5 在 Merlin 的模型 ID 使用小數點，而原廠 provider 紀錄使用連字號；研究腳本僅對這兩個已核對的模型明確映射為 `claude-opus-5-5` 與 `claude-sonnet-5-5`。
命名來源：[Anthropic 模型設定文件](https://support.claude.com/en/articles/11940350-claude-code-model-configuration)。其餘僅保留既有 MiniMax／Qwen 拼字映射，不使用模糊比對。

## Adapter 行為與限制

`MODEL_LIMITS` 統一保存 context、output 與已知 input，並衍生 `/v1/models` 的 `limit` 欄位與模型輸出預設值。來源未列出獨立 input 時省略該欄位。

請求省略 `max_tokens` 或傳 null 時使用模型 output；指定相容的較小正整數則保留，超過設定上限回 422。未知模型維持 10000 預設，明確指定值仍透傳。Qwen 3.8 Max 的已驗證傳輸例外仍為：正整數預算低於 16385 時使用模型預設 131072。

Context 不會作為 Merlin 請求參數，也不依字數估算後裁切歷史或拒絕請求。實際上限仍由上游判斷，長輸入不保證能同時使用最大 output；尤其 Kimi 本次目錄的 output 等於 context，這不是可同時使用完整輸入與完整輸出的保證。

一般請求與更正仍受整體時限、回應大小及剩餘 token 預算限制。OpenCode 可能忽略 `/v1/models` 的額外 metadata，其明確模型設定與 `OPENCODE_EXPERIMENTAL_OUTPUT_TOKEN_MAX` 仍需自行配置。

## 快照與重現

機器可讀快照：[JSON](model-limits-2026-10-03.json)。其中保存容量來源與 Merlin 官方清單的下載時間、SHA-256、現行與封存模型 ID。

```bash
python scripts/research_model_limits.py --input logs/models-dev-2026-10-03.json --out logs/model-limits-refresh.json
```

研究腳本只產生報告，不自動變更執行設定。新增模型實測與清單一致性驗證見 [更新紀錄](model-validation-2026-10-03.md)；先前可靠性及 Qwen 邊界實測見 [可靠性紀錄](reliability-2026-09-20.md)。
