# Spec – AI architecture v0.1: rules, models and people

Status: draft, 2026-11-20. Applies to every stage of the app. Visual version: the "Project Model AI Architecture"
page (claude.ai artifact, private; ask the owner for the link). Memory and skills: `spec-memory-skills.md`.

## 1. Principle

Rules where the answer must be exact and repeatable. Models where the document must be read or judged. People where
the answer is decided. Every model answer becomes a fact with a source, a method (`llm`) and a confidence; rules check
it; what people approve becomes rules (via skills), so each building needs fewer model calls than the last.

Today no model is called anywhere (`llm_calls` is empty). The mapper's LLM step (`mapper/llm.py`) is a stub.

## 2. Platform: our GCP subscription first

Models are called through **Vertex AI** (renamed Gemini Enterprise Agent Platform in 2026; docs use both names), so
billing, quotas, logging and data handling stay in our GCP project.

| On Vertex AI | Notes (reported Nov 2026, check in the Model Garden console) |
|---|---|
| Claude Fable 5.2, Opus 5.5, Sonnet 5.5, Haiku 5.5 | Each must be enabled in Model Garden. Called with the Anthropic SDK's Vertex client. |
| Gemini 4 Hydrogen | Fast, low cost; the only Gemini 4 model on the free tier. |
| Gemini 4 Argon, Gemini 4 Carbon | Argon reported as limited to verified enterprise customers in some regions; Carbon access reported as limited. Promo prices end 30 Nov 2026. |
| gpt-oss 120B / 20B | OpenAI's open-weight models, served by Vertex. GPT-6.2 Astra and Sol are **not** on Vertex. |

Outside GCP, kept as an option only: **Jev** (TypeSafe AI) is not on Vertex AI or Google Cloud Marketplace; it can be
called from Cloud Run with its own API key and billing. **OpenAI GPT-6.2** only through OpenAI's API.

## 3. Who does what

USD per million tokens, input / output, as reported in Nov 2026 (third-party sources, not Google's price page).
*Default* is what we build first; *contender* runs in the bake-off (§6); *escalate* takes over when the default's
answer fails the checks.

| Job | Rules | Default model | Contender | Escalate | People |
|---|---|---|---|---|---|
| Locate the building | Geocoder | none | | | Confirm the pin |
| Floor plans: geometry | PDF lines (`vectors.py`) paired into walls | none | Vectorising model for scanned sheets | | Fix on the 2D plan |
| Floor plans: meaning | Room labels, tag patterns | Gemini 4 Hydrogen ($1.50 / $7.50) | Sonnet 5.5 ($2 / $10) | Opus 5.5 ($4 / $20) | Answer asks |
| Schedules | Layout per designer (skill rules) | Opus 5.5 drafts a layout once per firm | Argon | Fable 5.2 ($8 / $40) | Approve the layout |
| Sequences | Section and setpoint patterns | Sonnet 5.5 | Gemini 4 Hydrogen | Opus 5.5 | Confirm the logic |
| Controls submittal | Point rows, Metasys references | Gemini 4 Hydrogen (risers, odd tables) | Sonnet 5.5 | Opus 5.5 | Answer asks |
| BMS export | Columns by name | none | | Haiku 5.5 for unknown headers | |
| Point → class | Name rules, templates, conventions | Haiku 5.5 ($0.10 / $0.50) | Jev (outside GCP), gpt-oss-20b | Sonnet 5.5 | Review below the threshold |
| Same unit across documents | Tag spelling | Haiku 5.5 | Jev (outside GCP) | | Confirm |
| Auto-accept or review | Threshold | Our own calibration (isotonic, scikit-learn) on model scores | Jev's probability | | Review queue |
| Validation | SHACL, knowledge model | never a model | | | |
| 3D twin | Extrude checked walls | none | | | |
| Equipment 3D | Parametric builders | Haiku 5.5 picks the variant | Gemini 4 Hydrogen | | |
| Memory curator | Checks (§6 of memory spec) | Sonnet 5.5 | Gemini 4 Hydrogen | Opus 5.5, Fable 5.2 for rules | Approve |
| Agent, text (`spec-agent.md`) | Context engine, entity names, tool registry | Sonnet 5.5; Opus 5.5 to reason | Argon | Fable 5.2 for long tasks | Ask, correct, confirm writes |
| Agent, voice (`spec-agent.md`) | Same tools | Gemini 3.8 Live (~$0.005/min in, ~$0.018/min out) | Live 2.5 Flash native audio | `ask_expert` → Claude | Talk, interrupt, confirm |

Why these defaults: Gemini 4 Hydrogen is the cheapest strong vision model on Vertex and reads PDFs natively, so it
takes the high-volume page reading. Claude Haiku 5.5 is the cheapest per point by a wide margin for classification.
Rare, high-leverage jobs (drafting a layout once per engineering firm, a rule from corrections) use Opus 5.5, because
one good rule replaces thousands of model calls later; Fable 5.2 only when Opus fails the checks.

## 4. Provider layer

Extend `mapper/llm.py` into `src/projectmodel/ai/`:

```
ai/
  providers.py   VertexClaude, VertexGemini, VertexGptOss, Jev (optional), NoModel; one interface
  jobs.py        one entry per job in §3: default, contender, escalate, prompt id, output schema
  prompts/       one file per prompt, versioned
  log.py         every call -> llm_calls (input, output, model, cost, latency, job, prompt version)
```

- Credentials: Application Default Credentials (a service account), never a key in the repo. The hosted app builds
  its database without any model call (as `build.py` does today), from stored facts.
- Every job returns typed JSON validated against its schema; invalid output counts as a failure and escalates.
- Vision jobs always receive our candidates by id (wall segments, tag positions), and answer with ids, never with
  new coordinates.
- Batch prediction for re-reading whole document sets; context caching for the knowledge-model excerpt sent with
  every call.

## 5. People in the loop

People are a stage, not an afterthought: they answer the reader's questions during setup, review below-threshold
facts, approve rules and skills, and correct the agent. Every decision is stored with `method=human`, written to the
journal and handed to the curator (`spec-memory-skills.md`).

## 6. Bake-off before building each job

Same input, same output shape, same scorer (`intake/score.py`, `scoring/score.py`). Dev set only; Troop D's real
sheets (plans, schedules, sequences) first, since its submittal and BMS export are generated by our own code.

| Job | Contenders | Measured by |
|---|---|---|
| Floor plan meaning | Rules · Hydrogen · Sonnet 5.5 · Argon if available | Rooms and placements vs the answer key; cost per sheet |
| Schedules | Rules · Opus 5.5 layout · Argon layout · model reads every row | Row and value accuracy; cost per page; cost on the second building |
| Sequences | Rules · Sonnet 5.5 · Hydrogen · Opus 5.5 | Setpoints and steps found; links to the right points |
| Point classes | Rules · Haiku 5.5 · gpt-oss-20b · Jev | H2 overall and auto-accepted; calibration; cost per 1,000 points |
| Agent | Opus 5.5 · Fable 5.2 · Argon | Right root cause, every step cited; cost per question |

## 7. Open questions

1. Which regions and models are enabled on our GCP project (Argon and Carbon access in particular)?
2. Is calling Jev outside GCP acceptable for customer data, or GCP only?
3. A second real document package (Kelly Walsh) before trusting any accuracy number.

## 8. Sources

- Vertex AI Model Garden guide (Gemini, Claude, Gemma): https://www.workspaceblog.in/blog/model-garden-gemini-claude-gemma-model-selection/
- Introducing Claude Haiku 5.5 (Anthropic): https://www.anthropic.com/claude-haiku-5-5
- OpenAI models on Vertex AI: https://docs.cloud.google.com/vertex-ai/generative-ai/docs/maas/openai
- Gemini 4 pricing on Vertex AI: https://www.getmaxim.ai/bifrost/llm-cost-calculator/provider/vertex_ai/model/gemini-4-hydrogen
- Vertex AI pricing, Gemini 4 Argon and Claude: https://mxchat.ai/vertex-ai-pricing-gemini-claude-chatbot/
- Is Jev available on Vertex AI? (TypeSafe): https://help.typesafe.ai/articles/2088283656-is-jev-available-on-amazon-bedrock-google-vertex-ai-or-azure-foundry
- Jev with AlloyDB AI (Google Codelab): https://codelabs.developers.google.com/alloydb-ai-jev?hl=en
