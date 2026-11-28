# Spec – The agent v0.1: always there, sees the screen, talks, acts

Status: draft, 2026-11-20. Builds on `spec-ai-architecture.md` (models, provider layer) and `spec-memory-skills.md`
(memory, skills, journal). Vocabulary as in `CLAUDE.md` §2.

## 1. What this is

One conversational agent, present on every page of the app, that:

- **knows what you are looking at** without being told: the project, the floor, the room, the equipment, the point,
  the document page, the setup step, what is selected and which scenario is running;
- **answers** from the knowledge graph, the documents, the simulator, and the memory and skills layer, citing each
  fact with how much it can be trusted;
- **acts on the screen**: opens pages, shows a floor, selects and highlights equipment, opens a document at the right
  place, runs simulations;
- **shows things in the conversation**: charts, tables, document previews, equipment cards, a piece of the graph,
  a snapshot of the 3D view;
- **talks**: push-to-talk or a hands-free call, with Gemini Live, so "show me floor 2" or "run a sequence simulation
  for VAV-1-23" works by voice while you look at the building;
- **does longer work** in the background ("check the whole submittal against the sequences") and reports back;
- **proposes, never decides**: anything that changes data is confirmed by a person and stored as `method=human`.

It replaces the scripted Agent tour with the real thing. The tour's walk (zone → VAV → AHU → plant → chiller)
becomes the agent's `troubleshoot-warm-zone` skill.

## 2. Non-goals (for now)

- Writing to a source system on the agent's own initiative (CLAUDE.md §8: write-back only when the user asks, with a preview, a confirm and a log). The agent never commands real equipment; "simulation" always means
  our simulator (`equipment3d/sim.js`, the sequences page), clearly labelled as simulated.
- Live BMS values. They arrive with the Niagara adapter; until then every value the agent shows is simulated.
- Auth and per-user permissions (later). Writes are confirmed and attributed to a free-text name, as today.
- A free-form code interpreter in the chat. Charts and views come from a fixed catalogue of components (§7).

## 3. How it looks

```
┌ rail ┬───────────────────────── page ─────────────────────────┬──────── agent dock ────────┐
│      │  Alpha · Tree  Graph 3D  Equipment 3D  Sequences …      │ ● Alpha › Floor 2 › VAV-1-23│  context chips
│      │                                                         │   (click × to drop one)     │
│      │       the page, unchanged                               │ ─────────────────────────── │
│      │       selections in viewers feed the context            │ conversation:                │
│      │                                                         │  text, cited facts,          │
│      │                                                         │  charts, document previews,  │
│      │                                                         │  cards, action receipts      │
│      │                                                         │ ─────────────────────────── │
│      │                                                         │ [ Ask about VAV-1-23… ] 🎙 ☎ │  type · push-to-talk · call
└──────┴─────────────────────────────────────────────────────────┴─────────────────────────────┘
```

- **Dock**: on the right, on every page; collapsible to a single button; opens full width for long work. It keeps its
  conversation across page changes.
- **Context chips** at the top: what the agent will use. Selecting something on the page adds or replaces a chip;
  the person can drop a chip with ×, or pin one so it survives navigation.
- **Action receipts**: every screen action the agent takes appears as a small line ("Opened Equipment 3D ·
  VAV-1-23 · scenario Chilled water running warm") with Undo (go back).
- **Voice**: 🎙 push-to-talk; ☎ starts a call (hands-free, interruptible). A live transcript shows in the dock; the
  agent's spoken answer and its on-screen actions happen together.
- **Ask about this**: right-click (or long-press) on any node, point, room, page region or chart opens the dock with
  that thing as the context.

## 4. Context engine: what the agent sees

Every page publishes a **screen state**; the dock turns it into a **context packet** for each turn. Built by rules,
deterministic, cheap: no model decides what the context is.

### 4.1 Screen state (published by the page)

```json
{
  "page": "Equipment_3D",
  "project": "alpha/names_paths",
  "level": "equipment",
  "focus": {"kind": "equipment", "id": "eq:Airside VAV-1-23", "label": "VAV-1-23"},
  "selection": [{"kind": "point", "id": "pt:...ZN-T", "label": "Zone temp"}],
  "view": {"mode": "3d", "floor": "L2", "camera": "hero", "layers": ["labels"]},
  "scenario": {"key": "chw_warm", "running_for_s": 412},
  "document": null,
  "setup_step": null
}
```

Sources: the page's query parameters (already used: `project`, `equip`, `scenario`), the viewers' click events
(already sent through `app/bridge.py`), the tree's selected row, the document viewer's page and box, the setup step.

### 4.2 Context levels

| Level | Comes from | Packet adds | Example asks |
|---|---|---|---|
| General | Overview, Shared knowledge | Global memory, knowledge model summary | "What is a fan-powered VAV?" "Compare Alpha and Troop D." |
| Project | Any project page | Project summary (sizes, completeness, review backlog), site memory | "What is still missing before this graph is complete?" |
| Floor | Digital twin, floor plan | Rooms, zones and units on the floor, what serves them | "Show me floor 2." "Which zones here are served by AHU-2?" |
| Room or zone | Twin, plan, tree | The zone's VAV, its chain upstream, notes | "Why is 2-14 warm?" |
| Equipment | Equipment 3D, tree, graph | `describe` result, template fit, missing points, sequence sections | "Run a sequence simulation for this." "What feeds it?" |
| Point | Tree row, 3D label | Class, provenance, trust, simulated value | "Where did this class come from?" "Plot it under the warm-CHW scenario." |
| Document | Setup step, provenance click | The page image, the facts read from it with boxes | "What is this symbol?" "Which units on this sheet have no schedule row?" |
| Setup step | Add a building | The step's facts, open questions, reading log | "Why are you asking me this?" "Accept all rooms above 90%." |
| Review | Review screen | Selected proposals, their confidences | "Accept every supply air temperature on AHU-2." |

The packet is small: ids, labels and short summaries (a few hundred tokens). The agent fetches anything more with
tools. Memory for the project's scopes and the person's profile come from the memory layer (`spec-memory-skills.md`
§7).

### 4.3 Seeing the screen

For questions about what is drawn ("what is that red thing?"), the dock can attach a **snapshot** of the active
viewer (the 3D and plan viewers already render with `preserveDrawingBuffer`). Sent only when the question needs it, to
Gemini 4 Hydrogen (text agent) or as a frame to Gemini Live (voice). Never a continuous screen stream by default:
Live sessions with video are limited and cost more.

## 5. Two brains, one set of tools

```
          voice                                  text
   ┌───────────────────┐                ┌───────────────────────┐
   │ Gemini 3.8 Live    │  ask_expert →  │ Claude (Vertex AI)     │
   │ talks, listens,    │ ◄── answer ──  │ Sonnet 5.5 by default  │
   │ fast UI commands   │                │ Opus 5.5 to reason     │
   └─────────┬─────────┘                │ Fable 5.2 long tasks    │
             │                           └───────────┬───────────┘
             └──────────────┬──────────────────────────┘
                            ▼
              Tool registry (agent service, §6)
     read graph · drive the screen · simulate · show in chat · propose
```

| Role | Model (Vertex AI) | Why |
|---|---|---|
| Voice: listen, talk, run fast tools | **Gemini 3.8 Live** (`gemini-3.8-live`); Extended Thinking variant for harder spoken questions | Native audio, interruptible, 97 languages; tool calls run in the background while it keeps talking. About $0.005/min audio in, $0.018/min out (reported) |
| Text chat, default | **Claude Sonnet 5.5** | Good tool use at $2 / $10 |
| Reasoning: troubleshooting, cross-document checks | **Claude Opus 5.5** | Multi-hop over the graph with citations |
| Long background tasks | **Claude Fable 5.2** | Hours-long, many-step work; rare |
| Name to entity ("VAV 123") | Rules first (fuzzy match on tags and labels); Haiku 5.5 only when ambiguous | Fast, cheap, same answer every time |
| Snapshot and photo questions | **Gemini 4 Hydrogen** | Cheapest strong vision on Vertex |

Routing: the text agent starts on Sonnet 5.5. It hands over to Opus 5.5 when the turn needs more than a few tool
hops or the person asks to "think about it"; long tasks become background jobs on Fable 5.2. The voice agent handles
navigation and simple lookups itself and calls `ask_expert` for anything that needs reasoning, saying a short filler
("Let me check the chain upstream") while Claude works; the answer is spoken and shown in the dock.

Both brains share one conversation record (in the journal), one context packet, one memory and one tool registry, so
a person can switch from voice to text mid-task.

To confirm before building: `gemini-3.8-live` appears in the Vertex AI Live API docs, but one Google page says Live
3.x models are not on Vertex yet. If so, voice starts on the Gemini API with our GCP project's key, or on
`gemini-live-2.5-flash-native-audio` on Vertex.

## 6. Tools

One registry in the agent service, described once (name, description, JSON schema) and given to both brains, and
exposed as an **MCP server** so other agents (Claude, Gemini Enterprise) can use the twin too.

| Group | Tools | Runs | Notes |
|---|---|---|---|
| Read the graph | `find_nodes`, `describe`, `upstream`, `downstream`, `behaviour` | Server | Exist in `agent_tools.py`; every fact has `trust` |
| | `resolve(text)` | Server | "VAV 123" → candidates with scores; asks when two are close |
| | `provenance(fact)`, `search_documents(query)` | Server | Source page and box; full-text over what the readers extracted |
| | `project_status`, `review_queue` | Server | Completeness (graph standard), what waits for review |
| Memory | `memory_search`, `skill_view`, `journal_search` | Server | From `spec-memory-skills.md` |
| Drive the screen | `navigate(page, params)`, `show_floor(level)`, `select(ids)`, `highlight(ids)`, `focus(id)`, `set_view(mode, layers)`, `open_document(file, page, box)` | Browser | Each returns a receipt; Undo goes back |
| Simulate | `run_scenario(equipment, scenario, speed)`, `run_sequence(equipment, section)`, `what_if(setpoint change)` | Browser (sim.js, sequences page) | Results streamed back as events the agent can read and plot; always labelled simulated |
| Show in chat | `chart`, `table`, `document_preview`, `entity_card`, `graph_view`, `snapshot` | Dock | From the component catalogue (§7) |
| Propose (writes) | `propose_review(decisions)`, `add_note`, `propose_memory` | Server | Shown as a card with Confirm; stored `method=human` with `assisted_by=agent` |
| Background | `start_task(goal)`, `task_status` | Server | Long jobs with progress in the dock |

Voice example, "run a sequence simulation for VAV 123":

1. Gemini Live calls `resolve("VAV 123")` → VAV-1-23 (one clear match; otherwise it asks which one).
2. It calls `navigate("sequences", {project, start: VAV-1-23, mode: "simulate"})` and `run_sequence(...)`, and says
   "Opening the sequence for VAV-1-23 and starting the simulation" while the page changes.
3. The simulator streams state changes; the agent narrates the important ones ("Cooling: damper opening to maximum
   airflow") and the dock shows a chart of zone temperature, setpoint and airflow.

## 7. What the chat can show

The agent answers in text plus **components**, as a declarative description the dock renders (the A2UI pattern:
the agent says *what* to show, our catalogue decides *how*). No agent-written code runs in the page.

| Component | Shows | Built on |
|---|---|---|
| `chart` | Time series, bars, scatter from simulated values or graph counts | Vega-Lite spec, validated, app colours |
| `table` | Points, equipment, review items, with actions per row | The app's table style |
| `document_preview` | A page of a project document with boxes drawn on it | `intake/pdfdoc.py` page images |
| `entity_card` | Equipment or point: class, trust, source, key values, buttons (open, simulate, ask) | |
| `graph_view` | A small neighbourhood of the graph | The graph viewer, embedded |
| `snapshot` | A still of the 3D or plan view, with highlights | The viewers' own renderers |
| `plan` | A step-by-step plan for a background task, with progress | |
| `confirm` | A proposed change with Confirm and Edit | |

Streaming to the dock follows the AG-UI event pattern (text deltas, tool calls, component messages, state updates),
so the front end can change later without changing the agent.

## 8. Proactive, not pushy

The agent may offer, never interrupt a call or a review:

- When a setup step finishes with open questions: "12 questions on the plans; the 5 room ones I can answer from the
  submittal. Show?"
- When a running scenario pushes a zone out of range: "3 zones on floor 2 can't reach setpoint in this scenario."
- When the person repeats a fix (from the memory layer): "This is the 3rd time; propose a rule?"

Offers appear as a quiet line in the dock, at most one at a time, dismissible, and are recorded in the journal so the
curator learns which help is welcome.

## 9. Trust and safety

- Every factual sentence links to its fact; the trust words come from `agent_tools.py` (`verified`, `stated`,
  `likely`, `unsure`), and the dock colours them.
- Simulated values are always labelled. The agent never says a building *is* doing something it only simulated.
- Writes only through `propose_*` tools, each confirmed by a person (a click, or a clear spoken "yes" that the
  transcript shows).
- Voice audio is not stored; transcripts are stored in the journal and can be deleted by their owner.
- Every model call logged (input, output, cost, latency) as CLAUDE.md requires; every tool call logged with its
  arguments and receipt.
- Content in documents is data, not instructions: text read from a PDF that addresses the agent is quoted, never
  obeyed.

## 10. Where it runs

| Part | Prototype (now) | Production |
|---|---|---|
| Dock and voice | A Streamlit custom component (the same `components.v2` mechanism as `THEME_WATCH_JS`), mounted in the rail so it survives page changes | A React front end; the 3D, plan, graph and sequence viewers are already standalone HTML/JS and move over unchanged |
| Agent service | A small FastAPI service next to the app (Cloud Run on GCP), holding the tool registry, the Claude calls (Anthropic Vertex client) and the conversation | Same |
| Voice connection | Browser to Gemini Live directly over WebSocket, with a short-lived token minted by the agent service; tool calls forwarded to the agent service or run in the page | Same |
| Screen actions | Query parameters and session state (the deep links that already exist), applied by a rerun | Client-side routing, no reload |

Streamlit reruns the page on every interaction and was not built for a streaming, always-on side panel. It is fine
to prove the agent. For an app that feels like a frontier product, the shell moves to a React front end once A5 works
(decision gate in §11).

## 11. Build phases

| # | Phase | Done when |
|---|---|---|
| A1 | **Context engine.** Screen state from every page; context chips in a dock | Chips are right on every page; selecting in a viewer or the tree updates them within a second |
| A2 | **Text agent.** Agent service, Sonnet 5.5 on Vertex, read tools, citations, streaming, journal | Answers "Why is zone 2-14 warm?" live, every step cited, cost logged |
| A3 | **Screen actions.** `navigate`, `show_floor`, `select`, `highlight`, `open_document`, receipts with Undo | "Show me floor 2" by text opens the twin on floor 2 |
| A4 | **Components in chat.** `chart`, `table`, `document_preview`, `entity_card`, `snapshot` | "Plot zone temperature against setpoint for VAV-2-14 under the warm-CHW scenario" draws the chart in the dock |
| A5 | **Voice.** Gemini 3.8 Live, push-to-talk and call, same tools, `ask_expert` to Claude | Both example commands work by voice, with the screen changing within 2 seconds of the end of speech |
| A6 | **Simulation tools.** `run_scenario`, `run_sequence`, `what_if`, results streamed back | "Run a sequence simulation for VAV-1-23" steps through the sequence with values and a chart |
| A7 | **Proposals, background tasks, proactive offers, MCP server** | A review accepted by voice is stored as `method=human`; a background check of a submittal reports with citations |
| A8 | **Decision gate: front end.** Measure rerun latency and dock behaviour in Streamlit | Decide to stay or move the shell to React |

## 12. Open questions

1. Gemini 3.8 Live on Vertex AI in our region, or the Gemini API with our project's key (§5)?
2. Languages: English first; which others do our engineers need on site?
3. Wake word or button only? Button only proposed (privacy, false triggers).
4. Should the agent be allowed to start a long background task by voice without a confirmation?
5. Mobile and tablet on site (camera of a nameplate, voice while walking the plant): after A5?

## 13. Sources

- Gemini Live API on Vertex AI, configure capabilities: https://docs.cloud.google.com/vertex-ai/generative-ai/docs/live-api/configure-gemini-capabilities
- Gemini Live API reference: https://docs.cloud.google.com/vertex-ai/generative-ai/docs/model-reference/multimodal-live
- Firebase AI Logic, Live API (model availability by provider): https://firebase.google.com/docs/ai-logic/live-api
- Gemini 3.8 Live: features, pricing, access (DataCamp): https://www.datacamp.com/blog/gemini-3-8-live
- Gemini Live API pricing per minute (Cekura): https://www.cekura.ai/blogs/gemini-live-api-pricing
- A2UI 1.0 (Google Developers Blog): https://developers.googleblog.com/en/a2ui-10-build-delightful-fast-reliable-agentic-experiences/
- AG-UI and A2UI explained (CopilotKit): https://copilotkit.ai/blog/ag-ui-and-a2ui-explained-how-the-emerging-agentic-stack-fits-together
