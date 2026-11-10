# Local lanes with Ollama

jumplane can route work to any model a local [Ollama](https://ollama.com) server lists. It starts `ollama run <model>` and never loads weights itself, so dense and mixture-of-experts models take the same path. No other local runtime is supported: the rules accept the hosts `claude`, `codex` and `ollama` only.

## What `init` does

`jumplane init` asks `http://127.0.0.1:11434/api/tags` which models the server holds. It leaves out tags ending in `:cloud` (which run remotely) and embedding models. It proposes one lane, `ollama-light`, in class light, using `--local-model <tag>` or else the first model listed. `init --accept` marks that lane verified, because the listing showed the model.

A local lane stays open while its model appeared at the last probe. Run `jumplane init` again after adding or removing a model; without `--accept` it updates the probe and leaves the rules alone. `pick` never contacts Ollama.

## Add more local lanes

Edit `rules.json` in the state folder and add a lane per model, in any class. Lanes inside a class are tried in file order. For example, to put a 27B model in class standard ahead of the hosted lanes:

```json
{"id": "ollama-standard", "host": "ollama", "model": "qwen3.8:27b", "effort": "default", "class": "standard", "pool": "ollama"}
```

Then verify it once, which launches the model with a short prompt:

```bash
jumplane verify ollama-standard
```

jumplane does not guess a class from a model name. You choose it.

## Five models checked on one PC

On 10 Nov 2026, rules with five local lanes were written to a scratch state folder and each lane was verified. `pick` then returned a local lane for light, standard and strong work. PC: RTX 4070 Super with 12 GB, Ollama 0.40.13, Windows 11.

| Ollama tag | Kind, from the publisher's card | Publisher's score, not reproduced | `jumplane verify` |
|---|---|---|---|
| `qwen3.5:9b` | 9B; the card does not say dense or mixture-of-experts for this size | LiveCodeBench v6 65.6 ([card](https://huggingface.co/Qwen/Qwen3.5-9B)) | verified, 24 s |
| `gemma4:12b` | Dense, 11.95B | LiveCodeBench v6 72.0% ([card](https://huggingface.co/google/gemma-4-12b-it)) | verified, 19 s |
| `gpt-oss:20b` | Mixture-of-experts, 21B with 3.6B active | SWE-bench Verified 53.2 at medium reasoning ([card](https://huggingface.co/openai/gpt-oss-20b)) | verified, 22 s |
| `qwen3.8:27b` | Dense, 27B | LiveCodeBench v6 90.3 ([card](https://huggingface.co/Qwen/Qwen3.8-27B)) | verified, 53 s |
| `qwen3.6:35b-a3b-coding-mtp-q4_K_M` | Mixture-of-experts, 35B with 3B active, 256 experts | SWE-bench Verified 73.4 ([card](https://huggingface.co/Qwen/Qwen3.6-35B-A3B)) | verified, 38 s |

How to read the table:

- Each score is the publisher's own figure for the full-precision model. jumplane has reproduced none of them, and no independent leaderboard was read.
- The local builds are quantised. The last tag is a community 4-bit build whose match to the card was not checked. A quantised build can score lower.
- "Verified" means the model answered one short prompt with exit 0 when jumplane launched it. It says nothing about quality.
- All five cards list the Apache-2.0 licence.
- The scores were read from the linked cards through an automated page summary on 10 Nov 2026. Recheck a score at its card before relying on it.

## Launch with stdin closed

`ollama run` waits on an open piped stdin. With stdin closed a run took 11 s; with it open, 51 s. Every `pick` answer says `"stdin": "closed"`, and [the guide](guide.md#6-launch-the-command-with-stdin-closed) shows how to launch that way.
