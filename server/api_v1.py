from datetime import date, datetime
from typing import Any


def ok(data: Any) -> dict[str, Any]:
    """Create a standard successful API response."""
    return {
        "ok": True,
        "data": data,
    }

def err(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    """Create a standard API error response."""
    error: dict[str, Any] = {"code": code, "message": message}
    if details:
        error["details"] = details
    return {"ok": False, "error": error}
def parse_date(value: Any) -> date:
    """Parse an API date in ISO or DD/MM/YYYY format."""
    if not isinstance(value, str):
        raise ValueError("date must be a string")

    value = value.strip()

    if len(value) == 10 and value[4] == "-" and value[7] == "-":
        try:
            return date.fromisoformat(value)
        except ValueError:
            pass

    if len(value) == 10 and value[2] == "/" and value[5] == "/":
        try:
            return datetime.strptime(value, "%d/%m/%Y").date()
        except ValueError:
            pass

    raise ValueError("date must use YYYY-MM-DD or DD/MM/YYYY")


def openapi_document() -> dict[str, Any]:
    """Return the public API OpenAPI document as packaged Python data."""
    bearer = [{"BearerAuth": []}]
    public = []
    json_response = {
        "200": {
            "description": "Successful JSON response",
            "content": {
                "application/json": {
                    "schema": {"$ref": "#/components/schemas/ApiSuccess"}
                }
            },
        },
        "400": {"description": "Invalid request"},
        "401": {"description": "Authentication required"},
        "403": {"description": "Insufficient scope or invalid CSRF"},
        "404": {"description": "Resource not found"},
        "429": {"description": "Rate limit exceeded"},
    }
    session_id = {
        "name": "sessionId",
        "in": "path",
        "required": True,
        "schema": {"type": "string"},
    }

    return {
        "openapi": "3.1.0",
        "info": {
            "title": "Phenikaa Calendar Exporter Public API",
            "version": "1.0.0",
            "description": (
                "Public API for health checks, one-shot calendar exports, "
                "API tokens, Phenikaa sessions, exports, and sync history."
            ),
        },
        "servers": [{"url": "/"}],
        "security": bearer,
        "tags": [
            {"name": "Health"},
            {"name": "Export"},
            {"name": "Tokens"},
            {"name": "Sessions"},
            {"name": "Sync"},
        ],
        "components": {
            "securitySchemes": {
                "BearerAuth": {
                    "type": "http",
                    "scheme": "bearer",
                    "bearerFormat": "API token",
                    "description": "Use Authorization: Bearer <token>.",
                },
                "SessionCookie": {
                    "type": "apiKey",
                    "in": "cookie",
                    "name": "phenikaa_server_session",
                },
                "CsrfHeader": {
                    "type": "apiKey",
                    "in": "header",
                    "name": "X-CSRF-Token",
                },
            },
            "schemas": {
                "ApiError": {
                    "type": "object",
                    "required": ["ok", "error"],
                    "properties": {
                        "ok": {"const": False},
                        "error": {
                            "type": "object",
                            "required": ["code", "message"],
                            "properties": {
                                "code": {"type": "string"},
                                "message": {"type": "string"},
                            },
                        },
                    },
                },
                "ApiSuccess": {
                    "type": "object",
                    "required": ["ok", "data"],
                    "properties": {
                        "ok": {"const": True},
                        "data": {"type": "object"},
                    },
                },
                "ExportRequest": {
                    "type": "object",
                    "required": ["start", "end"],
                    "properties": {
                        "start": {
                            "type": "string",
                            "description": "Start date: YYYY-MM-DD or DD/MM/YYYY.",
                        },
                        "end": {
                            "type": "string",
                            "description": "End date: YYYY-MM-DD or DD/MM/YYYY.",
                        },
                        "userId": {"type": "string"},
                        "tokenJWT": {
                            "type": "string",
                            "writeOnly": True,
                        },
                        "bootstrapHtml": {
                            "type": "string",
                            "writeOnly": True,
                        },
                    },
                    "description": (
                        "Provide either bootstrapHtml or both userId and tokenJWT."
                    ),
                },
                "SessionRequest": {
                    "type": "object",
                    "properties": {
                        "label": {"type": "string", "maxLength": 80},
                        "rangeStart": {"type": "string", "format": "date"},
                        "rangeEnd": {"type": "string", "format": "date"},
                        "syncIntervalHours": {
                            "type": "number",
                            "minimum": 0.25,
                            "maximum": 720,
                        },
                    },
                },
            },
        },
        "paths": {
            "/api/v1/openapi.json": {
                "get": {
                    "tags": ["Health"],
                    "summary": "Get the OpenAPI document",
                    "security": public,
                    "responses": {
                        "200": {
                            "description": "OpenAPI 3.1 JSON document",
                            "content": {
                                "application/json": {
                                    "schema": {"type": "object"}
                                }
                            },
                        }
                    },
                }
            },
            "/api/v1/health": {
                "get": {
                    "tags": ["Health"],
                    "summary": "Check server health",
                    "security": public,
                    "responses": json_response,
                }
            },
            "/api/v1/status": {
                "get": {
                    "tags": ["Health"],
                    "summary": "Get upstream service status",
                    "security": public,
                    "parameters": [{
                        "name": "refresh",
                        "in": "query",
                        "schema": {"type": "boolean"},
                    }],
                    "responses": json_response,
                }
            },
            "/api/v1/export/one-shot": {
                "post": {
                    "tags": ["Export"],
                    "summary": "Export a calendar without creating a persistent session",
                    "security": public,
                    "parameters": [{
                        "name": "format",
                        "in": "query",
                        "schema": {
                            "type": "string",
                            "enum": ["json", "ics", "xlsx", "zip"],
                            "default": "json",
                        },
                    }],
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/ExportRequest"}
                            }
                        },
                    },
                    "responses": {
                        **json_response,
                        "201": {"description": "Reserved"},
                        "413": {"description": "Request body too large"},
                        "502": {"description": "Upstream export failed"},
                    },
                }
            },
            "/api/v1/me": {
                "get": {
                    "tags": ["Tokens"],
                    "summary": "Get the authenticated token owner",
                    "responses": json_response,
                }
            },
            "/api/v1/tokens": {
                "get": {
                    "tags": ["Tokens"],
                    "summary": "List the owner's API tokens",
                    "responses": json_response,
                },
                "post": {
                    "tags": ["Tokens"],
                    "summary": "Create an API token using the signed-in browser session",
                    "security": [{"SessionCookie": [], "CsrfHeader": []}],
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "name": {"type": "string", "maxLength": 100},
                                        "scopes": {
                                            "type": "array",
                                            "items": {"type": "string"},
                                        },
                                    },
                                }
                            }
                        },
                    },
                    "responses": {
                        "201": {"description": "Token created; secret is returned once"},
                        "400": {"description": "Invalid request or scope"},
                        "401": {"description": "Browser session required"},
                        "403": {"description": "Valid CSRF token required"},
                    },
                },
            },
            "/api/v1/tokens/{tokenId}/revoke": {
                "post": {
                    "tags": ["Tokens"],
                    "summary": "Revoke an API token",
                    "parameters": [{
                        "name": "tokenId",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "string"},
                    }],
                    "responses": json_response,
                }
            },
            "/api/v1/sessions": {
                "get": {
                    "tags": ["Sessions"],
                    "summary": "List sessions owned by the token owner",
                    "responses": json_response,
                },
                "post": {
                    "tags": ["Sessions"],
                    "summary": "Create a Phenikaa session",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/SessionRequest"}
                            }
                        },
                    },
                    "responses": {
                        **json_response,
                        "201": {"description": "Session created"},
                        "409": {"description": "Session already exists"},
                    },
                },
            },
            "/api/v1/sessions/{sessionId}": {
                "parameters": [session_id],
                "get": {
                    "tags": ["Sessions"],
                    "summary": "Get a session and recent sync activity",
                    "responses": json_response,
                },
                "patch": {
                    "tags": ["Sessions"],
                    "summary": "Update session settings",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/SessionRequest"}
                            }
                        },
                    },
                    "responses": json_response,
                },
                "delete": {
                    "tags": ["Sessions"],
                    "summary": "Delete a session and clean up related resources",
                    "description": "Disables the session, removes its browser profile and exports, then deletes it. The owner's Google calendar is kept unless calendar=hide or calendar=delete is given.",
                    "parameters": [
                        session_id,
                        {"name": "calendar", "in": "query", "required": False,
                         "description": "What to do with the owner's Google calendar.",
                         "schema": {"type": "string", "enum": ["keep", "hide", "delete"], "default": "keep"}},
                    ],
                    "responses": {
                        **json_response,
                        "400": {"description": "invalid_request: calendar must be keep, hide, or delete"},
                        "409": {"description": "conflict_running: a sync or sign-in is using the session; retry shortly"},
                    },
                },
            },
            "/api/v1/sessions/{sessionId}/events": {
                "get": {
                    "tags": ["Sessions"],
                    "summary": "Filter the latest exported events by date",
                    "parameters": [
                        session_id,
                        {"name": "start", "in": "query", "required": True,
                         "schema": {"type": "string"}},
                        {"name": "end", "in": "query", "required": True,
                         "schema": {"type": "string"}},
                    ],
                    "responses": json_response,
                }
            },
            "/api/v1/sessions/{sessionId}/exports": {
                "get": {
                    "tags": ["Sessions"],
                    "summary": "List available calendar export files",
                    "parameters": [session_id],
                    "responses": json_response,
                }
            },
            "/api/v1/sessions/{sessionId}/exports/{filename}": {
                "get": {
                    "tags": ["Sessions"],
                    "summary": "Download an existing export",
                    "parameters": [
                        session_id,
                        {"name": "filename", "in": "path", "required": True,
                         "schema": {"type": "string", "enum": [
                             "calendar.json", "calendar.ics", "calendar.xlsx"
                         ]}},
                    ],
                    "responses": {
                        "200": {"description": "Calendar export file"},
                        "401": {"description": "Authentication required"},
                        "404": {"description": "Export not available"},
                    },
                }
            },
            "/api/v1/sessions/{sessionId}/sync": {
                "post": {
                    "tags": ["Sync"],
                    "summary": "Queue a session sync",
                    "description": "Queues a background sync and returns its run id; poll the run endpoint for the result. Requires the owner to have signed in to Phenikaa in the web app. Runs once at a time per session and at least 60 seconds apart.",
                    "parameters": [session_id],
                    "responses": {
                        "202": {"description": "Sync queued; data.runId and data.status are returned"},
                        "409": {"description": "login_required, session_disabled, or conflict_running (error.details.runId is the running sync)"},
                        "429": {"description": "The previous run finished less than 60 seconds ago; see the Retry-After header"},
                        "503": {"description": "Sync could not be queued"},
                    },
                }
            },
            "/api/v1/sessions/{sessionId}/sync/runs": {
                "get": {
                    "tags": ["Sync"],
                    "summary": "List recent sync runs",
                    "parameters": [session_id],
                    "responses": json_response,
                }
            },
            "/api/v1/sessions/{sessionId}/sync/runs/{runId}": {
                "get": {
                    "tags": ["Sync"],
                    "summary": "Get a sync run",
                    "parameters": [
                        session_id,
                        {"name": "runId", "in": "path", "required": True,
                         "schema": {"type": "integer"}},
                    ],
                    "responses": json_response,
                }
            },
        },
    }
