# Grok 4.7 ends after a tool preamble

The supplied OpenCode v2 session contained one assistant text response announcing workspace inspection, `finish=stop`, and no tool events. An isolated OpenCode 2.0.24 reproduction with the unchanged rainy-store prompt reproduced the failure in 10.22 seconds. Captured Merlin answer text was only the preamble: no tool call was lost in translation. The adapter's auto-choice plain-answer fallback accepted it as a final answer.

For `grok-4.7` requests with emulated tools, require the complete adapter envelope instead of accepting unframed plain text. Missing envelopes enter the existing one-attempt correction flow, sharing the remaining output budget. A second malformed response fails explicitly. Ordinary chat without tools and valid message envelopes remain supported; no semantic guessing, invented calls, or forced execution is added. This does not detect an unfinished plan inside a valid message envelope.

Evidence under ignored logs:

- `opencode-scene-e2e-grok47-debug-a1`: unchanged baseline, one request, zero tool calls and no files.
- `opencode-scene-e2e-grok47-debug-b1`: first preamble corrected into `glob`, second into `write`; both executed successfully and `index.html` was created. A later upstream request reached the diagnostic 120-second completion timeout. OpenCode retried; the isolated test was deliberately stopped. The scene was not completed or visually verified.
- Both runs used model output/context limits of 500000 and prompt SHA-256 `9a60c4499055745812975984a1554837dff96d91a5b560a984ac408bff792cc3`.
- 84 local tests passed, including recovery, repeated-invalid-response failure, normal chat and explicit final-message compatibility in both response modes. Compile and diff checks passed.

The scene harness now detects OpenCode v2 and uses `--standalone` with the subprocess working directory instead of v1-only `--pure`/`--dir`. Equal model context/output metadata is accepted; the actual client remains responsible for input headroom.

Changes are local only. No NAS deployment or user session modification was performed.
