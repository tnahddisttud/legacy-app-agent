# ShopMaster Agent

A LangChain agent (built with `create_agent`) that talks to the deliberately messy ShopMaster API (`../legacy-shop`).
Built for beginners: small files, one idea each.

## Quick start with Docker (one command)

```bash
cp .env.example .env         # (Windows: copy .env.example .env) then put your GROQ_API_KEY in it
docker compose up --build    # starts the legacy shop AND the agent's chat UI
```

Open **http://localhost:8501**. The agent waits until the shop is healthy before it starts.

```bash
docker compose down                                  # stop everything
docker compose down -v                               # ...and reset the shop's data
docker compose run --rm agent python run_agent.py    # chat in the terminal instead of the browser
```

- Same on every machine: Python and every package version are pinned (`Dockerfile` + `uv.lock`).
- Your keys stay out of the image. `.env` is read when the container starts, and `.dockerignore` keeps it out of the build.
- Inside Docker the shop is `http://legacy-shop:8080/legacy`; `docker-compose.yml` sets that for you.
- Already running the shop by hand from `../legacy-shop`? Stop it first, or you get *"container name /legacy-shop is
  already in use"* (both also want port 8080): `cd ../legacy-shop && docker compose down` (no `-v`, so its data is kept).
- `docker compose config` prints your `.env` values in clear text, so don't paste its output anywhere.

## Setup without Docker for the agent (10 minutes)

For editing the code and running the tests. The shop still runs in Docker.

```bash
# 1. Start the legacy shop (in another terminal)
cd ../legacy-shop && docker compose up --build

# 2. Python environment (needs uv: https://docs.astral.sh/uv/)
cd ../shopmaster-agent
uv sync                     # creates .venv and installs the locked dependencies

# 3. Settings
cp .env.example .env        # (Windows: copy .env.example .env) then fill in GROQ_API_KEY, LLM_MODEL, (optional) GOOGLE_API_KEY, LangSmith keys

# 4. Check everything is connected
uv run healthcheck.py
```

No LLM key yet? `uv run pytest` still works: the tests use a fake shop and a scripted fake LLM.

## Run it

```bash
uv run run_agent.py            # tools are plain Python functions
uv run run_agent.py --mcp      # same tools, served by an MCP server over stdio
uv run show_tool_schemas.py    # see exactly what the LLM is told about each tool
uv run streamlit run app.py    # the same agent in a browser chat (http://localhost:8501)
```

In the browser UI you see each tool the agent calls (lists come back as tables), the final answer, and
**Approve / Reject** buttons whenever the agent wants to change data. The sidebar has a "New chat" button
and the example questions below.

Things to try:
- `Do you have wireless mice under $50?`
- `Is SKU-1004 in stock?`  (duplicate SKU in the shop: watch for the warning)
- `Show me the orders of john.khan0@example.com`
- `Order 2 of SKU-1001 for customer 3`  (the agent pauses and asks YOU to approve)
- `Cancel order ORD-000002`  (approval again; maybe an invalid transition)

## How it fits together

```
pyproject.toml       <- dependencies (uv.lock pins exact versions)
pyproject.toml       <- dependencies (uv.lock pins the exact versions)
shopmaster/          <- everything about the ugly API. No LLM in here.
  client.py            login, 5-min token, rate limit, retries, 5 response formats
  parsers.py           messy values -> clean values (prices, dates, booleans, phones...)
  models.py            clean typed data (Pydantic)
  operations.py        the 8 operations = the 8 tools (schema from type hints, description from docstring)
  envelope.py          every tool returns {"ok": ..., "data"/"error": ...} and never raises
tools/shop.py        <- turns operations into LangChain tools
mcp_server/server.py <- turns the SAME operations into an MCP server
agent/               <- the agent
  agent.py             one create_agent() call: prompt + approval middleware + structured AgentAnswer
  llm.py               the model
prompts/system.md    <- the system prompt (plain Markdown, easy to edit)
run_agent.py         <- terminal chat
app.py               <- browser chat (Streamlit): same agent, nicer display
tests/               <- 68 tests, no network and no API key needed
```

The one rule: **clean the mess in code, let the LLM do the thinking.** The LLM never sees `$24.50`, `Y`/`0`/`true`,
XML, CSV, or magic status numbers. It sees clean JSON and clear error codes.

## Fallback model (optional)

The main model is gpt-oss on Groq. Put a free Google AI Studio key in `GOOGLE_API_KEY` and `ModelFallbackMiddleware`
sends a model call to Gemma (`gemma-4-31b-it`, set `FALLBACK_MODEL` to change it) when the Groq call fails:
rate limit, daily token limit, or a broken tool call. No key = no fallback, the agent works as before.
`uv run healthcheck.py` tests both models, and the browser UI shows which model wrote each answer.

## Safety: why writes need approval

`create_order` and `update_order_status` are *write* tools. `HumanInTheLoopMiddleware` pauses the agent before any write tool runs
and waits for a human to approve or reject. It's enforced in code, so no prompt can bypass it.
`order-status.do` even changes data over GET: we classify tools by what they DO, not by HTTP verb.

## Failure drills (turn the chaos up)

Edit `../legacy-shop/docker-compose.yml`, then `docker compose up -d`:

| Setting | What you'll see |
|---|---|
| `SHOP_TOKEN_TTL_SEC: "20"` | token expires mid-chat; the client logs in again, invisibly |
| `SHOP_RATE_MAX: "5"` | 503s; the client waits as the server asks |
| `SHOP_CHAOS_ERROR_RATE: "0.4"` | random HTML 500s; reads are retried |
| `SHOP_CHAOS_POST_COMMIT_ERROR_RATE: "0.5"` | order SAVED but answered with 500; no duplicate order is created |

Then open LangSmith (project `shopmaster-agent`) and read the traces.

## Tests

```bash
uv run pytest                          # 68 offline tests
uv run pytest tests/test_live_api.py   # 6 tests against the real running shop (skipped if it's down)
```

## Known simplifications
- No loop guard beyond `recursion_limit=25` (a stretch exercise: stop after the same failing call 3 times).
- Approval is a terminal prompt. A real app would surface it through an API endpoint.
- The create-order duplicate check compares order counts for that customer; two simultaneous orders for the
  same customer could fool it. Real systems use idempotency keys, which this API doesn't offer.
