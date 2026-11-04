# Atlas

React + FastAPI contract chat with Databricks authentication and Lakebase history.
The backend implements the supplied ContractRAGAgent notebook: embed the latest
question, retrieve contract excerpts with HYBRID search, then generate an answer.
Genie and AI Gateway are not used by this version.

For an existing installation, follow [UPGRADE_CONTRACT_RAG.md](UPGRADE_CONTRACT_RAG.md).
For a fresh workspace, follow [SETUP_NEW_WORKSPACE.md](SETUP_NEW_WORKSPACE.md).

The red-and-white UI keeps private conversation history, feedback, notes, saved
responses, and the signed-in user's name and initial avatar. The composer accepts
text only. Answers contain natural prose; source metadata is returned separately
as assistant.custom_outputs and saved in the existing atlas_tool_runs table.

The notebook logic lives in server/notebook_agent.py and runs inside the app.
Editing the original workspace notebook does not automatically update this code.
No notebook job or separate MLflow agent deployment is required. The original
MLflow decorators/model registration are replaced by the app's request handling
and saved metadata; this port does not create MLflow tracing spans.

Configuration uses DATABRICKS_CONTRACT_INDEX, DATABRICKS_EMBEDDING_ENDPOINT,
DATABRICKS_ANSWER_ENDPOINT and LAKEBASE_ENDPOINT. Repository configuration is a
template. Never place credentials in app.yaml or VITE_* variables.

For optional local development, install Python 3.11+ and Node.js 20.19+ (or a
supported newer LTS), install requirements-dev.txt, run npm ci, copy .env.example
to .env, and configure the target workspace. Authenticate the Databricks CLI
under the target-workspace profile. Run python -m server.run and npm run dev
in separate terminals. Do not upload .env, .venv, or node_modules.

Checks: python -m pytest server -q, npm test, npm run build.
The target workspace's resources and permissions need a live test after deployment.
