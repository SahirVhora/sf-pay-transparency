#!/usr/bin/env python3
"""Local server for the SF Pay Transparency prototype.

The browser cannot call SuccessFactors OData reliably because of CORS, so this
server serves the static app and performs OData calls from Python.
"""

from __future__ import annotations

import base64
from datetime import datetime, timezone
import math
import json
import os
from defusedxml.ElementTree import fromstring as _safe_fromstring
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen


HOST = "127.0.0.1"
PORT = 8080
ROOT = Path(__file__).resolve().parent
CREDENTIALS_FILE = ROOT / ".pay_transparency_credentials.json"
ALLOWED_HOST_SUFFIXES = (
    ".successfactors.eu",
    ".sapsf.eu",
    ".successfactors.com",
    ".sapsf.com",
)
LIVE_MODE = os.getenv("SFPT_LIVE_MODE", "").lower() in ("1", "true", "yes", "on")
EDM_NS = "{http://schemas.microsoft.com/ado/2008/09/edm}"
ALL_CHECK_IDS = (
    "pg_exists",
    "pg_values",
    "pg_mapped",
    "pg_dated",
    "ja_hierarchy",
    "ja_positions",
    "ja_families",
    "cd_base",
    "cd_currency",
    "cd_history",
    "cd_gender",
    "pd_profile",
    "pd_avg_levels",
    "pd_request",
    "gr_gender",
    "gr_wfa",
    "gr_5pct",
    "gr_notify",
    "hd_req",
    "hd_career",
    "hd_offer",
    "ja_trigger",
    "ja_workflow",
    "ja_remediation",
    "dg_audit",
    "dg_rbp",
    "dg_country",
)
PAY_TEXT_MARKERS = (
    "pay",
    "salary",
    "range",
    "compensation",
    "min",
    "max",
    "grade",
    "band",
)
MONEY_TEXT_MARKERS = (
    "salary",
    "pay",
    "compensation",
    "£",
    "$",
    "€",
    "gbp",
    "eur",
    "usd",
)
COUNTRY_OPTIONS = (
    ("AFG", "Afghanistan"),
    ("ALB", "Albania"),
    ("DZA", "Algeria"),
    ("AND", "Andorra"),
    ("AGO", "Angola"),
    ("ARG", "Argentina"),
    ("ARM", "Armenia"),
    ("AUS", "Australia"),
    ("AUT", "Austria"),
    ("AZE", "Azerbaijan"),
    ("BHR", "Bahrain"),
    ("BGD", "Bangladesh"),
    ("BEL", "Belgium"),
    ("BRA", "Brazil"),
    ("BGR", "Bulgaria"),
    ("CAN", "Canada"),
    ("CHL", "Chile"),
    ("CHN", "China"),
    ("COL", "Colombia"),
    ("HRV", "Croatia"),
    ("CZE", "Czechia"),
    ("DNK", "Denmark"),
    ("EGY", "Egypt"),
    ("EST", "Estonia"),
    ("FIN", "Finland"),
    ("FRA", "France"),
    ("DEU", "Germany"),
    ("GRC", "Greece"),
    ("HKG", "Hong Kong"),
    ("HUN", "Hungary"),
    ("IND", "India"),
    ("IDN", "Indonesia"),
    ("IRL", "Ireland"),
    ("ISR", "Israel"),
    ("ITA", "Italy"),
    ("JPN", "Japan"),
    ("KOR", "South Korea"),
    ("LVA", "Latvia"),
    ("LTU", "Lithuania"),
    ("LUX", "Luxembourg"),
    ("MYS", "Malaysia"),
    ("MEX", "Mexico"),
    ("NLD", "Netherlands"),
    ("NZL", "New Zealand"),
    ("NOR", "Norway"),
    ("POL", "Poland"),
    ("PRT", "Portugal"),
    ("ROU", "Romania"),
    ("SAU", "Saudi Arabia"),
    ("SGP", "Singapore"),
    ("SVK", "Slovakia"),
    ("SVN", "Slovenia"),
    ("ZAF", "South Africa"),
    ("ESP", "Spain"),
    ("SWE", "Sweden"),
    ("CHE", "Switzerland"),
    ("TWN", "Taiwan"),
    ("THA", "Thailand"),
    ("TUR", "Turkey"),
    ("ARE", "United Arab Emirates"),
    ("GBR", "United Kingdom"),
    ("USA", "United States"),
    ("VNM", "Vietnam"),
)
COUNTRY_CODE_TO_NAME = {code: name for code, name in COUNTRY_OPTIONS}
COUNTRY_NAME_TO_CODE = {name.lower(): code for code, name in COUNTRY_OPTIONS}
DEFAULT_EVIDENCE_LIMIT = 1000
EVIDENCE_ENTITY_KEYS = (
    "emp_job",
    "comp",
    "employment",
    "user",
    "personal",
    "person",
    "position",
    "job_code",
    "pay_grade",
    "pay_range",
)
SENSITIVE_FIELD_MARKERS = (
    "name",
    "firstname",
    "lastname",
    "displayname",
    "email",
    "address",
    "phone",
    "birth",
    "national",
    "person",
    "user",
    "employee",
    "paycompvalue",
    "amount",
    "salary",
    "iban",
    "bank",
    "account",
    "ssn",
    "tax",
)


class PayTransparencyHandler(BaseHTTPRequestHandler):
    def do_HEAD(self):
        parsed = urlparse(self.path)
        if parsed.path in ("", "/"):
            path = ROOT / "index.html"
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(path.stat().st_size))
            self.end_headers()
            return
        if parsed.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", "12")
            self.end_headers()
            return
        self.send_response(404)
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path in ("", "/"):
            self._serve_file(ROOT / "index.html", "text/html; charset=utf-8")
            return
        if parsed.path == "/health":
            self._json(200, {"ok": True})
            return
        if parsed.path == "/api/credentials":
            self._api_get_credentials()
            return
        if parsed.path == "/api/countries":
            self._api_countries()
            return
        self._text(404, "Not found")

    def do_POST(self):
        parsed = urlparse(self.path)
        try:
            payload = self._read_json()
            if parsed.path == "/api/test-connection":
                self._api_test_connection(payload)
                return
            if parsed.path == "/api/save-credentials":
                self._api_save_credentials(payload)
                return
            if parsed.path == "/api/live-checks":
                self._api_live_checks(payload)
                return
            if parsed.path == "/api/evidence-pack":
                self._api_evidence_pack(payload)
                return
            self._text(404, "Not found")
        except Exception as exc:
            self._json(500, {"ok": False, "message": str(exc)})

    def _api_test_connection(self, payload: dict):
        if not self._require_live_mode():
            return
        credentials = _merge_saved_credentials(payload)
        base_url = _clean_base_url(credentials.get("baseUrl", ""))
        username = (credentials.get("username") or "").strip()
        password = credentials.get("password") or ""
        _validate_sf_url(base_url)
        if not username or not password:
            self._json(
                400, {"ok": False, "message": "Username and password are required"}
            )
            return

        status, body, content_type = _sf_get(
            f"{base_url}/odata/v2/$metadata",
            username,
            password,
            accept="application/xml",
        )
        if 200 <= status < 300 and b"EntityType" in body[:200000]:
            self._json(
                200,
                {
                    "ok": True,
                    "message": "Connected - OData metadata endpoint is reachable",
                },
            )
            return

        snippet = _safe_snippet(body, content_type)
        self._json(
            status,
            {
                "ok": False,
                "message": f"HTTP {status} from SuccessFactors",
                "detail": snippet,
            },
        )

    def _api_get_credentials(self):
        if not LIVE_MODE:
            self._json(
                200,
                {
                    "ok": True,
                    "liveMode": False,
                    "baseUrl": "",
                    "companyId": "",
                    "username": "",
                    "hasPassword": False,
                },
            )
            return
        saved = _load_credentials()
        self._json(
            200,
            {
                "ok": True,
                "liveMode": True,
                "baseUrl": saved.get("baseUrl", ""),
                "companyId": saved.get("companyId", ""),
                "username": saved.get("username", ""),
                "hasPassword": bool(saved.get("password")),
            },
        )

    def _api_countries(self):
        if not LIVE_MODE:
            self._json(200, {"ok": True, "liveMode": False, "countries": []})
            return
        credentials = _merge_saved_credentials({})
        base_url = _clean_base_url(credentials.get("baseUrl", ""))
        username = (credentials.get("username") or "").strip()
        password = credentials.get("password") or ""
        if not base_url or not username or not password:
            self._json(200, {"ok": True, "countries": []})
            return
        _validate_sf_url(base_url)
        metadata = _fetch_metadata(base_url, username, password)
        resolved = _resolve_entities(metadata["entities"], metadata["properties"])
        countries = _get_country_options(
            base_url, username, password, metadata["properties"], resolved
        )
        self._json(200, {"ok": True, "countries": countries})

    def _api_save_credentials(self, payload: dict):
        if not self._require_live_mode():
            return
        current = _load_credentials()
        password = payload.get("password") or current.get("password", "")
        credentials = {
            "baseUrl": _clean_base_url(payload.get("baseUrl", "")),
            "companyId": (payload.get("companyId") or "").strip(),
            "username": (payload.get("username") or "").strip(),
            "password": password,
        }
        _validate_sf_url(credentials["baseUrl"])
        if (
            not credentials["companyId"]
            or not credentials["username"]
            or not credentials["password"]
        ):
            self._json(
                400,
                {
                    "ok": False,
                    "message": "Base URL, company ID, username, and password are required",
                },
            )
            return
        _save_credentials(credentials)
        self._json(200, {"ok": True, "message": "Credentials saved locally"})

    def _api_live_checks(self, payload: dict):
        if not self._require_live_mode():
            return
        credentials = _merge_saved_credentials(payload)
        base_url = _clean_base_url(credentials.get("baseUrl", ""))
        username = (credentials.get("username") or "").strip()
        password = credentials.get("password") or ""
        _validate_sf_url(base_url)
        if not username or not password:
            self._json(
                400, {"ok": False, "message": "Username and password are required"}
            )
            return

        metadata = _fetch_metadata(base_url, username, password)
        entities = metadata["entities"]
        properties = metadata["properties"]

        checks = {check_id: 0 for check_id in ALL_CHECK_IDS}

        resolved = _resolve_entities(entities, properties)

        pay_grade = resolved.get("pay_grade")
        pay_range = resolved.get("pay_range")
        job_code = resolved.get("job_code")
        position = resolved.get("position")
        comp = resolved.get("comp")
        emp_job = resolved.get("emp_job")
        requisition = resolved.get("requisition")
        req_locale = resolved.get("req_locale")
        offer = resolved.get("offer")

        pay_grade_rows = _has_rows_for(
            base_url, username, password, properties, pay_grade
        )
        pay_range_rows = _has_rows_for(
            base_url, username, password, properties, pay_range
        )
        job_code_rows = _has_rows_for(
            base_url, username, password, properties, job_code
        )
        position_rows = _has_rows_for(
            base_url, username, password, properties, position
        )
        comp_rows = _has_rows_for(base_url, username, password, properties, comp)
        emp_job_rows = _has_rows_for(base_url, username, password, properties, emp_job)

        checks["pg_exists"] = 100 if pay_grade_rows else 0
        checks["pg_values"] = _score_pay_range(
            properties, pay_range, pay_range_rows, position, position_rows
        )
        checks["pg_mapped"] = _score_any_mapping(
            properties,
            (position, job_code, emp_job),
            ("payGrade", "payRange", "grade", "payScale", "cust_PayRange"),
        )
        checks["pg_dated"] = (
            100
            if pay_grade
            and _has_any_field(
                properties,
                pay_grade,
                ("startDate", "endDate", "effectiveStartDate", "effectiveEndDate"),
            )
            and pay_grade_rows
            else 0
        )

        checks["ja_hierarchy"] = 100 if job_code_rows else 0
        checks["ja_positions"] = 100 if position_rows else 0
        checks["ja_families"] = _score_any_mapping(
            properties,
            (job_code, position, emp_job),
            ("jobFunction", "jobFamily", "jobSubFunction", "jobLevel"),
        )

        checks["cd_base"] = 100 if comp_rows else 0
        checks["cd_currency"] = (
            100
            if comp
            and _has_any_field(properties, comp, ("currencyCode", "currency"))
            and comp_rows
            else 0
        )
        checks["cd_history"] = (
            100
            if comp
            and _has_any_field(
                properties,
                comp,
                ("startDate", "endDate", "seqNumber", "effectiveLatestChange"),
            )
            and comp_rows
            else 0
        )

        users = _sample_entity(
            base_url,
            username,
            password,
            properties,
            "User",
            ("firstName", "gender"),
            top=100,
        )
        if users:
            with_gender = sum(1 for row in users if row.get("gender"))
            pct = round((with_gender / len(users)) * 100)
            checks["cd_gender"] = 100 if pct >= 95 else 50 if pct >= 80 else 10
            checks["gr_gender"] = checks["cd_gender"]
        elif "PerPersonal" in entities:
            personal = _sample_entity(
                base_url,
                username,
                password,
                properties,
                "PerPersonal",
                ("personIdExternal", "gender"),
                top=100,
            )
            if personal:
                with_gender = sum(1 for row in personal if row.get("gender"))
                pct = round((with_gender / len(personal)) * 100)
                checks["cd_gender"] = 100 if pct >= 95 else 50 if pct >= 80 else 10
                checks["gr_gender"] = checks["cd_gender"]

        can_calculate_category_avg = bool(
            comp_rows
            and checks["cd_gender"] > 0
            and (position_rows or emp_job_rows or job_code_rows)
        )
        checks["pd_profile"] = (
            80 if comp_rows and ("User" in entities or "PerPersonal" in entities) else 0
        )
        checks["pd_avg_levels"] = (
            100
            if resolved.get("pay_info_response")
            else (50 if can_calculate_category_avg else 0)
        )
        checks["pd_request"] = 100 if resolved.get("pay_info_request") else 0

        checks["gr_wfa"] = (
            100
            if resolved.get("pay_gap_report")
            else (40 if can_calculate_category_avg else 0)
        )
        checks["gr_5pct"] = (
            100
            if resolved.get("pay_gap_alert")
            else (30 if can_calculate_category_avg else 0)
        )
        checks["gr_notify"] = (
            100 if resolved.get("workflow") and checks["gr_5pct"] >= 100 else 0
        )

        if requisition:
            checks["hd_req"] = _score_requisition_pay_fields(
                base_url, username, password, properties, requisition
            )
            checks["hd_career"] = 70 if req_locale else 30
            if req_locale:
                checks["hd_career"] = max(
                    checks["hd_career"],
                    _score_requisition_locale_text(
                        base_url, username, password, properties, req_locale
                    ),
                )
            checks["hd_offer"] = 70 if offer else 0

        checks["ja_trigger"] = (
            100
            if resolved.get("pay_gap_alert")
            else (30 if can_calculate_category_avg else 0)
        )
        checks["ja_workflow"] = (
            100 if resolved.get("workflow") and checks["ja_trigger"] >= 100 else 0
        )
        checks["ja_remediation"] = 100 if resolved.get("remediation") else 0

        checks["dg_audit"] = _score_audit_governance(entities, properties)
        checks["dg_rbp"] = 80 if resolved.get("permission") else 0
        checks["dg_country"] = (
            60
            if checks["dg_rbp"]
            and _score_any_mapping(
                properties, (emp_job, position), ("country", "company", "location")
            )
            else 0
        )

        self._json(
            200,
            {
                "ok": True,
                "checkResults": checks,
                "resolvedEntities": resolved,
                "dataPullMode": {
                    "metadata": "full /odata/v2/$metadata",
                    "tenantData": "targeted samples from resolved entities",
                    "fullTenantAudit": False,
                },
            },
        )

    def _api_evidence_pack(self, payload: dict):
        if not self._require_live_mode():
            return
        credentials = _merge_saved_credentials(payload)
        base_url = _clean_base_url(credentials.get("baseUrl", ""))
        username = (credentials.get("username") or "").strip()
        password = credentials.get("password") or ""
        _validate_sf_url(base_url)
        if not username or not password:
            self._json(
                400, {"ok": False, "message": "Username and password are required"}
            )
            return

        limit = _bounded_int(
            payload.get("limit"),
            default=DEFAULT_EVIDENCE_LIMIT,
            minimum=100,
            maximum=5000,
        )
        country_filter = (payload.get("country") or "").strip()
        metadata = _fetch_metadata(base_url, username, password)
        entities = metadata["entities"]
        properties = metadata["properties"]
        resolved = _resolve_entities(entities, properties)
        evidence = _build_evidence_pack(
            base_url, username, password, properties, resolved, limit, country_filter
        )
        raw_evidence = evidence.pop("_raw", {})
        article9 = _calculate_article9({"_raw": raw_evidence}, resolved)
        self._json(
            200,
            {
                "ok": True,
                "generatedAt": _now_iso(),
                "limitPerEntity": limit,
                "countryFilter": country_filter,
                "resolvedEntities": resolved,
                "evidence": evidence,
                "article9": article9,
                "dataPullMode": {
                    "metadata": "full /odata/v2/$metadata",
                    "tenantData": f"Article 9 cohort evidence pull, capped at {limit} rows per relevant entity",
                    "fullTenantAudit": False,
                },
            },
        )

    def _require_live_mode(self) -> bool:
        if LIVE_MODE:
            return True
        self._json(
            403,
            {
                "ok": False,
                "liveMode": False,
                "message": "Live tenant mode is disabled. Restart locally with SFPT_LIVE_MODE=1 to save credentials or call SuccessFactors OData.",
            },
        )
        return False

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length)
        return json.loads(raw.decode("utf-8")) if raw else {}

    def _serve_file(self, path: Path, content_type: str):
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.end_headers()
        self.wfile.write(path.read_bytes())

    def _json(self, status: int, payload: dict):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _text(self, status: int, text: str):
        body = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        print("%s - %s" % (self.address_string(), fmt % args))


def _clean_base_url(base_url: str) -> str:
    return (base_url or "").strip().rstrip("/")


def _load_credentials() -> dict:
    if not CREDENTIALS_FILE.exists():
        return {}
    try:
        with CREDENTIALS_FILE.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save_credentials(credentials: dict):
    tmp_path = CREDENTIALS_FILE.with_suffix(".tmp")
    with tmp_path.open("w", encoding="utf-8") as fh:
        json.dump(credentials, fh, indent=2)
    os.chmod(tmp_path, 0o600)
    tmp_path.replace(CREDENTIALS_FILE)
    os.chmod(CREDENTIALS_FILE, 0o600)


def _merge_saved_credentials(payload: dict) -> dict:
    saved = _load_credentials()
    merged = dict(saved)
    for source_key, target_key in (
        ("baseUrl", "baseUrl"),
        ("companyId", "companyId"),
        ("username", "username"),
        ("password", "password"),
    ):
        value = payload.get(source_key)
        if value:
            merged[target_key] = value
    return merged


def _validate_sf_url(base_url: str):
    parsed = urlparse(base_url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("Base URL must be an HTTPS SuccessFactors API URL")
    hostname = parsed.hostname.lower()
    if not hostname.endswith(ALLOWED_HOST_SUFFIXES):
        raise ValueError("Base URL host is not an SAP SuccessFactors API host")


def _sf_get(
    url: str, username: str, password: str, accept: str = "application/json"
) -> tuple[int, bytes, str]:
    token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
    req = Request(
        url,
        headers={
            "Authorization": f"Basic {token}",
            "Accept": accept,
        },
        method="GET",
    )
    try:
        with urlopen(req, timeout=60) as resp:
            return resp.status, resp.read(), resp.headers.get("Content-Type", "")
    except HTTPError as exc:
        return exc.code, exc.read(), exc.headers.get("Content-Type", "")
    except URLError as exc:
        raise RuntimeError(f"Could not reach SuccessFactors: {exc.reason}") from exc


def _entity_has_rows(
    base_url: str, username: str, password: str, entity: str, fields: str
) -> bool:
    return bool(_entity_results(base_url, username, password, entity, fields, top=1))


def _entity_results(
    base_url: str, username: str, password: str, entity: str, fields: str, top: int
) -> list[dict]:
    url = f"{base_url}/odata/v2/{entity}?$top={top}&$select={fields}&$format=json"
    status, body, content_type = _sf_get(url, username, password)
    if not (200 <= status < 300):
        return []
    try:
        data = json.loads(body.decode("utf-8"))
    except json.JSONDecodeError:
        return []
    if isinstance(data.get("d"), dict) and isinstance(data["d"].get("results"), list):
        return data["d"]["results"]
    if isinstance(data.get("results"), list):
        return data["results"]
    return []


def _entity_results_paged(
    base_url: str,
    username: str,
    password: str,
    entity: str,
    fields: list[str],
    limit: int,
    page_size: int = 200,
) -> list[dict]:
    if not entity or not fields:
        return []
    rows: list[dict] = []
    skip = 0
    safe_page_size = min(page_size, limit)
    select = ",".join(fields)
    while len(rows) < limit:
        query = urlencode(
            {
                "$top": safe_page_size,
                "$skip": skip,
                "$select": select,
                "$format": "json",
            }
        )
        status, body, _content_type = _sf_get(
            f"{base_url}/odata/v2/{entity}?{query}", username, password
        )
        if not (200 <= status < 300):
            break
        try:
            data = json.loads(body.decode("utf-8"))
        except json.JSONDecodeError:
            break
        page = []
        if isinstance(data.get("d"), dict) and isinstance(
            data["d"].get("results"), list
        ):
            page = data["d"]["results"]
        elif isinstance(data.get("results"), list):
            page = data["results"]
        if not page:
            break
        rows.extend(page)
        if len(page) < safe_page_size:
            break
        skip += safe_page_size
    return rows[:limit]


def _entity_results_filtered(
    base_url: str,
    username: str,
    password: str,
    entity: str,
    fields: list[str],
    filter_expr: str,
    limit: int,
    page_size: int = 200,
) -> list[dict]:
    if not entity or not fields or not filter_expr:
        return []
    rows: list[dict] = []
    skip = 0
    safe_page_size = min(page_size, limit)
    select = ",".join(fields)
    while len(rows) < limit:
        query = urlencode(
            {
                "$top": safe_page_size,
                "$skip": skip,
                "$select": select,
                "$filter": filter_expr,
                "$format": "json",
            }
        )
        status, body, _content_type = _sf_get(
            f"{base_url}/odata/v2/{entity}?{query}", username, password
        )
        if not (200 <= status < 300):
            break
        try:
            data = json.loads(body.decode("utf-8"))
        except json.JSONDecodeError:
            break
        page = []
        if isinstance(data.get("d"), dict) and isinstance(
            data["d"].get("results"), list
        ):
            page = data["d"]["results"]
        elif isinstance(data.get("results"), list):
            page = data["results"]
        if not page:
            break
        rows.extend(page)
        if len(page) < safe_page_size:
            break
        skip += safe_page_size
    return rows[:limit]


def _fetch_metadata(base_url: str, username: str, password: str) -> dict:
    status, body, content_type = _sf_get(
        f"{base_url}/odata/v2/$metadata",
        username,
        password,
        accept="application/xml",
    )
    if not (200 <= status < 300):
        raise RuntimeError(
            f"Could not fetch OData metadata: HTTP {status} - {_safe_snippet(body, content_type)}"
        )
    root = _safe_fromstring(body)
    entities = set()
    properties = {}
    for entity_type in root.iter(f"{EDM_NS}EntityType"):
        name = entity_type.get("Name")
        if not name:
            continue
        entities.add(name)
        properties[name] = {
            prop.get("Name", "")
            for prop in entity_type.findall(f"{EDM_NS}Property")
            if prop.get("Name")
        }
    return {"entities": entities, "properties": properties}


def _has_any_field(
    properties: dict[str, set[str]], entity: str, needles: tuple[str, ...]
) -> bool:
    fields = properties.get(entity, set())
    lower_fields = [field.lower() for field in fields]
    return any(needle.lower() in field for needle in needles for field in lower_fields)


def _has_entity_matching(entities: set[str], candidates: tuple[str, ...]) -> bool:
    lower_entities = {entity.lower() for entity in entities}
    for candidate in candidates:
        candidate_lower = candidate.lower()
        if candidate_lower in lower_entities:
            return True
        if any(candidate_lower in entity for entity in lower_entities):
            return True
    return False


def _first_existing_entity(
    entities: set[str], candidates: tuple[str, ...]
) -> str | None:
    for candidate in candidates:
        if candidate in entities:
            return candidate
    lower_map = {entity.lower(): entity for entity in entities}
    for candidate in candidates:
        candidate_lower = candidate.lower()
        for lower, original in lower_map.items():
            if candidate_lower in lower:
                return original
    return None


def _resolve_entities(
    entities: set[str], properties: dict[str, set[str]]
) -> dict[str, str | None]:
    return {
        "pay_grade": _best_entity(
            entities, properties, ("FOPayGrade", "PayGrade"), ("pay", "grade")
        ),
        "pay_range": _best_entity(
            entities,
            properties,
            ("FOPayRange", "PayRange", "PayScaleLevel"),
            ("pay", "range"),
        ),
        "job_code": _best_entity(
            entities,
            properties,
            ("FOJobCode", "JobClassification", "JobProfile"),
            ("job",),
        ),
        "position": _best_entity(entities, properties, ("Position",), ("position",)),
        "emp_job": _best_entity(entities, properties, ("EmpJob",), ("emp", "job")),
        "employment": _best_entity(
            entities, properties, ("EmpEmployment",), ("employment",)
        ),
        "person": _best_entity(entities, properties, ("PerPerson",), ("person",)),
        "comp": _best_entity(
            entities,
            properties,
            ("EmpPayCompRecurring", "EmpCompensation"),
            ("pay", "comp"),
        ),
        "requisition": _exact_entity(entities, ("JobRequisition",)),
        "req_locale": _exact_entity(
            entities, ("JobRequisitionLocale", "JobReqPosting", "JobRequisitionPosting")
        ),
        "offer": _exact_entity(entities, ("OfferLetter", "JobOffer", "OfferDetail")),
        "workflow": _exact_entity(
            entities, ("WfRequest", "Workflow", "MyPendingWorkflow")
        ),
        "permission": _exact_entity(
            entities,
            (
                "RBPBasicPermission",
                "UserPermissions",
                "PermissionRole",
                "PermissionGroup",
            ),
        ),
        "pay_info_response": _exact_entity(
            entities,
            ("Pay_Info_Response", "PayInformationResponse", "PayTransparencyResponse"),
        ),
        "pay_info_request": _exact_entity(
            entities,
            ("Pay_Info_Request", "PayInformationRequest", "PayComparisonRequest"),
        ),
        "pay_gap_report": _exact_entity(
            entities, ("PayGapReport", "PayEquityReport", "PayTransparencyReport")
        ),
        "pay_gap_alert": _exact_entity(
            entities, ("PayGapAlert", "GapAlert", "PayTransparencyAlert")
        ),
        "remediation": _exact_entity(
            entities, ("Remediation_Action", "RemediationAction", "PayGapRemediation")
        ),
    }


def _exact_entity(entities: set[str], candidates: tuple[str, ...]) -> str | None:
    for candidate in candidates:
        if candidate in entities:
            return candidate
    lower_map = {entity.lower(): entity for entity in entities}
    for candidate in candidates:
        found = lower_map.get(candidate.lower())
        if found:
            return found
    return None


def _best_entity(
    entities: set[str],
    properties: dict[str, set[str]],
    exact_candidates: tuple[str, ...],
    contains_terms: tuple[str, ...],
) -> str | None:
    for candidate in exact_candidates:
        if candidate in entities:
            return candidate
    lower_map = {entity.lower(): entity for entity in entities}
    for candidate in exact_candidates:
        candidate_lower = candidate.lower()
        for lower, original in lower_map.items():
            if candidate_lower == lower:
                return original
    scored = []
    for entity in entities:
        lower_entity = entity.lower()
        lower_fields = " ".join(properties.get(entity, set())).lower()
        score = sum(2 for term in contains_terms if term.lower() in lower_entity)
        score += sum(1 for term in contains_terms if term.lower() in lower_fields)
        if score:
            scored.append((score, len(entity), entity))
    if not scored:
        return None
    scored.sort(key=lambda row: (-row[0], row[1], row[2]))
    return scored[0][2]


def _has_rows_for(
    base_url: str,
    username: str,
    password: str,
    properties: dict[str, set[str]],
    entity: str | None,
) -> bool:
    if not entity:
        return False
    return bool(
        _sample_entity(base_url, username, password, properties, entity, (), top=1)
    )


def _sample_entity(
    base_url: str,
    username: str,
    password: str,
    properties: dict[str, set[str]],
    entity: str,
    preferred_fields: tuple[str, ...],
    top: int = 10,
) -> list[dict]:
    if not entity:
        return []
    entity_fields = properties.get(entity, set())
    selected = [field for field in preferred_fields if field in entity_fields]
    if not selected:
        selected = _default_select_fields(entity_fields)
    if not selected:
        return []
    return _entity_results(
        base_url, username, password, entity, ",".join(selected), top=top
    )


def _default_select_fields(fields: set[str]) -> list[str]:
    priority = (
        "externalCode",
        "code",
        "name",
        "userId",
        "personIdExternal",
        "jobReqId",
        "startDate",
        "effectiveStartDate",
        "payComponent",
        "paycompvalue",
        "currencyCode",
    )
    selected = [field for field in priority if field in fields]
    if selected:
        return selected[:5]
    return sorted(fields)[:5]


def _score_pay_range(
    properties: dict[str, set[str]],
    pay_range: str | None,
    pay_range_rows: bool,
    position: str | None,
    position_rows: bool,
) -> int:
    if pay_range and pay_range_rows:
        return 100
    if (
        position
        and position_rows
        and _has_any_field(
            properties,
            position,
            ("PayRange_Min", "PayRange_Max", "PayRange_Mid", "payRange"),
        )
    ):
        return 90
    if (
        position
        and position_rows
        and _has_any_field(properties, position, ("pay", "salary", "range"))
    ):
        return 60
    return 0


def _score_any_mapping(
    properties: dict[str, set[str]],
    entities: tuple[str | None, ...],
    needles: tuple[str, ...],
) -> int:
    for entity in entities:
        if entity and _has_any_field(properties, entity, needles):
            return 100
    return 0


def _score_requisition_pay_fields(
    base_url: str,
    username: str,
    password: str,
    properties: dict[str, set[str]],
    requisition: str,
) -> int:
    fields = _matching_fields(properties, requisition, PAY_TEXT_MARKERS)
    if not fields:
        return 0
    sample = _sample_entity(
        base_url, username, password, properties, requisition, tuple(fields[:8]), top=10
    )
    if sample and _has_nonempty_field(sample, fields):
        return 100
    return 60


def _score_requisition_locale_text(
    base_url: str,
    username: str,
    password: str,
    properties: dict[str, set[str]],
    req_locale: str,
) -> int:
    desc_fields = _matching_fields(
        properties,
        req_locale,
        ("externalJobDescription", "jobDescription", "extJobDesc", "description"),
    )
    if not desc_fields:
        return 30
    sample = _sample_entity(
        base_url,
        username,
        password,
        properties,
        req_locale,
        tuple(desc_fields[:6]),
        top=10,
    )
    text = " ".join(
        str(value) for row in sample for value in row.values() if value is not None
    ).lower()
    if any(marker in text for marker in MONEY_TEXT_MARKERS):
        return 100
    return 70 if sample else 30


def _score_audit_governance(entities: set[str], properties: dict[str, set[str]]) -> int:
    if _has_entity_matching(entities, ("FormAuditTrail", "AuditData", "ChangeAudit")):
        return 80
    if _first_existing_entity(entities, ("EmpCompensation", "EmpPayCompRecurring")):
        comp_entity = _first_existing_entity(
            entities, ("EmpCompensation", "EmpPayCompRecurring")
        )
        if comp_entity and _has_any_field(
            properties,
            comp_entity,
            ("createdBy", "createdOn", "lastModifiedBy", "lastModifiedOn"),
        ):
            return 50
    return 0


def _matching_fields(
    properties: dict[str, set[str]], entity: str, needles: tuple[str, ...]
) -> list[str]:
    fields = properties.get(entity, set())
    matches = []
    for field in sorted(fields):
        lower = field.lower()
        if any(needle.lower() in lower for needle in needles):
            matches.append(field)
    return matches


def _has_nonempty_field(rows: list[dict], fields: list[str]) -> bool:
    field_set = set(fields)
    for row in rows:
        for field, value in row.items():
            if field in field_set and value not in (None, ""):
                return True
    return False


def _first_existing_field(fields: set[str], candidates: tuple[str, ...]) -> str | None:
    for candidate in candidates:
        if candidate in fields:
            return candidate
    lower_map = {field.lower(): field for field in fields}
    for candidate in candidates:
        found = lower_map.get(candidate.lower())
        if found:
            return found
    return None


def _unique_preserve_order(values: list[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _chunks(values: list[str], size: int):
    for i in range(0, len(values), size):
        yield values[i : i + size]


def _odata_quote(value: str) -> str:
    return str(value).replace("'", "''")


def _country_filter_values(country_filter: str) -> list[str]:
    value = str(country_filter or "").strip()
    if not value:
        return []
    values = [value]
    upper = value.upper()
    if upper in COUNTRY_CODE_TO_NAME:
        values.append(COUNTRY_CODE_TO_NAME[upper])
    code = COUNTRY_NAME_TO_CODE.get(value.lower())
    if code:
        values.append(code)
    return _unique_preserve_order(values)


def _country_filter_expr(field: str, country_filter: str) -> str:
    return " or ".join(
        f"{field} eq '{_odata_quote(value)}'"
        for value in _country_filter_values(country_filter)
    )


def _build_evidence_pack(
    base_url: str,
    username: str,
    password: str,
    properties: dict[str, set[str]],
    resolved: dict[str, str | None],
    limit: int,
    country_filter: str = "",
) -> dict:
    entity_map = dict(resolved)
    if "User" in properties:
        entity_map["user"] = "User"
    if "PerPersonal" in properties:
        entity_map["personal"] = "PerPersonal"
    if "PerPerson" in properties:
        entity_map["person"] = "PerPerson"

    evidence = {
        "generatedAt": _now_iso(),
        "limitPerEntity": limit,
        "countryFilter": country_filter,
        "entities": {},
        "_raw": {},
    }
    cohort = _build_user_cohort(
        base_url, username, password, properties, resolved, limit, country_filter
    )
    if cohort:
        evidence["cohort"] = {
            "userCount": len(cohort.get("userIds", [])),
            "personCount": len(cohort.get("personIds", [])),
            "countryFilter": country_filter,
            "anchor": cohort.get("anchor", ""),
            "strictCountryFilter": bool(country_filter),
            "matched": bool(cohort.get("userIds") or cohort.get("personIds")),
        }
    required_purposes = {
        "emp_job",
        "comp",
        "employment",
        "user",
        "personal",
        "person",
        "position",
    }
    for purpose in EVIDENCE_ENTITY_KEYS:
        entity = entity_map.get(purpose)
        if not entity:
            continue
        fields = _evidence_fields_for(purpose, entity, properties.get(entity, set()))
        rows = _cohort_rows_for_purpose(
            base_url,
            username,
            password,
            properties,
            purpose,
            entity,
            fields,
            limit,
            cohort,
            country_filter,
        )
        if not rows and purpose not in required_purposes:
            continue
        evidence["_raw"][purpose] = rows
        evidence["entities"][purpose] = {
            "entity": entity,
            "selectedFields": fields,
            "rowsPulled": len(rows),
            "sampleRowsMasked": [_mask_row(row) for row in rows[:5]],
            "quality": _quality_for_rows(rows, fields),
        }
    return evidence


def _build_user_cohort(
    base_url: str,
    username: str,
    password: str,
    properties: dict[str, set[str]],
    resolved: dict[str, str | None],
    limit: int,
    country_filter: str,
) -> dict:
    emp_job_entity = resolved.get("emp_job")
    user_entity = "User" if "User" in properties else None
    emp_job_fields = (
        _evidence_fields_for(
            "emp_job", emp_job_entity, properties.get(emp_job_entity, set())
        )
        if emp_job_entity
        else []
    )
    user_fields = (
        _evidence_fields_for("user", user_entity, properties.get(user_entity, set()))
        if user_entity
        else []
    )

    emp_job_rows = []
    anchor = ""
    if emp_job_entity and emp_job_fields:
        if country_filter:
            country_field = _first_existing_field(
                properties.get(emp_job_entity, set()),
                ("countryOfCompany", "country", "company", "location"),
            )
            if country_field:
                emp_job_rows = _entity_results_filtered(
                    base_url,
                    username,
                    password,
                    emp_job_entity,
                    emp_job_fields,
                    _country_filter_expr(country_field, country_filter),
                    limit,
                )
                anchor = f"{emp_job_entity}.{country_field}"
                if (
                    not emp_job_rows
                    and country_field != "company"
                    and "company" in properties.get(emp_job_entity, set())
                ):
                    emp_job_rows = _entity_results_filtered(
                        base_url,
                        username,
                        password,
                        emp_job_entity,
                        emp_job_fields,
                        _country_filter_expr("company", country_filter),
                        limit,
                    )
                    if emp_job_rows:
                        anchor = f"{emp_job_entity}.company"
        if not emp_job_rows and not country_filter:
            emp_job_rows = _entity_results_paged(
                base_url,
                username,
                password,
                emp_job_entity,
                emp_job_fields,
                limit=limit,
            )
            anchor = emp_job_entity

    user_rows = []
    if user_entity and user_fields:
        if country_filter:
            country_field = _first_existing_field(
                properties.get(user_entity, set()),
                ("country", "countryOfCompany", "location"),
            )
            if country_field:
                user_rows = _entity_results_filtered(
                    base_url,
                    username,
                    password,
                    user_entity,
                    user_fields,
                    _country_filter_expr(country_field, country_filter),
                    limit,
                )
                anchor = anchor or f"{user_entity}.{country_field}"
        if not user_rows and not emp_job_rows and not country_filter:
            user_rows = _entity_results_paged(
                base_url, username, password, user_entity, user_fields, limit=limit
            )
            anchor = user_entity

    user_ids = []
    person_ids = []
    position_ids = []
    job_code_ids = []
    pay_grade_ids = []
    pay_range_ids = []
    for row in emp_job_rows:
        uid = _first_value(row, ("userId", "personIdExternal"))
        if uid:
            user_ids.append(str(uid))
        position_id = _first_value(row, ("position", "positionId", "positionCode"))
        job_code = _first_value(row, ("jobCode", "jobCodeId"))
        pay_grade = _first_value(row, ("payGrade", "payGradeId"))
        pay_range = _first_value(row, ("payRange", "payRangeId"))
        if position_id:
            position_ids.append(str(position_id))
        if job_code:
            job_code_ids.append(str(job_code))
        if pay_grade:
            pay_grade_ids.append(str(pay_grade))
        if pay_range:
            pay_range_ids.append(str(pay_range))
    for row in user_rows:
        uid = _first_value(row, ("userId", "personIdExternal"))
        pid = _first_value(row, ("personIdExternal", "personId"))
        if uid:
            user_ids.append(str(uid))
        if pid:
            person_ids.append(str(pid))

    user_ids = _unique_preserve_order(user_ids)[:limit]
    if user_ids and user_entity and not user_rows:
        user_rows = _fetch_by_ids(
            base_url,
            username,
            password,
            user_entity,
            user_fields,
            "userId",
            user_ids,
            limit,
        )
        for row in user_rows:
            pid = _first_value(row, ("personIdExternal", "personId"))
            if pid:
                person_ids.append(str(pid))

    employment_entity = resolved.get("employment")
    if user_ids and employment_entity:
        employment_fields = _evidence_fields_for(
            "employment", employment_entity, properties.get(employment_entity, set())
        )
        employment_rows = _fetch_by_ids(
            base_url,
            username,
            password,
            employment_entity,
            employment_fields,
            "userId",
            user_ids,
            limit,
        )
        for row in employment_rows:
            pid = _first_value(row, ("personIdExternal", "personId"))
            if pid:
                person_ids.append(str(pid))
    else:
        employment_rows = []

    return {
        "anchor": anchor,
        "userIds": user_ids,
        "personIds": _unique_preserve_order(person_ids)[:limit],
        "positionIds": _unique_preserve_order(position_ids)[:limit],
        "jobCodeIds": _unique_preserve_order(job_code_ids)[:limit],
        "payGradeIds": _unique_preserve_order(pay_grade_ids)[:limit],
        "payRangeIds": _unique_preserve_order(pay_range_ids)[:limit],
        "countryFilter": country_filter,
        "seedRows": {
            "user": user_rows,
            "emp_job": emp_job_rows,
            "employment": employment_rows,
        },
    }


def _cohort_rows_for_purpose(
    base_url: str,
    username: str,
    password: str,
    properties: dict[str, set[str]],
    purpose: str,
    entity: str,
    fields: list[str],
    limit: int,
    cohort: dict,
    country_filter: str = "",
) -> list[dict]:
    seed = (cohort or {}).get("seedRows", {})
    if purpose in seed and seed[purpose]:
        return seed[purpose][:limit]
    user_ids = (cohort or {}).get("userIds", [])
    person_ids = (cohort or {}).get("personIds", [])
    position_ids = (cohort or {}).get("positionIds", [])
    job_code_ids = (cohort or {}).get("jobCodeIds", [])
    pay_grade_ids = (cohort or {}).get("payGradeIds", [])
    pay_range_ids = (cohort or {}).get("payRangeIds", [])
    entity_fields = properties.get(entity, set())
    if purpose in ("comp", "emp_job", "employment", "permission") and user_ids:
        id_field = _first_existing_field(entity_fields, ("userId", "personIdExternal"))
        if id_field:
            return _fetch_by_ids(
                base_url, username, password, entity, fields, id_field, user_ids, limit
            )
    if purpose in ("personal", "person") and person_ids:
        id_field = _first_existing_field(
            entity_fields, ("personIdExternal", "personId", "userId")
        )
        if id_field:
            return _fetch_by_ids(
                base_url,
                username,
                password,
                entity,
                fields,
                id_field,
                person_ids,
                limit,
            )
    if purpose == "position" and position_ids:
        id_field = _first_existing_field(
            entity_fields, ("code", "externalCode", "position", "positionId")
        )
        if id_field:
            return _fetch_by_ids(
                base_url,
                username,
                password,
                entity,
                fields,
                id_field,
                position_ids,
                limit,
            )
    if purpose == "job_code" and job_code_ids:
        id_field = _first_existing_field(
            entity_fields, ("externalCode", "code", "jobCode")
        )
        if id_field:
            return _fetch_by_ids(
                base_url,
                username,
                password,
                entity,
                fields,
                id_field,
                job_code_ids,
                limit,
            )
    if purpose == "pay_grade" and pay_grade_ids:
        id_field = _first_existing_field(
            entity_fields, ("externalCode", "code", "payGrade")
        )
        if id_field:
            return _fetch_by_ids(
                base_url,
                username,
                password,
                entity,
                fields,
                id_field,
                pay_grade_ids,
                limit,
            )
    if purpose == "pay_range" and pay_range_ids:
        id_field = _first_existing_field(
            entity_fields, ("externalCode", "code", "payRange")
        )
        if id_field:
            return _fetch_by_ids(
                base_url,
                username,
                password,
                entity,
                fields,
                id_field,
                pay_range_ids,
                limit,
            )
    if country_filter:
        country_field = _first_existing_field(
            entity_fields,
            ("country", "countryOfCompany", "company", "location", "cust_Country"),
        )
        if country_field:
            rows = _entity_results_filtered(
                base_url,
                username,
                password,
                entity,
                fields,
                _country_filter_expr(country_field, country_filter),
                limit,
            )
            return rows
    return _entity_results_paged(
        base_url, username, password, entity, fields, limit=limit
    )


def _fetch_by_ids(
    base_url: str,
    username: str,
    password: str,
    entity: str,
    fields: list[str],
    id_field: str,
    ids: list[str],
    limit: int,
    batch_size: int = 20,
) -> list[dict]:
    rows = []
    for batch in _chunks(_unique_preserve_order(ids), batch_size):
        if len(rows) >= limit:
            break
        expr = " or ".join(f"{id_field} eq '{_odata_quote(value)}'" for value in batch)
        rows.extend(
            _entity_results_filtered(
                base_url, username, password, entity, fields, expr, limit - len(rows)
            )
        )
    return rows[:limit]


def _get_country_options(
    base_url: str,
    username: str,
    password: str,
    properties: dict[str, set[str]],
    resolved: dict[str, str | None],
) -> list[dict]:
    options: dict[str, dict] = {}
    sources = []
    emp_job = resolved.get("emp_job")
    position = resolved.get("position")
    user_entity = "User" if "User" in properties else None
    for entity, preferred in (
        (emp_job, ("countryOfCompany", "country", "company", "location")),
        (position, ("cust_Country", "country", "company", "location")),
        (user_entity, ("country", "countryOfCompany", "location")),
    ):
        if not entity:
            continue
        field = _first_existing_field(properties.get(entity, set()), preferred)
        if field:
            sources.append((entity, field))
    for entity, field in sources:
        rows = _entity_results_paged(
            base_url, username, password, entity, [field], limit=2000
        )
        for row in rows:
            value = row.get(field)
            if value in (None, ""):
                continue
            key = str(value).strip()
            if not key:
                continue
            options.setdefault(
                key,
                {"value": key, "label": key, "source": f"{entity}.{field}", "count": 0},
            )
            options[key]["count"] += 1
    for code, name in COUNTRY_OPTIONS:
        options.setdefault(
            code,
            {
                "value": code,
                "label": f"{name} ({code})",
                "source": "standard",
                "count": 0,
            },
        )
    return sorted(options.values(), key=lambda x: (0 if x["count"] else 1, x["label"]))[
        :300
    ]


def _evidence_fields_for(purpose: str, entity: str, fields: set[str]) -> list[str]:
    preferred_by_purpose = {
        "pay_grade": (
            "externalCode",
            "code",
            "name",
            "paygradeLevel",
            "startDate",
            "endDate",
            "status",
        ),
        "pay_range": (
            "externalCode",
            "code",
            "name",
            "minimum",
            "midpoint",
            "maximum",
            "currency",
            "startDate",
            "endDate",
        ),
        "job_code": (
            "externalCode",
            "code",
            "name",
            "grade",
            "jobFunction",
            "jobLevel",
            "startDate",
            "endDate",
            "status",
        ),
        "position": (
            "code",
            "externalName_defaultValue",
            "jobCode",
            "jobTitle",
            "payGrade",
            "payRange",
            "cust_PayRange_Min",
            "cust_PayRange_Mid",
            "cust_PayRange_Max",
            "cust_PayRangeCurrency",
            "company",
            "location",
            "cust_Country",
            "effectiveStartDate",
            "effectiveEndDate",
        ),
        "emp_job": (
            "userId",
            "jobCode",
            "position",
            "payGrade",
            "company",
            "location",
            "countryOfCompany",
            "startDate",
            "endDate",
        ),
        "employment": (
            "userId",
            "personIdExternal",
            "personId",
            "startDate",
            "endDate",
            "assignmentClass",
            "employmentId",
        ),
        "person": (
            "personIdExternal",
            "personId",
            "dateOfBirth",
            "countryOfBirth",
            "createdOn",
            "lastModifiedOn",
        ),
        "comp": (
            "userId",
            "payComponent",
            "paycompvalue",
            "currencyCode",
            "frequency",
            "startDate",
            "endDate",
            "seqNumber",
        ),
        "user": (
            "userId",
            "personIdExternal",
            "gender",
            "country",
            "department",
            "division",
            "location",
        ),
        "personal": ("personIdExternal", "personId", "gender", "startDate", "endDate"),
        "requisition": (
            "jobReqId",
            "templateName",
            "country",
            "currency",
            "salaryMin",
            "salaryMax",
            "payRange",
            "compensation",
        ),
        "req_locale": (
            "jobReqId",
            "locale",
            "externalTitle",
            "externalJobDescription",
            "jobDescription",
            "status",
        ),
        "offer": ("offerId", "jobReqId", "salary", "currency", "templateId", "status"),
        "workflow": (
            "wfRequestId",
            "status",
            "createdBy",
            "createdOn",
            "lastModifiedOn",
        ),
        "permission": ("userId", "roleId", "permission", "target", "lastModifiedOn"),
    }
    selected = [
        field for field in preferred_by_purpose.get(purpose, ()) if field in fields
    ]
    if purpose in ("requisition", "position", "pay_range", "offer"):
        selected.extend(
            field
            for field in _matching_fields({entity: fields}, entity, PAY_TEXT_MARKERS)
            if field not in selected
        )
    if not selected:
        selected = _default_select_fields(fields)
    return selected[:20]


def _quality_for_rows(rows: list[dict], fields: list[str]) -> dict:
    total = len(rows)
    populated = {}
    for field in fields:
        count = sum(1 for row in rows if row.get(field) not in (None, ""))
        populated[field] = {
            "populated": count,
            "coveragePct": round((count / total) * 100) if total else 0,
        }
    return {
        "rows": total,
        "fieldCoverage": populated,
    }


def _mask_row(row: dict) -> dict:
    masked = {}
    for key, value in row.items():
        lower = key.lower()
        if any(marker in lower for marker in SENSITIVE_FIELD_MARKERS):
            masked[key] = _mask_value(value)
        else:
            masked[key] = value
    return masked


def _mask_value(value):
    if value in (None, ""):
        return value
    text = str(value)
    if len(text) <= 4:
        return "***"
    return f"{text[:2]}***{text[-2:]}"


def _calculate_article9(evidence: dict, resolved: dict[str, str | None]) -> dict:
    raw = evidence.get("_raw", {})
    comp_rows = raw.get("comp", [])
    user_rows = raw.get("user", [])
    personal_rows = raw.get("personal", [])
    employment_rows = raw.get("employment", [])
    person_rows = raw.get("person", [])
    emp_job_rows = raw.get("emp_job", [])
    position_rows = raw.get("position", [])

    gender_by_user = {}
    gender_by_person = {}
    person_by_user = {}
    for row in user_rows:
        uid = _first_value(row, ("userId", "personIdExternal"))
        person_id = _first_value(row, ("personIdExternal", "personId"))
        gender = _normalise_gender(row.get("gender"))
        if uid and person_id:
            person_by_user[str(uid)] = str(person_id)
        if uid and gender:
            gender_by_user[str(uid)] = gender
        if person_id and gender:
            gender_by_person[str(person_id)] = gender
    for row in personal_rows:
        uid = _first_value(row, ("personIdExternal", "personId", "userId"))
        gender = _normalise_gender(row.get("gender"))
        if uid and gender:
            gender_by_person[str(uid)] = gender
            gender_by_user.setdefault(str(uid), gender)
    for row in employment_rows:
        uid = _first_value(row, ("userId", "employmentId"))
        person_id = _first_value(row, ("personIdExternal", "personId"))
        if uid and person_id:
            person_by_user[str(uid)] = str(person_id)
            if str(person_id) in gender_by_person:
                gender_by_user[str(uid)] = gender_by_person[str(person_id)]
    for row in person_rows:
        uid = _first_value(row, ("personIdExternal", "personId"))
        if uid and str(uid) in gender_by_person:
            gender_by_user.setdefault(str(uid), gender_by_person[str(uid)])

    job_by_user = {}
    for row in emp_job_rows:
        uid = _first_value(row, ("userId", "personIdExternal"))
        if uid:
            job_by_user[str(uid)] = row

    position_by_code = {}
    for row in position_rows:
        code = _first_value(row, ("code", "externalCode"))
        if code:
            position_by_code[str(code)] = row

    pay_records = []
    for row in comp_rows:
        uid = _first_value(row, ("userId", "personIdExternal"))
        amount = _to_float(_first_value(row, ("paycompvalue", "amount", "salary")))
        if not uid or amount is None:
            continue
        uid = str(uid)
        gender = gender_by_user.get(uid)
        if not gender and uid in person_by_user:
            gender = gender_by_person.get(person_by_user[uid])
        job = job_by_user.get(uid, {})
        position = (
            position_by_code.get(str(job.get("position")), {})
            if job.get("position")
            else {}
        )
        category = _worker_category(job, position)
        country = (
            _first_value(job, ("countryOfCompany", "country", "company", "location"))
            or _first_value(position, ("cust_Country", "company", "location"))
            or "Unmapped"
        )
        component = str(row.get("payComponent") or "")
        pay_records.append(
            {
                "userId": uid,
                "gender": gender,
                "amount": amount,
                "currency": row.get("currencyCode"),
                "component": component,
                "isVariable": _is_variable_component(component),
                "category": str(category or "Unmapped"),
                "country": str(country or "Unmapped"),
            }
        )

    usable = [row for row in pay_records if row["gender"] in ("female", "male")]
    groups = {}
    for row in usable:
        key = (row["country"], row["category"], row.get("currency") or "")
        groups.setdefault(key, []).append(row)

    category_results = []
    for (country, category, currency), rows in sorted(groups.items()):
        female = [row["amount"] for row in rows if row["gender"] == "female"]
        male = [row["amount"] for row in rows if row["gender"] == "male"]
        if not female or not male:
            continue
        male_mean = _mean(male)
        female_mean = _mean(female)
        male_median = _median(male)
        female_median = _median(female)
        variable_rows = [row for row in rows if row["isVariable"]]
        category_results.append(
            {
                "country": country,
                "workerCategory": category,
                "currency": currency,
                "employees": len({row["userId"] for row in rows}),
                "femaleCount": len(female),
                "maleCount": len(male),
                "meanFemalePay": round(female_mean, 2),
                "meanMalePay": round(male_mean, 2),
                "meanGapPct": _gap_pct(male_mean, female_mean),
                "medianFemalePay": round(female_median, 2),
                "medianMalePay": round(male_median, 2),
                "medianGapPct": _gap_pct(male_median, female_median),
                "variableComponentRecords": len(variable_rows),
                "jointAssessmentFlag": abs(_gap_pct(male_mean, female_mean) or 0) >= 5,
            }
        )

    all_amounts = sorted(usable, key=lambda row: row["amount"])
    quartiles = _quartile_distribution(all_amounts)
    return {
        "status": "prototype_calculated" if category_results else "insufficient_data",
        "recordsAnalysed": len(pay_records),
        "recordsWithGender": len(usable),
        "genderCoveragePct": round((len(usable) / len(pay_records)) * 100)
        if pay_records
        else 0,
        "joinDiagnostics": {
            "compRows": len(comp_rows),
            "userRows": len(user_rows),
            "personalRows": len(personal_rows),
            "employmentRows": len(employment_rows),
            "personRows": len(person_rows),
            "genderByUserCount": len(gender_by_user),
            "genderByPersonCount": len(gender_by_person),
            "personByUserCount": len(person_by_user),
            "empJobRows": len(emp_job_rows),
            "positionRows": len(position_rows),
        },
        "categoryResults": category_results,
        "quartileDistribution": quartiles,
        "limitations": _article9_limitations(
            evidence, pay_records, usable, category_results
        ),
    }


def _worker_category(job: dict, position: dict):
    return (
        _first_value(job, ("jobCode", "payGrade", "position"))
        or _first_value(
            position, ("jobCode", "jobLevel", "payGrade", "payRange", "code")
        )
        or "Unmapped"
    )


def _article9_limitations(
    evidence: dict,
    pay_records: list[dict],
    usable: list[dict],
    category_results: list[dict],
) -> list[str]:
    notes = []
    if not pay_records:
        notes.append(
            "No compensation records with numeric pay values were available in the evidence pull."
        )
    if pay_records and not usable:
        notes.append(
            "Compensation records were found, but gender could not be joined for prototype Article 9-style calculations."
        )
    if usable and not category_results:
        notes.append(
            "Gendered pay records were found, but each worker category needs both male and female records to calculate gaps."
        )
    notes.append(
        "Prototype uses the capped evidence pull, not a full tenant audit. Increase the limit or add full audit mode for production evidence."
    )
    notes.append(
        "Worker category mapping is inferred from job/position/pay grade fields and should be validated by HR/legal."
    )
    notes.append(
        "Prototype calculations use available pay component rows and do not certify gross annual pay, gross hourly pay, ordinary basic pay, complementary or variable components, or national reporting formats."
    )
    notes.append(
        "Privacy suppression and small-population controls are not enforced before displaying category averages."
    )
    return notes


def _quartile_distribution(rows: list[dict]) -> list[dict]:
    if not rows:
        return []
    quartiles = []
    size = math.ceil(len(rows) / 4)
    for i in range(4):
        slice_rows = rows[i * size : (i + 1) * size]
        if not slice_rows:
            continue
        quartiles.append(
            {
                "quartile": i + 1,
                "records": len(slice_rows),
                "female": sum(1 for row in slice_rows if row["gender"] == "female"),
                "male": sum(1 for row in slice_rows if row["gender"] == "male"),
                "minPay": round(slice_rows[0]["amount"], 2),
                "maxPay": round(slice_rows[-1]["amount"], 2),
            }
        )
    return quartiles


def _normalise_gender(value) -> str | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in ("f", "female", "woman", "w"):
        return "female"
    if text in ("m", "male", "man"):
        return "male"
    return None


def _is_variable_component(component: str) -> bool:
    text = component.lower()
    return any(
        marker in text
        for marker in (
            "bonus",
            "var",
            "commission",
            "incentive",
            "allowance",
            "stock",
            "equity",
        )
    )


def _first_value(row: dict, fields: tuple[str, ...]):
    for field in fields:
        value = row.get(field)
        if value not in (None, ""):
            return value
    return None


def _to_float(value) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(str(value).replace(",", ""))
    except ValueError:
        return None


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    sorted_values = sorted(values)
    mid = len(sorted_values) // 2
    if len(sorted_values) % 2:
        return sorted_values[mid]
    return (sorted_values[mid - 1] + sorted_values[mid]) / 2


def _gap_pct(reference: float, comparison: float) -> float | None:
    if not reference:
        return None
    return round(((reference - comparison) / reference) * 100, 2)


def _bounded_int(value, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_snippet(body: bytes, content_type: str) -> str:
    if "html" in (content_type or "").lower():
        return "Received HTML instead of OData. Check API base URL and credentials."
    return body[:500].decode("utf-8", errors="replace").replace("\n", " ")


if __name__ == "__main__":
    port = int(os.getenv("PORT", str(PORT)))
    server = ThreadingHTTPServer((HOST, port), PayTransparencyHandler)
    print(f"SF Pay Transparency app running at http://localhost:{port}")
    if LIVE_MODE:
        print(
            "Live tenant mode enabled: credentials and OData endpoints are available locally."
        )
    else:
        print(
            "Demo-safe mode: set SFPT_LIVE_MODE=1 to enable local SuccessFactors OData checks."
        )
    server.serve_forever()
