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
- User can define habits.
- User can record completion for a habit.
- Completion is associated with a date.
- Persisted habit state survives restart.
- python3 -m compileall and pytest pass.
- `python3 -m src.app` starts and answers HTTP.
