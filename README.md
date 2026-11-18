# Messy Enterprise App + LangChain Agent (workshop)

| Folder | What |
|---|---|
| `legacy-shop/` | Deliberately ugly Java/Quarkus e-commerce API. `docker compose up --build` |
| `shopmaster-agent/` | The LangChain agent, tools, MCP server and Streamlit chat UI (Python). `docker compose up --build` in this folder starts the shop **and** the agent |

Start with `legacy-shop/README.md` (it lists every intentional quirk), then `shopmaster-agent/README.md`.
