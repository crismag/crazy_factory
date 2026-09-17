#!/usr/bin/env python3
"""Product-claim evidence: capability, not coding vocabulary.

Claims may be satisfied by one or more evidence kinds. The evaluator
selects the strongest practical kind for the claim. Identifier lists
are an optional static kind, never the habit-class acceptance path.

Kinds:
    static       — source identifiers / data fields / files
    test         — workbench tests that exercise the claim (reserved)
    runtime      — the running product interface created/returned state
    persistence  — created state still present after stop/restart
    visible      — operator-visible output (HTML), not banner quotes
"""

from __future__ import annotations

import os
import re
import signal
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

from product_intent import Capability
from runtime_observer import confine_start, discover_start

KIND_STATIC = "static"
KIND_TEST = "test"
KIND_RUNTIME = "runtime"
KIND_PERSISTENCE = "persistence"
KIND_VISIBLE = "visible"

EVIDENCE_KINDS = frozenset(
    {KIND_STATIC, KIND_TEST, KIND_RUNTIME, KIND_PERSISTENCE, KIND_VISIBLE}
)

# Habit-class claims: behavioral evidence, not add_habit / current_streak.
DEFAULT_CLAIM_EVIDENCE: dict[str, tuple[str, ...]] = {
    "define_habits": (KIND_RUNTIME,),
    "record_completion": (KIND_RUNTIME,),
    "dated_completion": (KIND_RUNTIME,),
    "persist_habits": (KIND_PERSISTENCE,),
    "habit_streaks": (KIND_VISIBLE, KIND_RUNTIME),
    "weekly_view": (KIND_VISIBLE, KIND_RUNTIME),
}

HABIT_CLAIM_IDS = frozenset(DEFAULT_CLAIM_EVIDENCE)

EVIDENCE_FILE = "product_evidence.json"
START_WAIT = 2.0
HTTP_TIMEOUT = 2.0
KILL_SECONDS = 1.0
MAX_BODY = 200_000

_ISO_DATE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
_STREAK_NUM = re.compile(
    r"(?:streak|consecutive|run)\W{0,32}(\d+)|(\d+)\W{0,12}days?\b",
    re.IGNORECASE,
)
_WEEKDAYS = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)
_WEEKDAYS_SHORT = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
_CREATE_HINT = re.compile(
    r"\b(add|create|new|save|register|name|title|habit)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class EvidenceHit:
    """One claim scored against one evidence kind."""

    cap_id: str
    ok: bool
    kind: str
    detail: str


@dataclass
class ClaimScore:
    """Capability plus the strongest evidence that scored it."""

    cap: Capability
    ok: bool
    kind: str
    detail: str


def evidence_kinds(cap: Capability) -> tuple[str, ...]:
    """Admissible kinds for a claim, strongest first."""
    raw = tuple(
        item
        for item in (getattr(cap, "evidence", ()) or ())
        if item in EVIDENCE_KINDS
    )
    if raw:
        return raw
    if cap.id in DEFAULT_CLAIM_EVIDENCE:
        return DEFAULT_CLAIM_EVIDENCE[cap.id]
    return (KIND_STATIC,)


def static_claim_satisfied(
    cap: Capability,
    *,
    identifiers: set[str],
    json_keys: set[str],
    files: set[str],
) -> bool:
    """True when static probes hit source, not banner text."""
    symbol_hit = not cap.symbols or any(
        name in identifiers for name in cap.symbols
    )
    field_hit = not cap.fields or any(
        name in json_keys or name in identifiers for name in cap.fields
    )
    file_hit = not cap.files or any(name in files for name in cap.files)
    needed = bool(cap.symbols or cap.fields or cap.files)
    if not needed:
        return False
    return bool(symbol_hit and field_hit and file_hit)


class _PageParser(HTMLParser):
    """Collect forms, links, and visible text from HTML."""

    def __init__(self) -> None:
        super().__init__()
        self.forms: list[dict[str, Any]] = []
        self.links: list[str] = []
        self.chunks: list[str] = []
        self._form: dict[str, Any] | None = None

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        ad = {k: (v or "") for k, v in attrs}
        if tag == "a" and ad.get("href"):
            self.links.append(ad["href"])
        if tag == "form":
            self._form = {
                "action": ad.get("action") or "",
                "method": (ad.get("method") or "get").lower(),
                "fields": [],
                "labels": [],
            }
            self.forms.append(self._form)
        elif self._form is not None and tag in {
            "input",
            "textarea",
            "button",
            "select",
        }:
            ftype = ad.get("type") or ("submit" if tag == "button" else "text")
            self._form["fields"].append(
                {
                    "name": ad.get("name") or "",
                    "type": ftype.lower(),
                    "value": ad.get("value") or "",
                }
            )
        if tag == "time" and ad.get("datetime"):
            self.chunks.append(ad["datetime"])

    def handle_endtag(self, tag: str) -> None:
        if tag == "form":
            self._form = None

    def handle_data(self, data: str) -> None:
        text = unescape(data)
        if text.strip():
            self.chunks.append(text)
            if self._form is not None:
                self._form["labels"].append(text)


def parse_page(html: str) -> _PageParser:
    parser = _PageParser()
    try:
        parser.feed(html)
        parser.close()
    except (ValueError, TypeError, AssertionError):
        return parser
    return parser


def _visible_text(html: str) -> str:
    return unescape(" ".join(parse_page(html).chunks))


class _LocalRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        host = (urlparse(newurl).hostname or "").lower()
        if host not in {"127.0.0.1", "localhost"}:
            return None
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _opener() -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(_LocalRedirect)


def _kill(proc: subprocess.Popen[str]) -> None:
    try:
        if proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except (ProcessLookupError, PermissionError, OSError):
                proc.terminate()
            try:
                proc.wait(timeout=KILL_SECONDS)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except (ProcessLookupError, PermissionError, OSError):
                    proc.kill()
    finally:
        for stream in (proc.stdout, proc.stderr):
            if stream is not None:
                try:
                    stream.close()
                except OSError:
                    pass


class WorkbenchHttp:
    """Start a confined workbench HTTP app and speak to 127.0.0.1 only."""

    def __init__(self, app: Path) -> None:
        self.app = app
        self.port: int | None = None
        self._proc: subprocess.Popen[str] | None = None
        self._opener = _opener()

    @property
    def origin(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def start(self) -> str:
        argv, port = discover_start(self.app)
        if not argv or port is None:
            return "no HTTP start command declared"
        verdict, refusal = confine_start(argv, self.app)
        if verdict != "ok":
            return refusal or verdict
        try:
            proc = subprocess.Popen(
                argv,
                cwd=str(self.app),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                start_new_session=True,
            )
        except (FileNotFoundError, OSError) as exc:
            return f"could not start: {exc}"
        self._proc = proc
        self.port = port
        deadline = time.monotonic() + START_WAIT
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                err = ""
                try:
                    err = (proc.stderr.read() if proc.stderr else "")[-200:]
                except OSError:
                    err = ""
                return f"process exited {proc.returncode}: {err.strip()}"
            if _port_answers(port):
                if proc.poll() is not None:
                    return "start failed; listen port already in use"
                return ""
            time.sleep(0.1)
        return f"port {port} did not answer"

    def stop(self) -> None:
        if self._proc is not None:
            _kill(self._proc)
            self._proc = None

    def get(self, path: str) -> tuple[int, str]:
        return self._call("GET", path, None)

    def post(self, path: str, fields: dict[str, str]) -> tuple[int, str]:
        body = urllib.parse.urlencode(fields).encode("utf-8")
        return self._call("POST", path, body)

    def _call(
        self, method: str, path: str, body: bytes | None
    ) -> tuple[int, str]:
        url = urljoin(self.origin + "/", path)
        host = (urlparse(url).hostname or "").lower()
        if host not in {"127.0.0.1", "localhost"}:
            return 0, "refused non-local URL"
        headers = {"User-Agent": "crazy-factory-evidence"}
        if body is not None:
            headers["Content-Type"] = (
                "application/x-www-form-urlencoded; charset=utf-8"
            )
        req = urllib.request.Request(
            url, data=body, headers=headers, method=method
        )
        try:
            with self._opener.open(req, timeout=HTTP_TIMEOUT) as resp:
                raw = resp.read(MAX_BODY)
                return int(resp.status), raw.decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            raw = exc.read(MAX_BODY)
            return int(exc.code), raw.decode("utf-8", "replace")
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            return 0, str(exc)


def _port_answers(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=0.4):
            return True
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def _abs_path(page_path: str, action: str) -> str:
    page = page_path if page_path.startswith("/") else f"/{page_path}"
    joined = urljoin("http://127.0.0.1" + page, action or "")
    parsed = urlparse(joined)
    path = parsed.path or page
    if parsed.query:
        return f"{path}?{parsed.query}"
    return path


def _text_fields(form: dict[str, Any]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for field in form.get("fields") or []:
        if not field.get("name"):
            continue
        ftype = str(field.get("type") or "text")
        if ftype in {
            "hidden",
            "submit",
            "button",
            "checkbox",
            "radio",
            "file",
        }:
            continue
        out.append(field)
    return out


def _is_create_form(form: dict[str, Any]) -> bool:
    if str(form.get("method") or "") != "post":
        return False
    fields = _text_fields(form)
    if not fields:
        return False
    if any(f.get("type") == "date" for f in fields):
        return False
    labels = " ".join(str(x) for x in form.get("labels") or [])
    names = " ".join(f.get("name") or "" for f in fields)
    blob = f"{form.get('action')} {labels} {names}"
    return bool(_CREATE_HINT.search(blob) or len(fields) == 1)


def _is_date_form(form: dict[str, Any]) -> bool:
    if str(form.get("method") or "") != "post":
        return False
    return any(
        f.get("type") == "date" and f.get("name")
        for f in form.get("fields") or []
    )


def _fill_create(form: dict[str, Any], token: str) -> dict[str, str]:
    payload: dict[str, str] = {}
    filled = False
    for field in _text_fields(form):
        ftype = field.get("type") or "text"
        if ftype in {"text", "search", ""} and not filled:
            payload[field["name"]] = token
            filled = True
        elif field.get("value"):
            payload[field["name"]] = field["value"]
    return payload


def _fill_date(form: dict[str, Any], day: str) -> dict[str, str]:
    payload: dict[str, str] = {}
    for field in form.get("fields") or []:
        name = field.get("name") or ""
        if not name:
            continue
        if field.get("type") == "date":
            payload[name] = day
        elif (
            field.get("type")
            not in {
                "submit",
                "button",
                "hidden",
            }
            and field.get("value")
            or field.get("type") == "hidden"
            and field.get("value")
        ):
            payload[name] = field["value"]
    return payload


def _window_around(html: str, token: str, radius: int = 500) -> str:
    text = _visible_text(html)
    low = text.lower()
    needle = token.lower()
    at = low.find(needle)
    if at < 0:
        return text
    start = max(0, at - radius)
    return text[start : at + len(token) + radius]


def _streak_number(text: str) -> int | None:
    best: int | None = None
    for match in _STREAK_NUM.finditer(text):
        raw = match.group(1) or match.group(2)
        if raw is None:
            continue
        try:
            value = int(raw)
        except ValueError:
            continue
        if value <= 0:
            continue
        if best is None or value > best:
            best = value
    return best


def _has_week_structure(html: str) -> bool:
    text = _visible_text(html).lower()
    long_hits = sum(1 for day in _WEEKDAYS if re.search(rf"\b{day}\b", text))
    if long_hits >= 5:
        return True
    short_hits = sum(
        1 for day in _WEEKDAYS_SHORT if re.search(rf"\b{day}\b", text)
    )
    if short_hits >= 5:
        return True
    dates = _ISO_DATE.findall(html)
    return bool(len(set(dates)) >= 7 and re.search(r"\bweek", text))


def _contains(html: str, token: str) -> bool:
    return token.lower() in unescape(html).lower()


@dataclass
class HabitBundle:
    """Behavioral evidence collected from one workbench HTTP session."""

    hits: dict[str, EvidenceHit]
    error: str = ""

    def hit(self, cap_id: str) -> EvidenceHit | None:
        return self.hits.get(cap_id)


def probe_habit_product(app: Path) -> HabitBundle:
    """Drive the running product interface; no identifier vocabulary."""
    token = "cf-ev-" + uuid.uuid4().hex[:10]
    today = datetime.now(tz=timezone.utc).astimezone().date()
    yesterday = today - timedelta(days=1)
    dated = datetime(2021, 6, 4, tzinfo=timezone.utc).date()
    http = WorkbenchHttp(app)
    hits: dict[str, EvidenceHit] = {}

    def miss(cap_id: str, kind: str, detail: str) -> None:
        hits[cap_id] = EvidenceHit(cap_id, False, kind, detail)

    def ok(cap_id: str, kind: str, detail: str) -> None:
        hits[cap_id] = EvidenceHit(cap_id, True, kind, detail)

    err = http.start()
    if err:
        for cap_id, kinds in DEFAULT_CLAIM_EVIDENCE.items():
            miss(cap_id, kinds[0], err)
        return HabitBundle(hits=hits, error=err)

    try:
        landing_paths = ["/", "/habits", "/entries", "/items"]
        pages: list[tuple[str, str]] = []
        for path in landing_paths:
            status, body = http.get(path)
            if status and status < 400 and body:
                pages.append((path, body))

        create = None
        create_path = "/"
        for path, body in pages:
            parsed = parse_page(body)
            for form in parsed.forms:
                if _is_create_form(form):
                    create = form
                    create_path = path
                    break
            if create is not None:
                break

        if create is None:
            miss(
                "define_habits",
                KIND_RUNTIME,
                "no create form on the product interface",
            )
        else:
            action = _abs_path(create_path, str(create.get("action") or ""))
            fields = _fill_create(create, token)
            _status, body = http.post(action, fields)
            shown = _contains(body, token)
            if not shown:
                for path in landing_paths:
                    st, again = http.get(path)
                    if st and _contains(again, token):
                        body = again
                        shown = True
                        break
            if shown:
                ok(
                    "define_habits",
                    KIND_RUNTIME,
                    f"created {token!r} through the product form",
                )
            else:
                miss(
                    "define_habits",
                    KIND_RUNTIME,
                    "form POST did not make the new habit observable",
                )

        if not hits.get("define_habits") or not hits["define_habits"].ok:
            for cap_id in (
                "record_completion",
                "dated_completion",
                "habit_streaks",
                "weekly_view",
                "persist_habits",
            ):
                miss(
                    cap_id,
                    DEFAULT_CLAIM_EVIDENCE[cap_id][0],
                    "habit was not created",
                )
            return HabitBundle(hits=hits)

        detail_html = body
        date_form = None
        date_page = "/"
        candidates: list[tuple[str, str]] = [(create_path, body)]
        parsed_detail = parse_page(detail_html)
        extra = 0
        for href in parsed_detail.links:
            if extra >= 6:
                break
            path = urlparse(urljoin(http.origin + "/", href)).path
            if not path.startswith("/") or path.endswith(
                (".css", ".js", ".png", ".ico")
            ):
                continue
            st, linked = http.get(path)
            extra += 1
            if st and st < 400:
                candidates.append((path, linked))
                if _contains(linked, token):
                    detail_html = linked

        for path, html in candidates:
            parsed = parse_page(html)
            for form in parsed.forms:
                if _is_date_form(form):
                    date_form = form
                    date_page = path
                    detail_html = html
                    break
            if date_form is not None:
                break

        if date_form is None:
            miss(
                "record_completion",
                KIND_RUNTIME,
                "no completion form with a calendar date",
            )
            miss(
                "dated_completion",
                KIND_RUNTIME,
                "no completion form with a calendar date",
            )
            miss(
                "habit_streaks",
                KIND_VISIBLE,
                "no dated completion interface to build history",
            )
        else:
            action = _abs_path(date_page, str(date_form.get("action") or ""))
            dated_html = ""
            status, dated_html = http.post(
                action, _fill_date(date_form, dated.isoformat())
            )
            if status >= 400 or not _contains(dated_html, dated.isoformat()):
                # Some UIs only accept recent dates; today still has a date.
                status, dated_html = http.post(
                    action, _fill_date(date_form, today.isoformat())
                )
                dated = today
            recorded = bool(
                status
                and status < 400
                and (
                    _contains(dated_html, dated.isoformat())
                    or _ISO_DATE.search(dated_html)
                )
            )
            if recorded:
                ok(
                    "record_completion",
                    KIND_RUNTIME,
                    f"recorded a completion for {token!r}",
                )
            else:
                miss(
                    "record_completion",
                    KIND_RUNTIME,
                    "completion POST was not observable",
                )
            if recorded and _contains(dated_html, dated.isoformat()):
                ok(
                    "dated_completion",
                    KIND_RUNTIME,
                    f"completion stored/returned with date {dated.isoformat()}",
                )
            elif recorded:
                miss(
                    "dated_completion",
                    KIND_RUNTIME,
                    "completion recorded but no calendar date was returned",
                )
            else:
                miss(
                    "dated_completion",
                    KIND_RUNTIME,
                    "completion was not stored with a calendar date",
                )

            _status_y, after_y = http.post(
                action, _fill_date(date_form, yesterday.isoformat())
            )
            status_t, after_t = http.post(
                action, _fill_date(date_form, today.isoformat())
            )
            streak_html = after_t if status_t and status_t < 400 else after_y
            if not _contains(streak_html, token):
                for path in landing_paths:
                    st, again = http.get(path)
                    if st and _contains(again, token):
                        streak_html = again
                        break
            window = _window_around(streak_html, token)
            number = _streak_number(window)
            has_dates = (
                yesterday.isoformat() in streak_html
                and today.isoformat() in streak_html
            )
            if number is not None and number >= 2:
                ok(
                    "habit_streaks",
                    KIND_VISIBLE,
                    f"observable streak {number} after two consecutive dates",
                )
            elif has_dates and re.search(
                r"streak|consecutive", window, re.IGNORECASE
            ):
                ok(
                    "habit_streaks",
                    KIND_RUNTIME,
                    "consecutive dated completions are visible with streak output",
                )
            else:
                miss(
                    "habit_streaks",
                    KIND_VISIBLE,
                    "known history did not produce an observable streak",
                )

        week_html = detail_html
        for path in landing_paths:
            st, again = http.get(path)
            if st and _contains(again, token):
                week_html = again
                if _has_week_structure(again):
                    break
        if _has_week_structure(week_html):
            ok(
                "weekly_view",
                KIND_VISIBLE,
                "weekly completion structure is visible in product output",
            )
        else:
            miss(
                "weekly_view",
                KIND_VISIBLE,
                "no weekly completion structure in product output",
            )

        http.stop()
        err = http.start()
        if err:
            miss("persist_habits", KIND_PERSISTENCE, f"restart failed: {err}")
        else:
            survived = False
            for path in landing_paths:
                st, again = http.get(path)
                if st and _contains(again, token):
                    survived = True
                    break
            if survived:
                ok(
                    "persist_habits",
                    KIND_PERSISTENCE,
                    f"{token!r} still present after stop/restart",
                )
            else:
                miss(
                    "persist_habits",
                    KIND_PERSISTENCE,
                    "created habit missing after restart",
                )
        return HabitBundle(hits=hits)
    finally:
        http.stop()


def persist_evidence(task_root: Path, scores: list[ClaimScore]) -> Path:
    task_root.mkdir(parents=True, exist_ok=True)
    path = task_root / EVIDENCE_FILE
    payload = {
        "claims": [
            {
                "id": score.cap.id,
                "ok": score.ok,
                "kind": score.kind,
                "detail": score.detail,
                "claim": score.cap.claim,
            }
            for score in scores
        ]
    }
    path.write_text(json_dumps(payload), encoding="utf-8")
    return path


def json_dumps(payload: dict[str, Any]) -> str:
    import json

    return json.dumps(payload, indent=2) + "\n"


def evaluate_claims(
    caps: list[Capability],
    *,
    app: Path,
    identifiers: set[str],
    json_keys: set[str],
    files: set[str],
    task_root: Path | None = None,
) -> list[ClaimScore]:
    """Score each claim with the strongest practical evidence kind."""
    bundle: HabitBundle | None = None
    if any(cap.id in HABIT_CLAIM_IDS for cap in caps):
        try:
            bundle = probe_habit_product(app)
        except Exception as exc:  # noqa: BLE001 - evidence must not crash accept
            bundle = HabitBundle(
                hits={
                    cap_id: EvidenceHit(cap_id, False, kinds[0], str(exc))
                    for cap_id, kinds in DEFAULT_CLAIM_EVIDENCE.items()
                },
                error=str(exc),
            )

    scores: list[ClaimScore] = []
    for cap in caps:
        kinds = evidence_kinds(cap)
        scored = False
        if bundle is not None and cap.id in HABIT_CLAIM_IDS:
            hit = bundle.hit(cap.id)
            if hit is not None:
                scores.append(
                    ClaimScore(
                        cap=cap,
                        ok=hit.ok,
                        kind=hit.kind,
                        detail=hit.detail,
                    )
                )
                scored = True
        if scored:
            continue
        if KIND_STATIC in kinds or kinds == (KIND_STATIC,):
            ok = static_claim_satisfied(
                cap,
                identifiers=identifiers,
                json_keys=json_keys,
                files=files,
            )
            scores.append(
                ClaimScore(
                    cap=cap,
                    ok=ok,
                    kind=KIND_STATIC,
                    detail=(
                        "static identifiers/fields/files matched"
                        if ok
                        else "static probes did not match"
                    ),
                )
            )
            continue
        scores.append(
            ClaimScore(
                cap=cap,
                ok=False,
                kind=kinds[0] if kinds else KIND_STATIC,
                detail="no practical evidence collected",
            )
        )
    if task_root is not None:
        persist_evidence(task_root, scores)
    return scores
