# Empty upstream tools compatibility

An isolated diagnostic wrapper omitted `params.tools` only when empty, keeping each model's configured output limit and all other adapter behavior unchanged. It did not modify production policy or omit actual native tool definitions.

Real upstream evidence: `logs/all-models-omit-empty-tools.json`, 17 models, chat and emulated tool modes, 31/34 passed.

- All models except MiniMax M3 passed chat without the field (16/17).
- All except GPT 6 Astra and MiniMax M3 passed the emulated tool test (15/17).
- Astra returned an answer instead of satisfying required tool choice. A separate alternating comparison, `logs/astra-empty-tools-comparison.json`, failed twice with an empty array and twice with omission for the same reason. This does not show an omission-specific regression, but does not establish successful Astra tool use either.
- MiniMax chat and tool requests both timed out after about 45 seconds. Its compatibility remains unverified; do not infer that omission caused the timeout.

These are short request tests, not long coding-task reliability measurements or verification of maximum-size outputs. Production currently retains the targeted Gemini 3.8 exception; this investigation alone does not change all models' payload policy.
