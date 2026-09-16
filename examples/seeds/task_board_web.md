# Factory Seed

Goal:
Build a small task-board web application where a person can create,
edit, complete, and delete tasks, with persistent local storage and a
usable interface in a browser.

Constraints:
- Python 3 standard library only (http.server, pathlib, json).
- No npm, no frameworks, no database server.
- Persist tasks in a JSON file under data/tasks.json.
- Keep the implementation small and testable.

Known Context:
A single-user local app is enough. No accounts, no sharing, no cloud.

Success:
- Starting the app serves an HTML UI on localhost.
- A user can add a task, see it listed, mark it complete, edit its
  title, and delete it.
- Restarting the process keeps the tasks (JSON persistence).
- Missing or corrupt JSON is handled without crashing (empty list /
  reset).
- Automated tests cover the task model and persistence.
- The UI is usable at a narrow viewport (no overlapping controls).

Acceptance (the factory is not done when files merely exist):
1. `python3 -m compileall` succeeds on the project.
2. `python3 -m pytest` passes.
3. Persistence round-trip: save then load returns the same tasks.
4. A documented start command launches the server (for example
   `python3 -m src.task_board`).
5. The UI exposes add / edit / complete / delete without placeholders.
