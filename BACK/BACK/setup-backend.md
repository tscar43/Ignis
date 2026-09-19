# Setup: Backend & Routing

Do this before writing any code. It takes about 30 minutes.

**Your branch:** `routing-backend`
**Your folders:** `backend/main.py`, `backend/routing/`, `backend/shelters/`, `demo_data/shelters.json`, the cached road graph

---

## Checklist

- [ ] VS Code extensions installed
- [ ] AI agent installed and signed in (Codex or Claude Code)
- [ ] GitHub CLI signed in
- [ ] MCP servers added to your agent
- [ ] Repo cloned, on your branch
- [ ] `.env` and `.gitignore` in place
- [ ] Your folder's `AGENTS.md` created
- [ ] Python environment working, FastAPI running

---

## 1. VS Code extensions

Paste into a terminal (or search each name in the Extensions panel if an ID doesn't work):

```bash
# Everyone
code --install-extension eamodio.gitlens
code --install-extension GitHub.vscode-pull-request-github
code --install-extension usernamehw.errorlens
code --install-extension ms-vsliveshare.vsliveshare

# Your role
code --install-extension ms-python.python
code --install-extension ms-python.vscode-pylance
code --install-extension charliermarsh.ruff
code --install-extension rangav.vscode-thunder-client
code --install-extension humao.rest-client
code --install-extension jumpinjackie.vscode-map-preview
code --install-extension ms-toolsai.jupyter
```

What they're for: Thunder Client or REST Client to test your endpoints (pick one; REST Client saves requests as files you can commit for teammates), Map Preview to check route GeoJSON, Jupyter for experimenting with the road graph.

## 2. AI agent

**If you're on ChatGPT Pro:** install the **Codex** extension from the VS Code marketplace (publisher: OpenAI) and sign in with your ChatGPT account. Codex reads `AGENTS.md` files automatically.

**If you're on Claude Pro:** install **Claude Code** (`anthropic.claude-code`) and sign in. Claude Code reads `CLAUDE.md`, so create a `CLAUDE.md` next to each `AGENTS.md` containing only this line:

```
@AGENTS.md
```

## 3. GitHub CLI

Install from https://cli.github.com, then:

```bash
gh auth login
```

## 4. MCP servers

**Context7** gives your agent current docs (important for OSMnx, which changed its API across versions).

Codex: add to `~/.codex/config.toml`

```toml
[mcp_servers.context7]
command = "npx"
args = ["-y", "@upstash/context7-mcp"]
```

Claude Code:

```bash
claude mcp add --transport http context7 https://mcp.context7.com/mcp
```

Requires Node.js. Restart your agent after adding. If a command errors, check the server's current setup instructions.

## 5. Repo and branch

You're the natural owner of repo-wide setup, so if the repo doesn't exist yet, create it and add the other two as collaborators.

```bash
git clone <repo-url>
cd wildfire-agent
git checkout -b routing-backend
```

**Workflow:** commit small, push often, open a PR into `main`, let CI pass, merge. Pull `main` into your branch several times a day.

## 6. Secrets and .gitignore

Make sure the root `.gitignore` includes at least:

```
.env
.venv/
__pycache__/
node_modules/
*.tif
*.tiff
*.graphml
```

(If the team decides to commit a small cached graph for the demo, remove `*.graphml` and keep the file small.)

Create `.env`:

```
LLM_API_KEY=your_key_here
```

The frontend teammate's agent runs behind your `/chat` endpoint, so the LLM key lives on the backend. **Never commit `.env`.**

## 7. Your folder's AGENTS.md

Create `backend/routing/AGENTS.md`:

```markdown
# Backend & routing agent rules

- Only edit backend/main.py, backend/routing/, backend/shelters/, and demo_data/shelters.json.
- backend/agent/ belongs to the frontend teammate; don't edit it.
- Never edit contracts/ without the team agreeing first. Use Pydantic models that match contracts/.
- Units: minutes and kilometers. Geometry: EPSG:4326 GeoJSON.
- Risk bands are cumulative; score each edge by the most severe band it touches.
- Load the road graph from the local cache; never call Overpass at runtime.
- Keep CORS enabled for the frontend dev server.
- Never commit .env or large files.
- Before pushing: run pytest.
```

(Claude Code: add `backend/routing/CLAUDE.md` with `@AGENTS.md`.)

## 8. Python environment

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install fastapi uvicorn pydantic osmnx networkx geopandas shapely scikit-learn httpx pytest
```

Select `.venv` as the interpreter in VS Code. You own the shared requirements file; the geospatial teammate will add their dependencies through PRs.

Test it:

```bash
uvicorn backend.main:app --reload
```

Then open http://localhost:8000/docs to see FastAPI's built-in API page.

## 9. CI (you set this up for the team)

Add a GitHub Actions workflow in `.github/workflows/` that runs on every PR: install dependencies, run `pytest`, and validate the `demo_data/` files against `contracts/`. Your agent can write this; ask it to keep it fast.

---

**First task after setup:** get a route between two points returned as GeoJSON, and send it to the frontend teammate.
