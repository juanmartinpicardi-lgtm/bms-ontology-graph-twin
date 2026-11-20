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

## The agent and model calls (Vertex AI)

The agent dock and the mapper's model step call models on Vertex AI. Streamlit Cloud has no gcloud sign-in, so the
app reads a service account key from the app's **Secrets** (Streamlit's store, never git). Without it the app runs as
before, on rules only, and the dock says "Models off".

1. Create a service account with the role **Vertex AI User** in the GCP project, and a JSON key for it:

   ```bash
   gcloud iam service-accounts create projectmodel-app --display-name "Project Model app"
   gcloud projects add-iam-policy-binding PROJECT_ID \
     --member "serviceAccount:projectmodel-app@PROJECT_ID.iam.gserviceaccount.com" --role roles/aiplatform.user
   gcloud iam service-accounts keys create key.json \
     --iam-account projectmodel-app@PROJECT_ID.iam.gserviceaccount.com
   ```

2. Turn the key into TOML for the Secrets box (prints it; nothing is written):

   ```bash
   python -c "import json,sys; k=json.load(open('key.json')); print('[ai.service_account]'); [print(f'{a} = {json.dumps(b)}') for a,b in k.items()]"
   ```

3. In share.streamlit.io: the app → **Settings** → **Secrets**, paste the output, save. The app restarts. Delete
   `key.json` from your disk afterwards.
4. Check: the dock's badge shows the model (e.g. "Gemini 4 Argon · Vertex AI") instead of "Models off".

Which models answer: Claude models need enabling in Vertex AI Model Garden for the project. Until they are, the
agent answers with Gemini 4 Argon (the job's contender); the router learns that from the first "not found" and the
dock's badge names the model in use. Every call is logged with its cost in `llm_calls` (lost on restart, like the
rest of the database).

Who can open it: an app from a private repository is private by default, so only viewers you invite by email
(in the app's **Share** settings) can open it. The free plan allows one private app.

Not kept on Cloud: notes and anything else written to the database are lost when the server restarts (its disk is
temporary), and the graph is rebuilt from the blind exports.
