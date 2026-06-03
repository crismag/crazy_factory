# Factory Seed

Goal:
Build a small HTTP endpoint health checker.

Constraints:
- Python
- Standard library only (urllib)
- Reads a list of URLs from a local file
- Keep implementation small

Known Context:
None yet.

Success:
Check each URL, report status code and latency, exit non-zero if any is down.
