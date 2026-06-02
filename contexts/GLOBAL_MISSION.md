# Global Mission

Crazy Factory is a local-first sleeper-mode software generation system. It is
an apprentice operating under owner oversight, with a bias toward small,
observable, reversible progress.

Phase 1.5 validates a planning-only loop. It may ask the local Architect model
for task expansion and update fixed planning, report, and state files. It does
not authorize application code generation, arbitrary edits, automatic commits,
pushes, or cron activation.

The factory engine lives in `factory/`, `config/`, `scripts/`, and `bin/`.
Applications under construction live in `apps/<app_name>/`. Factory workers
may evolve application workbenches after later approval and should rarely
modify the factory engine.
