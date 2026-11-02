# Atlas

React + FastAPI chat with Databricks authentication, a Python agent workflow,
Genie, project retrieval, and Lakebase history. The red-and-white UI includes private conversation history, response feedback,
notes, saved responses, and an account name with an initial avatar. The composer
accepts text only.

Start with [SETUP_NEW_WORKSPACE.md](SETUP_NEW_WORKSPACE.md). Replace the five resource settings in
`app.yaml`, prepare the new database with `setup/01_create_tables.sql`, then grant
the new app's service principal access using `setup/02_grant_app.sql`.

This package contains source code and configuration placeholders. It contains no
credentials, personal chat history, installed dependencies, or old deployment
metadata. The target workspace has not been accessed or tested by this package.

The notebook workflow is implemented in `server/notebook_agent.py`. It runs in the
app process; it does not execute or automatically synchronize a workspace notebook.

For optional local development, install Python 3.11+ and Node.js 20.19+ (or a
supported newer LTS), install `requirements-dev.txt`, run `npm ci`, copy
`.env.example` to `.env`, and fill it with target-workspace values. Authenticate
the Databricks CLI under the `target-workspace` profile. Run `python -m server.run`
and `npm run dev` in separate terminals. Do not upload `.env`, `.venv`, or
`node_modules`. For hosted deployment, no local Node/Python build is required.

Checks: `python -m pytest server -q`, `npm test`, and `npm run build`.
