# Deploy on Streamlit Community Cloud

The app runs as is from this repository. A fresh checkout has no database (`data/*.sqlite` is not in git), so on
first start the app maps Alpha (both inputs) from `data/blind/` and stores the sequences' behaviour edges. That takes
about a minute, once per server start; rules only, no LLM key needed.

1. Sign in at https://share.streamlit.io with GitHub and allow access to private repositories.
2. **Create app** → **Deploy a public app from GitHub** (the repo itself stays private).
   - Repository: `juanmartinpicardi-lgtm/bms-ontology-graph-twin`, branch `main`
   - Main file path: `src/projectmodel/app/main.py`
3. **Advanced settings** → Python version **3.11** (pyproject requires 3.11; dependencies come from `uv.lock`).
4. Deploy. Pushing to `main` redeploys.

Who can open it: an app from a private repository is private by default, so only viewers you invite by email
(in the app's **Share** settings) can open it. The free plan allows one private app.

Not kept on Cloud: notes and anything else written to the database are lost when the server restarts (its disk is
temporary), and the graph is rebuilt from the blind exports.
