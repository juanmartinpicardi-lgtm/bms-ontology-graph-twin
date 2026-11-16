# Project Model

A prototype that turns engineering-tool exports and project documents into a reviewed knowledge graph of a building,
using a reusable knowledge model, and measures how good it is against ground truth.

## Open the app

**https://bms-ontology-graph-twin.streamlit.app/**

The repository is private, so the app is too: ask the owner to invite you by email (the app's **Share** settings).
It redeploys on every push to `main`. The first start after a redeploy takes about a minute.

To try the guided setup end to end: **Projects → Add a building** (locate, five documents, review, then tribal knowledge)
(https://bms-ontology-graph-twin.streamlit.app/add-building). Each step has a **Use the test file** button that loads
the matching file from [`test_packages/troop_d/`](test_packages/troop_d/README.md).

On the hosted app, buildings, answers and notes added during a session are lost when the server restarts.

## Run it locally

```bash
uv sync
.venv/bin/streamlit run src/projectmodel/app/main.py
```

## More

- [`CLAUDE.md`](CLAUDE.md): the build brief (goal, vocabulary, architecture, phase 0 tasks)
- [`docs/`](docs/README.md): feature specs
- [`docs/deploy_streamlit_cloud.md`](docs/deploy_streamlit_cloud.md): how the app is deployed
