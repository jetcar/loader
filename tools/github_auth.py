"""
GitHub OAuth login tool.

Registers this script as a GitHub OAuth App and saves the resulting token
to a .env file for reuse by the analyzer.

Setup (one-time):
  1. Go to https://github.com/settings/developers → "OAuth Apps" → "New OAuth App"
  2. Fill in:
       Application name:     Jokker Analyzer
       Homepage URL:         http://localhost
       Authorization callback URL: http://localhost:8742/callback
  3. Click "Register application"
  4. Copy "Client ID" and generate a "Client secret"
  5. Run this script:
       python tools/github_auth.py --client-id <ID> --client-secret <SECRET>

The token is saved to .env as GITHUB_MODELS_TOKEN=<token>.
Subsequent runs of analyzer.py will load it automatically.
"""

import argparse
import http.server
import os
import secrets
import sys
import threading
import urllib.parse
import webbrowser
from pathlib import Path

import requests

GITHUB_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
CALLBACK_PORT = 8742
CALLBACK_PATH = "/callback"
REQUIRED_SCOPE = "models:read"
ENV_FILE = Path(__file__).resolve().parents[1] / ".env"


def _find_existing_env_value(key: str) -> str | None:
    """Return the current value of key in .env, if present."""
    if not ENV_FILE.exists():
        return None
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        if line.startswith(f"{key}="):
            return line[len(key) + 1:].strip()
    return None


def _write_env_token(token: str) -> None:
    """Write or replace GH_MODELS_TOKEN in .env."""
    key = "GH_MODELS_TOKEN"
    new_line = f"{key}={token}\n"

    if ENV_FILE.exists():
        lines = ENV_FILE.read_text(encoding="utf-8").splitlines(keepends=True)
        replaced = False
        for i, line in enumerate(lines):
            if line.startswith(f"{key}="):
                lines[i] = new_line
                replaced = True
                break
        if not replaced:
            lines.append(new_line)
        ENV_FILE.write_text("".join(lines), encoding="utf-8")
    else:
        ENV_FILE.write_text(new_line, encoding="utf-8")

    print(f"Token saved to {ENV_FILE}")


def _exchange_code_for_token(code: str, client_id: str, client_secret: str) -> str:
    """Exchange OAuth authorization code for an access token."""
    resp = requests.post(
        GITHUB_TOKEN_URL,
        headers={"Accept": "application/json"},
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "redirect_uri": f"http://localhost:{CALLBACK_PORT}{CALLBACK_PATH}",
        },
        timeout=15,
    )
    resp.raise_for_status()
    payload = resp.json()

    if "error" in payload:
        raise RuntimeError(f"GitHub token exchange failed: {payload['error_description']}")

    token = payload.get("access_token", "")
    if not token:
        raise RuntimeError(f"No access_token in response: {payload}")
    return token


class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    """Minimal HTTP handler that captures the OAuth callback."""

    result: dict = {}  # shared across the single request

    def do_GET(self):  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != CALLBACK_PATH:
            self._respond(404, "Not found")
            return

        params = urllib.parse.parse_qs(parsed.query)
        if "error" in params:
            error = params["error"][0]
            desc = params.get("error_description", [error])[0]
            self._respond(400, f"Authorization denied: {desc}")
            _CallbackHandler.result["error"] = desc
        elif "code" in params:
            _CallbackHandler.result["code"] = params["code"][0]
            self._respond(200, "Authorization successful! You can close this tab.")
        else:
            self._respond(400, "Missing code parameter")
            _CallbackHandler.result["error"] = "missing code"

    def _respond(self, status: int, message: str) -> None:
        body = message.encode()
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # suppress default access log
        pass


def run_oauth_flow(client_id: str, client_secret: str) -> str:
    """
    Run the OAuth authorization code flow.
    Opens the browser, waits for the callback, exchanges the code, returns token.
    """
    state = secrets.token_urlsafe(16)

    auth_url = (
        f"{GITHUB_AUTHORIZE_URL}"
        f"?client_id={urllib.parse.quote(client_id)}"
        f"&redirect_uri={urllib.parse.quote(f'http://localhost:{CALLBACK_PORT}{CALLBACK_PATH}')}"
        f"&scope={urllib.parse.quote(REQUIRED_SCOPE)}"
        f"&state={state}"
    )

    # Start callback server in a background thread; handle exactly one request
    server = http.server.HTTPServer(("localhost", CALLBACK_PORT), _CallbackHandler)
    server.timeout = 120  # seconds to wait for the browser callback
    thread = threading.Thread(target=server.handle_request, daemon=True)
    thread.start()

    print(f"\nOpening browser for GitHub authorization...")
    print(f"If the browser does not open, navigate to:\n  {auth_url}\n")
    webbrowser.open(auth_url)

    thread.join(timeout=125)
    server.server_close()

    if "error" in _CallbackHandler.result:
        raise RuntimeError(_CallbackHandler.result["error"])
    if "code" not in _CallbackHandler.result:
        raise RuntimeError("Timed out waiting for GitHub OAuth callback.")

    code = _CallbackHandler.result["code"]
    print("Authorization code received. Exchanging for token...")
    return _exchange_code_for_token(code, client_id, client_secret)


def _load_env() -> None:
    """Load .env from repo root if python-dotenv is available."""
    try:
        from dotenv import load_dotenv  # type: ignore
        load_dotenv(dotenv_path=ENV_FILE)
    except ImportError:
        pass


def main() -> None:
    _load_env()

    parser = argparse.ArgumentParser(
        description="GitHub OAuth login — saves GITHUB_MODELS_TOKEN to .env"
    )
    parser.add_argument(
        "--client-id",
        default=os.environ.get("GITHUB_CLIENT_ID", ""),
        help="GitHub OAuth App client ID (or set GITHUB_CLIENT_ID in .env)",
    )
    parser.add_argument(
        "--client-secret",
        default=os.environ.get("GITHUB_CLIENT_SECRET", ""),
        help="GitHub OAuth App client secret (or set GITHUB_CLIENT_SECRET in .env)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-authenticate even if a token is already stored",
    )
    args = parser.parse_args()

    if not args.client_id or not args.client_secret:
        parser.error(
            "Provide --client-id / --client-secret or set "
            "GITHUB_CLIENT_ID / GITHUB_CLIENT_SECRET in .env"
        )

    existing = _find_existing_env_value("GH_MODELS_TOKEN")
    if existing and not args.force:
        print(f"Token already stored in {ENV_FILE}.")
        print("Use --force to re-authenticate.")
        sys.exit(0)

    token = run_oauth_flow(args.client_id, args.client_secret)
    _write_env_token(token)
    print("Done. Run the analyzer now:\n  python analyzer/analyzer.py")


if __name__ == "__main__":
    main()
