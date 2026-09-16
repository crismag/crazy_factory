# Factory Seed

Goal:
build a habit tracker

Constraints:
- Python 3 standard library only (http.server, pathlib, json).
- No npm, no frameworks, no database server.
- Persist application data as JSON under data/.
- Keep the implementation small and testable.
- Serve a usable HTML UI on localhost.

Known Context:
Single-user local app. No accounts, no cloud.
Screens: home, list, detail.
Data: JSON file under data/.

Success:
- A person can use the habit tracker UI in a browser on localhost.
- Core create / list / update / delete flows work without placeholders.
- Data persists across process restart (JSON under data/).
- python3 -m compileall and pytest pass.
- `python3 -m src.app` starts and answers HTTP.
