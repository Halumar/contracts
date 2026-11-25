#!/usr/bin/env python3
"""Generate and annotate openapi/hub.openapi.json from the hub's FastAPI app.

Run with a Python environment that has the hub requirements installed,
from any working directory:

    python tools/snapshot_openapi.py --app-dir <hub>/halumar/rootfs/opt/hub
    python tools/snapshot_openapi.py --app-dir ... --check   # CI: fail on drift

The app is imported, not started: image and database paths are pointed at a
temporary directory (the code reads them at import time). The raw FastAPI
schema is then annotated with what FastAPI cannot know: security per operation
(derived from the route source: require_admin / require_integration / public
paths), functional tags, external response schemas from schemas/, TODO markers
for ad-hoc responses, unused endpoints and known deviations (docs/protocol.md).
"""

from __future__ import annotations

import argparse
import copy
import inspect
import json
import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "openapi" / "hub.openapi.json"
NAMESPACE = json.loads((REPO / "namespace.json").read_text())
# Functional names that do not depend on the namespace, as in the hub's api/auth.py
# and services/integration_status.py.
SESSION_COOKIE = "hub_session"
CSRF_COOKIE = "hub_csrf"
INTEGRATION_VERSION_HEADER = "X-Hub-Integration-Version"

TAGS = [
    ("system", "Health, logs, restart, TLS."),
    ("auth", "Login/session for the Admin UI and admin API tokens."),
    ("areas", "Areas, sections, entity placements, layout, widgets, tags."),
    ("ha-data", "Read-through of Home Assistant states and registries."),
    ("sync-export", "Import from HA, export/import of areas."),
    ("pairing", "PIN window and REST pairing."),
    ("clients", "Paired devices and guests: management, name, owner."),
    ("settings", "Global hub settings (most PUTs broadcast client_config_updated)."),
    ("token-automation", "Per-device HA token rotation (the integration mints the token)."),
    ("notifications", "Notifications to devices."),
    ("profiles", "Profile model: profiles, suggestions, default profiles, device adjustments, own area, effective rules."),
    ("kids", "Kids mode: rule test, status and parent release of a device; the device control path."),
    ("family", "Family manager: children and notify targets of a family manager, overview, house settings, answers of the admin; away route and notification answers of the integration."),
    ("log", "Log tab: activity, changes and alarms, retention, notifications at events."),
    ("integration", "Surface of the companion HA integration (integration token only)."),
    ("static", "Admin UI assets and uploaded images (not part of the API contract)."),
]

# Endpoints without a caller in the hub admin UI, the integration or the apps.
UNUSED = {
    ("get", "/api/integration/devices"): "Not used by the integration.",
    ("get", "/api/areas/{area_id}/sections"): "Unused.",
    ("get", "/api/areas/{area_id}/widgets"): "Unused.",
    ("put", "/api/areas/{area_id}"): "Admin UI uses PATCH.",
    ("delete", "/api/pairing/clients/{client_id}"): "Admin UI uses /permanent.",
    ("delete", "/api/pairing/clients/{client_id}/tombstone"): "No UI.",
    ("get", "/api/pairing/clients/{client_id}/area-visibility/{area_id}"): "No UI.",
    ("get", "/api/ha/entities/{entity_id}"): "Unused.",
    ("get", "/api/ha/devices"): "Unused.",
    ("get", "/api/ha/domains"): "Unused.",
    ("get", "/api/export/areas/{area_id}"): "Unused.",
    ("get", "/api/notifications/icons"): "Unused.",
}

DEVIATIONS = {
    ("put", "/api/settings/app-url"): "Known deviation D11 (docs/protocol.md): no client_config_updated broadcast, no URL validation.",
}

EXTERNAL_RESPONSES = {
    ("get", "/api/health"): "../schemas/rest/health.json",
    ("get", "/api/integration/status"): "../schemas/integration/status.response.json",
    ("get", "/api/integration/devices"): "../schemas/integration/devices.response.json",
    ("post", "/api/integration/start-pairing"): "../schemas/integration/start-pairing.response.json",
    ("post", "/api/integration/areas/{area_id}/activate"): "../schemas/integration/area-activation.response.json",
    ("post", "/api/integration/areas/{area_id}/deactivate"): "../schemas/integration/area-activation.response.json",
    ("post", "/api/integration/clients/{client_id}/navigate_to_area"): "../schemas/integration/client-command.response.json",
    ("post", "/api/integration/clients/{client_id}/show_entity"): "../schemas/integration/client-command.response.json",
    ("post", "/api/integration/clients/{client_id}/refresh"): "../schemas/integration/client-command.response.json",
    ("post", "/api/integration/notify"): "../schemas/integration/notify.response.json",
    ("post", "/api/notifications"): "../schemas/integration/notify.response.json",
    ("post", "/api/integration/clients/{client_id}/kick"): "../schemas/integration/kick.response.json",
    ("post", "/api/integration/pairing/cancel"): "../schemas/integration/pairing-cancel.response.json",
    ("post", "/api/integration/clients/{client_id}/clear_notifications"): "../schemas/integration/clear-notifications.response.json",
    ("post", "/api/integration/notifications/ack"): "../schemas/integration/notifications-ack.response.json",
    # Notifications queued while the hub was unreachable
    ("post", "/api/integration/notifications/handover"): "../schemas/integration/notifications-handover.response.json",
    ("post", "/api/integration/clients/{client_id}/tags"): "../schemas/integration/client-tags.response.json",
    ("post", "/api/integration/clients/{client_id}/extend"): "../schemas/integration/extend.response.json",
    ("patch", "/api/clients/{client_id}/extend"): "../schemas/integration/extend.response.json",
    # One Home Assistant user per device
    ("post", "/api/integration/client-token"): "../schemas/integration/client-token.response.json",
    # Remote access: external Home Assistant URL
    ("post", "/api/integration/ha-url"): "../schemas/integration/ha-url.response.json",
    # Device activity feed
    ("get", "/api/pairing/clients/{client_id}/activity"): "../schemas/rest/device-activity.response.json",
    # 200 and 202 share the body (status pending / rotation_requested)
    ("post", "/api/clients/{client_id}/rotate-token"): "../schemas/rest/rotate-token.response.json",
    # Set up a device from a paired device
    ("get", "/api/pairing/onboarding"): "../schemas/rest/onboarding-sessions.response.json",
    # Guest invitations by members
    ("get", "/api/pairing/guest-invites"): "../schemas/rest/guest-invites.response.json",
    # Quick access
    ("get", "/api/quick-access"): "../schemas/rest/quick-access.response.json",
    ("put", "/api/quick-access/{entity_id}"): "../schemas/rest/quick-access.response.json",
    # Kids mode at run time (the profiles themselves follow below)
    ("post", "/api/profiles/{profile_id}/check"): "../schemas/rest/kids-check.response.json",
    ("get", "/api/pairing/clients/{client_id}/kids-status"): "../schemas/rest/kids-status.response.json",
    ("post", "/api/pairing/clients/{client_id}/kids-override"): "../schemas/rest/kids-status.response.json",
    ("delete", "/api/pairing/clients/{client_id}/kids-override"): "../schemas/rest/kids-status.response.json",
    # Profile model
    ("get", "/api/profiles"): "../schemas/rest/profiles.response.json",
    ("post", "/api/profiles"): "../schemas/rest/profile.json",
    ("get", "/api/profiles/{profile_id}"): "../schemas/rest/profile.json",
    ("patch", "/api/profiles/{profile_id}"): "../schemas/rest/profile.json",
    ("post", "/api/profiles/{profile_id}/duplicate"): "../schemas/rest/profile.json",
    ("post", "/api/profiles/{profile_id}/apply-suggestion"): "../schemas/rest/profile.json",
    ("post", "/api/profiles/from-device"): "../schemas/rest/profile.json",
    ("get", "/api/profile-rules"): "../schemas/data/profile-rules.json",
    ("get", "/api/profile-suggestions"): "../schemas/rest/profile-suggestions.response.json",
    ("get", "/api/profile-audit"): "../schemas/rest/profile-audit.response.json",
    ("post", "/api/profile-suggestions/{suggestion_id}"): "../schemas/rest/profile.json",
    ("get", "/api/settings/profiles"): "../schemas/rest/profile-settings.json",
    ("put", "/api/settings/profiles"): "../schemas/rest/profile-settings.json",
    ("put", "/api/pairing/clients/{client_id}/profile"): "../schemas/rest/paired-client.json",
    ("get", "/api/pairing/clients/{client_id}/effective"): "../schemas/rest/client-effective.response.json",
    ("put", "/api/pairing/clients/{client_id}/overrides/{rule_key}"): "../schemas/rest/client-effective.response.json",
    ("delete", "/api/pairing/clients/{client_id}/overrides/{rule_key}"): "../schemas/rest/client-effective.response.json",
    ("put", "/api/pairing/clients/{client_id}/own-area"): "../schemas/rest/client-effective.response.json",
    ("put", "/api/pairing/clients/{client_id}/remote-pin"): "../schemas/rest/client-effective.response.json",
    ("post", "/api/pairing/clients/bulk"): "../schemas/rest/clients-bulk.response.json",
    ("get", "/api/pairing/clients/{client_id}"): "../schemas/rest/paired-client.json",
    ("patch", "/api/pairing/clients/{client_id}"): "../schemas/rest/paired-client.json",
    ("put", "/api/pairing/clients/{client_id}/access-switch"): "../schemas/rest/paired-client.json",
    ("post", "/api/integration/access-switch"): "../schemas/integration/access-switch.response.json",
    ("post", "/api/client/control"): "../schemas/ws/server/control_ok.json",
    ("post", "/api/client/leave"): "../schemas/ws/server/client_leave_ok.json",
    # Location
    ("post", "/api/client/location"): "../schemas/ws/server/location_report_ok.json",
    ("post", "/api/integration/location-status"): "../schemas/integration/location-status.response.json",
    # Family manager
    ("get", "/api/pairing/clients/{client_id}/family"): "../schemas/rest/client-family.response.json",
    ("put", "/api/pairing/clients/{client_id}/family"): "../schemas/rest/client-family.response.json",
    ("get", "/api/family"): "../schemas/rest/family-overview.response.json",
    ("get", "/api/settings/family"): "../schemas/rest/family-settings.json",
    ("put", "/api/settings/family"): "../schemas/rest/family-settings.json",
    ("post", "/api/family/requests/{request_id}/answer"): "../schemas/common/family-request.json",
    ("post", "/api/integration/family"): "../schemas/integration/family.response.json",
    ("post", "/api/integration/family/notify-answer"): "../schemas/integration/family-notify-answer.response.json",
    # Wall panel as a Home Assistant device
    ("get", "/api/pairing/clients/{client_id}/panel"): "../schemas/rest/client-panel.response.json",
    ("post", "/api/pairing/clients/{client_id}/panel"): "../schemas/integration/panel-command.response.json",
    ("post", "/api/integration/clients/{client_id}/panel"): "../schemas/integration/panel-command.response.json",
    # NFC/QR tags registered in the hub
    ("get", "/api/scan-tags"): "../schemas/rest/scan-tags.response.json",
    ("post", "/api/scan-tags"): "../schemas/common/scan-tag.json",
    ("put", "/api/scan-tags/{tag_id}"): "../schemas/common/scan-tag.json",
    # Early access requests
    ("get", "/api/access-requests"): "../schemas/rest/access-requests.response.json",
    ("post", "/api/access-requests/{request_id}/answer"): "../schemas/common/access-request.json",
    # Enforcement in Home Assistant
    ("get", "/api/integration/enforcement-rules"): "../schemas/integration/enforcement-rules.response.json",
    ("post", "/api/integration/kids-check"): "../schemas/integration/kids-check.response.json",
    ("post", "/api/integration/events"): "../schemas/integration/events.response.json",
    # Log tab and notifications at events
    ("get", "/api/log"): "../schemas/rest/log.response.json",
    ("get", "/api/log/export"): "../schemas/rest/log.response.json",
    ("get", "/api/log/summary"): "../schemas/rest/log-summary.response.json",
    ("post", "/api/log/read"): "../schemas/rest/log-read.response.json",
    ("get", "/api/log/settings"): "../schemas/rest/log-settings.json",
    ("put", "/api/log/settings"): "../schemas/rest/log-settings.json",
    ("get", "/api/settings/home-networks"): "../schemas/rest/home-networks.json",
    ("put", "/api/settings/home-networks"): "../schemas/rest/home-networks.json",
    ("get", "/api/areas/{area_id}/room-climate"): "../schemas/rest/room-climate.response.json",
    ("put", "/api/areas/{area_id}/room-climate"): "../schemas/rest/room-climate.response.json",
    ("get", "/api/log/notify-targets"): "../schemas/rest/notify-targets.response.json",
    ("get", "/api/settings/event-notifications"): "../schemas/rest/event-notifications.json",
    ("put", "/api/settings/event-notifications"): "../schemas/rest/event-notifications.json",
    ("post", "/api/settings/event-notifications/test"): "../schemas/rest/event-notifications-test.response.json",
}

EXTERNAL_REQUESTS = {
    ("post", "/api/integration/start-pairing"): "../schemas/integration/start-pairing.request.json",
    # Tile settings
    ("put", "/api/areas/{area_id}/entities/{entity_id}"): "../schemas/rest/area-entity-update.request.json",
    # Remote access: external Home Assistant URL
    ("post", "/api/integration/ha-url"): "../schemas/integration/ha-url.request.json",
    # Quick access
    ("put", "/api/quick-access/{entity_id}"): "../schemas/rest/quick-access.request.json",
    # Kids mode
    ("post", "/api/client/control"): "../schemas/rest/client-control.request.json",
    # A device without a hub socket signs off
    ("post", "/api/client/leave"): "../schemas/rest/client-leave.request.json",
    # Position of a device with parental controls without a hub socket
    ("post", "/api/client/location"): "../schemas/rest/client-location.request.json",
    ("post", "/api/integration/location-status"): "../schemas/integration/location-status.request.json",
    ("post", "/api/pairing/clients/{client_id}/kids-override"): "../schemas/rest/kids-override.request.json",
    ("post", "/api/profiles/{profile_id}/check"): "../schemas/rest/kids-check.request.json",
    # Notifications queued while the hub was unreachable
    ("post", "/api/integration/notifications/handover"): "../schemas/integration/notifications-handover.request.json",
    # Profile model
    ("post", "/api/profiles"): "../schemas/rest/profile-write.request.json",
    ("patch", "/api/profiles/{profile_id}"): "../schemas/rest/profile-write.request.json",
    ("post", "/api/profiles/{profile_id}/duplicate"): "../schemas/rest/profile-name.request.json",
    ("post", "/api/profiles/from-device"): "../schemas/rest/profile-from-device.request.json",
    ("post", "/api/profile-suggestions/{suggestion_id}"): "../schemas/rest/profile-name.request.json",
    ("put", "/api/settings/profiles"): "../schemas/rest/profile-settings.json",
    ("put", "/api/pairing/clients/{client_id}/profile"): "../schemas/rest/client-profile.request.json",
    ("put", "/api/pairing/clients/{client_id}/overrides/{rule_key}"): "../schemas/rest/device-override.request.json",
    ("put", "/api/pairing/clients/{client_id}/own-area"): "../schemas/rest/client-own-area.request.json",
    ("put", "/api/pairing/clients/{client_id}/remote-pin"): "../schemas/rest/client-remote-pin.request.json",
    ("post", "/api/pairing/clients/bulk"): "../schemas/rest/clients-bulk.request.json",
    ("post", "/api/pairing/generate"): "../schemas/rest/pairing-generate.request.json",
    ("patch", "/api/pairing/clients/{client_id}"): "../schemas/rest/client-update.request.json",
    ("put", "/api/pairing/clients/{client_id}/access-switch"): "../schemas/rest/access-switch.request.json",
    ("post", "/api/integration/access-switch"): "../schemas/integration/access-switch.request.json",
    # Family manager
    ("put", "/api/pairing/clients/{client_id}/family"): "../schemas/rest/client-family.request.json",
    ("put", "/api/settings/family"): "../schemas/rest/family-settings.json",
    ("post", "/api/family/requests/{request_id}/answer"): "../schemas/rest/family-answer.request.json",
    ("post", "/api/integration/family"): "../schemas/integration/family.request.json",
    ("post", "/api/integration/family/notify-answer"): "../schemas/integration/family-notify-answer.request.json",
    # Wall panel as a Home Assistant device
    ("post", "/api/pairing/clients/{client_id}/panel"): "../schemas/rest/client-panel-command.request.json",
    ("post", "/api/integration/clients/{client_id}/panel"): "../schemas/integration/panel-command.request.json",
    # NFC/QR tags registered in the hub
    ("post", "/api/scan-tags"): "../schemas/rest/scan-tag-write.request.json",
    ("put", "/api/scan-tags/{tag_id}"): "../schemas/rest/scan-tag-write.request.json",
    # Early access requests
    ("post", "/api/access-requests/{request_id}/answer"): "../schemas/rest/access-request-answer.request.json",
    # Enforcement in Home Assistant
    ("post", "/api/integration/kids-check"): "../schemas/integration/kids-check.request.json",
    ("post", "/api/integration/events"): "../schemas/integration/events.request.json",
    # Log tab and notifications at events
    ("post", "/api/log/read"): "../schemas/rest/log-read.request.json",
    ("put", "/api/log/settings"): "../schemas/rest/log-settings.json",
    ("put", "/api/settings/home-networks"): "../schemas/rest/home-networks.json",
    ("put", "/api/areas/{area_id}/room-climate"): "../schemas/rest/room-climate.request.json",
    ("put", "/api/settings/event-notifications"): "../schemas/rest/event-notifications.json",
    ("post", "/api/settings/event-notifications/test"): "../schemas/rest/event-notifications-test.request.json",
}

# Untyped request-body properties (dict in FastAPI) linked to a contract schema:
# (component schema, property) -> $ref. Object alternatives become the $ref.
EXTERNAL_PROPERTIES = {
    # Tile settings of a placement (Admin answers)
    ("AreaEntityResponse", "tile"): "../schemas/common/tile-settings.json",
}

SECURITY = {
    "public": [],
    "admin": [{"ingress": []}, {"sessionCookie": [], "csrfHeader": []}, {"adminToken": []}, {"sessionBearer": []}],
    "admin_read": [{"ingress": []}, {"sessionCookie": []}, {"adminToken": []}, {"sessionBearer": []}],
    "integration": [{"integrationToken": []}],
    # Only the Home Assistant sidebar may change who administers the hub.
    "ingress": [{"ingress": []}],
}
SECURITY["auth"] = SECURITY["admin_read"] + [{"clientBearer": []}]
# The REST paths that accept the device secret (and nothing else).
SECURITY["client"] = [{"clientBearer": []}]
CLIENT_PATHS = {"/api/client/control", "/api/client/leave", "/api/client/location"}
# A notification for a watch goes to the phone that set it up (docs/protocol.md, watches).
WATCH_FORWARD = {("post", "/api/notifications"), ("post", "/api/integration/notify")}
WATCH_FORWARD_422 = ("Validation Error, or the target is a watch whose phone (the device that set it up) is deleted, "
                     "inactive or being deleted: detail as text, nothing stored.")
WRITE_METHODS = {"post", "put", "patch", "delete"}


def tag_for(path: str, fastapi_tag: str | None) -> str:
    if not path.startswith("/api/"):
        return "static"
    if path == "/api/health" or path.startswith("/api/admin/") or path.startswith("/api/settings/tls"):
        return "system"
    if path.endswith("/rotate-token"):
        return "token-automation"
    if path in ("/api/client/control", "/api/client/location") or path.endswith(("/check", "/kids-status", "/kids-override")):
        return "kids"
    if path.startswith(("/api/family", "/api/settings/family", "/api/integration/family")) or path.endswith("/family"):
        return "family"
    if path.startswith(("/api/profiles", "/api/profile-rules", "/api/profile-suggestions", "/api/profile-audit", "/api/settings/profiles")) or path.endswith(
        ("/profile", "/effective", "/own-area", "/remote-pin", "/bulk")
    ) or "/overrides/" in path:
        return "profiles"
    if path.startswith(("/api/log", "/api/settings/event-notifications")):
        return "log"
    if path.startswith("/api/settings/"):
        return "settings"
    if path.startswith(("/api/pairing/clients", "/api/clients/", "/api/access-requests")) or path == "/api/client/leave":
        return "clients"
    if path == "/api/tags":
        return "areas"
    if path.startswith("/api/ha/"):
        return "ha-data"
    if path.startswith(("/api/sync/", "/api/export/", "/api/import/")):
        return "sync-export"
    return fastapi_tag or "system"


def load_app(app_dir: Path):
    tmp = Path(tempfile.mkdtemp(prefix="contracts-openapi-"))
    (tmp / "images").mkdir()
    os.environ["HUB_IMAGE_DIR"] = str(tmp / "images")
    os.environ["HUB_DB_PATH"] = str(tmp / "hub.db")
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(app_dir))
    import main  # noqa: PLC0415  (hub entry module)
    from api import auth  # noqa: PLC0415

    return main.app, auth


def _guard_in(func, depth: int = 2, seen=None) -> str | None:
    """Find require_integration/require_ingress/require_admin in func or helpers of its module it calls."""
    import re  # noqa: PLC0415

    seen = seen if seen is not None else set()
    if func in seen:
        return None
    seen.add(func)
    src = inspect.getsource(func)
    if "require_integration(" in src:
        return "integration"
    if "require_ingress(" in src:
        return "ingress"
    if "require_admin(" in src:
        return "admin"
    if depth == 0:
        return None
    module_globals = getattr(func, "__globals__", {})
    for name in re.findall(r"\b([A-Za-z_]\w*)\(", src):
        helper = module_globals.get(name)
        if inspect.isfunction(helper) and helper.__module__ == func.__module__:
            found = _guard_in(helper, depth - 1, seen)
            if found:
                return found
    return None


def _raises_404(func, depth: int = 2, seen=None) -> bool:
    """Whether func, or a helper of its module it calls, raises HTTPException 404."""
    import re  # noqa: PLC0415

    seen = seen if seen is not None else set()
    if func in seen:
        return False
    seen.add(func)
    src = inspect.getsource(func)
    if re.search(r"status_code\s*=\s*404\b", src):
        return True
    if depth == 0:
        return False
    module_globals = getattr(func, "__globals__", {})
    for name in re.findall(r"\b([A-Za-z_]\w*)\(", src):
        helper = module_globals.get(name)
        if inspect.isfunction(helper) and helper.__module__ == func.__module__:
            if _raises_404(helper, depth - 1, seen):
                return True
    return False


def classify(path: str, route, auth_mod) -> str:
    if not path.startswith("/api/"):
        return "public"
    if path in auth_mod.PUBLIC_PATHS or path.startswith(tuple(auth_mod.PUBLIC_PREFIXES)):
        return "public"
    if path in CLIENT_PATHS:
        return "client"
    return _guard_in(route.endpoint) or "auth"


def iter_api_routes(routes, prefix=""):
    """Yield (full_path, APIRoute); handles FastAPI's lazy _IncludedRouter (>= 0.13x)."""
    from fastapi.routing import APIRoute  # noqa: PLC0415

    for r in routes:
        if isinstance(r, APIRoute):
            yield prefix + r.path_format, r
        elif hasattr(r, "original_router") and hasattr(r, "include_context"):
            yield from iter_api_routes(r.original_router.routes, prefix + (r.include_context.prefix or ""))


def link_object(schema: dict, ref: str) -> dict:
    if schema.get("type") == "object":
        out = {k: v for k, v in schema.items() if k not in ("type", "additionalProperties")}
        return {"$ref": ref, **out}
    if "anyOf" in schema and any(s.get("type") == "object" for s in schema["anyOf"]):
        return {**schema, "anyOf": [s if s.get("type") != "object" else link_object(s, ref)
                                    for s in schema["anyOf"]]}
    raise SystemExit(f"cannot link {schema!r} to {ref}: no object schema")


def annotate(raw: dict, app, auth_mod, version: str) -> dict:
    spec = copy.deepcopy(raw)
    routes = {}
    for full_path, r in iter_api_routes(app.routes):
        if r.include_in_schema:
            for m in r.methods:
                routes[(m.lower(), full_path)] = r

    hub_version = spec["info"].get("version", "")
    spec["info"] = {
        "title": "Hub REST API",
        "version": version,
        "summary": "REST surface of the hub (Home Assistant app).",
        "description": (
            "Snapshot of the FastAPI schema of the hub "
            f"{hub_version}, annotated by tools/snapshot_openapi.py. All routes live under /api, "
            "there is no version prefix. The WebSocket /api/ws is described in "
            "asyncapi/hub-ws.asyncapi.yaml. Errors use FastAPI's {\"detail\": ...}. "
            "Unknown GET paths (also below /api) are answered by the SPA fallback with "
            "200 text/html instead of 404. Cookie and header names are functional; "
            "namespace-dependent names follow namespace.json (" + NAMESPACE["current"] + ")."
        ),
        "license": {"name": "Apache-2.0", "identifier": "Apache-2.0"},
        "x-hub-version": hub_version,
        "x-namespace": NAMESPACE["current"],
    }
    spec["servers"] = [
        {"url": "http://{host}:8099", "description": "LAN, plain HTTP (integration via Supervisor hostname, unpinned apps, LAN login)",
         "variables": {"host": {"default": "homeassistant.local"}}},
        {"url": "https://{host}:8100", "description": "LAN, TLS with self-signed leaf; clients pin the SHA-256 fingerprint (Bonjour fp, QR fp, client_config)",
         "variables": {"host": {"default": "homeassistant.local"}}},
        {"url": "https://{ha_host}/api/hassio_ingress/{ingress_token}", "description": "Home Assistant Ingress (Admin UI)",
         "variables": {"ha_host": {"default": "homeassistant.local:8123"}, "ingress_token": {"default": "INGRESS_TOKEN"}}},
    ]
    spec.pop("security", None)
    comps = spec.setdefault("components", {})
    comps["securitySchemes"] = {
        "ingress": {"type": "apiKey", "in": "header", "name": "X-Ingress-Path",
                    "description": "Home Assistant Ingress. Trusted only from the Supervisor ingress proxy (172.30.32.2, fixed by Home Assistant); loopback only with the dev flag. Grants admin."},
        "sessionCookie": {"type": "apiKey", "in": "cookie", "name": SESSION_COOKIE,
                          "description": "Admin UI session after POST /api/auth/login (HA credentials via Supervisor /auth, HA administrators only), 24 h, bound to the User-Agent. Only while direct admin access is switched on (PUT /api/settings/admin-direct-access, default off); switching it off ends every session."},
        "csrfHeader": {"type": "apiKey", "in": "header", "name": "X-CSRF-Token",
                       "description": "Required together with the session cookie for POST/PUT/PATCH/DELETE; value from the readable cookie " + CSRF_COOKIE + "."},
        "adminToken": {"type": "http", "scheme": "bearer", "bearerFormat": "hex64",
                       "description": "Admin API token (Settings > API token). Admin rights."},
        "sessionBearer": {"type": "http", "scheme": "bearer", "bearerFormat": "hex64",
                          "description": "The session token is also accepted as bearer (only while direct admin access is on). Admin rights."},
        "clientBearer": {"type": "http", "scheme": "bearer", "bearerFormat": "hex64",
                         "description": "Client secret of a paired device. As a REST credential only for POST /api/client/control (x-auth: client, kids mode), POST /api/client/location (position of a device with parental controls) and POST /api/client/leave (a device without a hub socket signs off); other paths answer 401 or 403 by require_admin."},
        "integrationToken": {"type": "http", "scheme": "bearer", "bearerFormat": "hex64",
                             "description": "Integration token from Supervisor discovery (rotated on every hub start). Valid only for /api/integration/* (403 elsewhere) and the WS push session."},
    }
    comps.setdefault("parameters", {})["IntegrationVersion"] = {
        "name": INTEGRATION_VERSION_HEADER, "in": "header", "required": False,
        "schema": {"type": "string"}, "description": "Version of the calling integration (telemetry, shown in the Admin UI).",
    }
    comps.setdefault("responses", {}).update({
        "Unauthorized": {"description": "Missing or invalid credential.",
                         "content": {"application/json": {"schema": {"type": "object", "properties": {"detail": {"type": "string"}}}}}},
        "Forbidden": {"description": "Credential valid but not allowed here (role, token scope, CSRF).",
                      "content": {"application/json": {"schema": {"type": "object", "properties": {"detail": {"type": "string"}}}}}},
        "NotFound": {"description": "Unknown resource named in the path or the body; detail names it (e.g. 'Area not found', 'Client not found', 'Section not found in area').",
                     "content": {"application/json": {"schema": {"type": "object", "properties": {"detail": {"type": "string"}}}}}},
    })
    spec["tags"] = [{"name": n, "description": desc} for n, desc in TAGS]
    for (name, prop), ref in EXTERNAL_PROPERTIES.items():
        props = comps.get("schemas", {}).get(name, {}).get("properties", {})
        if prop not in props:
            raise SystemExit(f"EXTERNAL_PROPERTIES: {name}.{prop} not in the hub schema")
        props[prop] = link_object(props[prop], ref)

    op_ids: dict[str, int] = {}
    todo_count = 0
    for path, ops in spec["paths"].items():
        for method, op in ops.items():
            route = routes.get((method, path))
            level = classify(path, route, auth_mod) if route else "public"
            op["tags"] = [tag_for(path, (op.get("tags") or [None])[0])]
            op["x-auth"] = level
            if level == "admin" and method not in WRITE_METHODS:
                op["security"] = SECURITY["admin_read"]
            else:
                op["security"] = SECURITY[level]
            if route is not None:
                name = route.endpoint.__name__
                op_ids[name] = op_ids.get(name, 0) + 1
                op["operationId"] = name if op_ids[name] == 1 else f"{name}_{method}"
            responses = op.setdefault("responses", {})
            if level != "public":
                responses.setdefault("401", {"$ref": "#/components/responses/Unauthorized"})
                if level in ("admin", "integration", "ingress"):
                    responses.setdefault("403", {"$ref": "#/components/responses/Forbidden"})
            if route is not None and path.startswith("/api/") and _raises_404(route.endpoint):
                responses.setdefault("404", {"$ref": "#/components/responses/NotFound"})
            if level == "integration":
                params = op.setdefault("parameters", [])
                params.append({"$ref": "#/components/parameters/IntegrationVersion"})
            key = (method, path)
            if key in EXTERNAL_REQUESTS:
                required = bool(op.get("requestBody", {}).get("required", False))
                op["requestBody"] = {"required": required, "content": {"application/json": {"schema": {"$ref": EXTERNAL_REQUESTS[key]}}}}
            ok_code = next((c for c in ("200", "201") if c in responses), None)
            if ok_code and key in EXTERNAL_RESPONSES:
                responses[ok_code]["content"] = {"application/json": {"schema": {"$ref": EXTERNAL_RESPONSES[key]}}}
            elif ok_code:
                content = responses[ok_code].get("content", {})
                schema = content.get("application/json", {}).get("schema")
                if schema == {} and path.startswith("/api/"):
                    op["x-todo"] = "Response not modelled (free-form object)."
                    todo_count += 1
            if key in UNUSED:
                op["x-unused"] = UNUSED[key]
            if key in DEVIATIONS:
                op["x-known-deviation"] = DEVIATIONS[key]
            if key in WATCH_FORWARD and "422" in responses:
                responses["422"]["description"] = WATCH_FORWARD_422
            if path == "/api/health":
                responses["503"] = {"description": "Database not usable (same body, status 'error').",
                                    "content": {"application/json": {"schema": {"$ref": EXTERNAL_RESPONSES[key]}}}}
            if path == "/api/clients/{client_id}/rotate-token":
                schema = {"$ref": EXTERNAL_RESPONSES[key]}
                responses["202"] = {"description": "Rotation stored and still running: status rotation_requested (sent to the integration) or pending (integration not connected).",
                                    "content": {"application/json": {"schema": schema}}}
                responses["404"] = {"description": "Unknown device."}
                responses["409"] = {"description": "Device not active or without an HA token yet."}
            if path == "/api/integration/pairing-qr":
                op["parameters"] = [{
                    "name": "X-Pairing-Qr",
                    "in": "header",
                    "required": False,
                    "description": "accept = the integration can show the QR code (it checks pairing_qr_camera and "
                    "never caches it). Without it the hub always sends the status image and writes no audit entry.",
                    "schema": {"enum": ["accept"]},
                }]
                responses["200"] = {
                    "description": "PNG of the integration's pairing camera. A status image (PAIRING / STANDBY, with a "
                    "line why no QR is shown) and X-Pairing-Pin: omitted, unless the hub option pairing_qr_camera "
                    "allows the open window (guests: guest windows only, all: every window; reported as "
                    "pairing_qr_camera in GET /api/integration/status): then the QR of the canonical pairing deep link "
                    "(contains the PIN), X-Pairing-Pin: included and X-Pairing-Kind. Never cached; after the window "
                    "ends or the PIN is used the next request gets the status image.",
                    "headers": {
                        "X-Pairing-Active": {"schema": {"enum": ["true", "false"]}},
                        "X-Pairing-Remaining": {"schema": {"type": "string", "pattern": "^[0-9]+$"}},
                        "X-Pairing-Pin": {
                            "description": "included = the image is the QR with the PIN; omitted = a status image without it.",
                            "schema": {"enum": ["included", "omitted"]},
                        },
                        "X-Pairing-Kind": {
                            "description": "Only with X-Pairing-Pin: included. guest = a guest pairing window (the PIN only "
                            "creates a guest with the profile and end fixed when the window opened); device = any other window.",
                            "schema": {"enum": ["guest", "device"]},
                        },
                        "X-Pairing-Window": {
                            "description": "Only with X-Pairing-Pin: included. Opaque id of the pairing window (not "
                            "derived from the PIN); the integration ends a camera stream when it changes.",
                            "schema": {"type": "string", "pattern": "^[0-9]+$"},
                        },
                    },
                    "content": {"image/png": {"schema": {"type": "string", "contentMediaType": "image/png"}}},
                }
            if not path.startswith("/api/"):
                op["x-internal"] = True
    spec["x-todo-count"] = todo_count
    spec["x-websocket"] = {"path": "/api/ws", "spec": "../asyncapi/hub-ws.asyncapi.yaml"}
    order = ["openapi", "info", "servers", "tags", "paths", "components", "x-websocket", "x-todo-count"]
    return {k: spec[k] for k in order if k in spec}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--app-dir", required=True, type=Path, help="<hub repo>/halumar/rootfs/opt/hub")
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--check", action="store_true", help="compare instead of writing; exit 1 on drift")
    args = ap.parse_args()

    app, auth_mod = load_app(args.app_dir.resolve())
    version = (REPO / "VERSION").read_text().strip()
    spec = annotate(app.openapi(), app, auth_mod, version)
    text = json.dumps(spec, indent=2, ensure_ascii=False) + "\n"
    if args.check:
        current = args.out.read_text() if args.out.exists() else ""
        if current != text:
            print(f"DRIFT: {args.out} is not up to date with the hub code. Re-run without --check.")
            return 1
        print("OpenAPI snapshot up to date.")
        return 0
    args.out.write_text(text)
    n_ops = sum(len(v) for v in spec["paths"].values())
    print(f"wrote {args.out} ({len(spec['paths'])} paths, {n_ops} operations, {spec['x-todo-count']} responses without a model)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
