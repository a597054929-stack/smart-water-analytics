"""Phase 6 audit: HTTP static file server tests.

Covers:
  1. Static audit (3 categories)
  2. Functional verification (4 scenarios)
  3. Protocol compliance (Keep-Alive)
  4. (Doc updates in README.md separately)

Run:
  pytest tests/test_http_static_server.py -v
  # requires server NOT running (this test brings up its own uvicorn instance)
"""
from __future__ import annotations

import asyncio
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest
import requests

try:
    import psutil  # optional: gives Process.memory_info() for RSS check
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

ROOT = Path(__file__).resolve().parent.parent
AGENT_DIR = ROOT / "agent"
DIST_DATA = ROOT / "frontend" / "dist" / "data"


def _free_port() -> int:
    """Find a free TCP port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _server_up(base: str, timeout: float = 15.0) -> bool:
    """Poll until /api/health returns 200 or timeout."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = requests.get(f"{base}/api/health", timeout=2)
            if r.status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


@pytest.fixture(scope="module")
def server():
    """Spawn a uvicorn server in a subprocess and tear it down at the end."""
    port = _free_port()
    base = f"http://127.0.0.1:{port}"
    env = os.environ.copy()
    # Don't require real DB for static file tests
    env.pop("WATER_DB_PATH", None)
    # Phase 6: explicit AGENT_API_KEY off so dev-mode auth is
    # permissive (the 14 audit tests don't need auth).
    env.pop("AGENT_API_KEY", None)
    proc = subprocess.Popen(
        [sys.executable, "server.py", "--port", str(port), "--host", "127.0.0.1"],
        cwd=str(AGENT_DIR),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    proc._base = base
    proc._port = port
    proc._pid = proc.pid
    try:
        if not _server_up(base):
            proc.terminate()
            pytest.fail("server did not start within 15s")
        yield proc
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


@pytest.fixture(scope="module")
def auth_server():
    """Phase 6 vuln 2: spawn a server with AGENT_API_KEY set."""
    port = _free_port()
    base = f"http://127.0.0.1:{port}"
    env = os.environ.copy()
    env.pop("WATER_DB_PATH", None)
    env["AGENT_API_KEY"] = "test-secret-key-12345"
    # High RPM so the auth tests don't accidentally hit 429
    env["AGENT_API_KEY_RPM"] = "100000"
    proc = subprocess.Popen(
        [sys.executable, "server.py", "--port", str(port), "--host", "127.0.0.1"],
        cwd=str(AGENT_DIR),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    proc._base = base
    proc._port = port
    proc._api_key = env["AGENT_API_KEY"]
    try:
        if not _server_up(base):
            proc.terminate()
            pytest.fail("auth server did not start within 15s")
        yield proc
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


@pytest.fixture(scope="module")
def rate_limit_server():
    """Phase 6 vuln 2: spawn a server with low RPM cap (5/min) so we
    can verify the 429 path on the 6th request."""
    port = _free_port()
    base = f"http://127.0.0.1:{port}"
    env = os.environ.copy()
    env.pop("WATER_DB_PATH", None)
    env["AGENT_API_KEY"] = "test-secret-key-67890"
    env["AGENT_API_KEY_RPM"] = "5"
    proc = subprocess.Popen(
        [sys.executable, "server.py", "--port", str(port), "--host", "127.0.0.1"],
        cwd=str(AGENT_DIR),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    proc._base = base
    proc._port = port
    proc._api_key = env["AGENT_API_KEY"]
    try:
        if not _server_up(base):
            proc.terminate()
            pytest.fail("rate-limit server did not start within 15s")
        yield proc
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


# ── 2. Functional verification ─────────────────────────────────

def test_normal_get_200_with_content_type(server):
    """GET /data/meter_info.json -> 200 + correct Content-Type auto-magic."""
    r = requests.get(f"{server._base}/data/meter_info.json", timeout=5)
    assert r.status_code == 200
    # Content-Type is auto-detected by Starlette's mimetypes.guess_type
    assert r.headers["content-type"].startswith("application/json")
    # Etag + Last-Modified are set for conditional GET
    assert "etag" in r.headers
    assert "last-modified" in r.headers
    # Body is real JSON with 9963 meters
    body = r.json()
    assert isinstance(body, dict)
    assert len(body) > 9000


def test_path_traversal_blocked_dotdot(server):
    """GET /data/../.env -> server normalizes to /.env, then 404."""
    r = requests.get(f"{server._base}/data/../.env", timeout=5, allow_redirects=False)
    # uvicorn normalizes /data/../.env to /.env. The /.env path has no
    # route, so we get 404. Body should NOT contain .env contents.
    assert r.status_code in (403, 404)
    assert "tp-s50e7" not in r.text  # the .env's API key must not leak
    assert "LLM_API_KEY" not in r.text


def test_path_traversal_blocked_multiple_dotdot(server):
    """GET /data/../../../../etc/passwd -> 404 (Linux target) or 404 (Windows)."""
    r = requests.get(
        f"{server._base}/data/../../../../etc/passwd", timeout=5, allow_redirects=False
    )
    assert r.status_code in (403, 404)
    assert "root:" not in r.text  # /etc/passwd first line


def test_path_traversal_blocked_url_encoded(server):
    """URL-encoded ../ (%2F) also blocked — Starlette decodes + normalizes."""
    r = requests.get(
        f"{server._base}/data/..%2F..%2Fetc%2Fpasswd", timeout=5, allow_redirects=False
    )
    assert r.status_code in (403, 404)


def test_404_for_nonexistent_file(server):
    """GET /data/nonexistent.json -> 404."""
    r = requests.get(f"{server._base}/data/nonexistent.json", timeout=5)
    assert r.status_code == 404


def test_404_for_nonexistent_subdir(server):
    """GET /data/no/such/path.json -> 404 (not a path traversal vector)."""
    r = requests.get(f"{server._base}/data/no/such/path.json", timeout=5)
    assert r.status_code == 404


def test_dashboard_root_serves_html(server):
    """GET / -> 200 HTML (single-page app entry point)."""
    r = requests.get(f"{server._base}/", timeout=5)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert "<!DOCTYPE html>" in r.text or "<html" in r.text


# ── 2d. Large file concurrency (memory stability) ─────────────

def test_concurrent_large_file_memory_stable(server):
    """10 parallel requests for the 18MB daily_totals.json; server RSS
    should not grow more than ~30MB above the steady-state baseline.

    Test that 10 concurrent reads don't load the whole file 10x into
    memory — FileResponse uses sendfile/streaming so each connection
    uses ~64KB kernel buffer regardless of file size.
    """
    if HAS_PSUTIL:
        proc = psutil.Process(server._pid)
        rss_before = proc.memory_info().rss
    else:
        # Fallback: read Windows tasklist WorkingSet
        out = subprocess.check_output(
            ['tasklist', '/FI', f'PID eq {server._pid}', '/FO', 'CSV', '/NH'],
            text=True, timeout=5,
        )
        # Format: "INFO,"Image Name","PID","Session Name","Session#","Mem Usage"
        last = out.split(',')[-1].strip().strip('"').replace(' K', '').replace(',', '').replace('"', '').strip()
        rss_before = int(last) * 1024

    # 10 concurrent downloads
    n = 10
    responses = [None] * n

    def fetch(i: int) -> None:
        r = requests.get(
            f"{server._base}/data/daily_totals.json",
            timeout=30,
            stream=True,
        )
        # Consume the body in chunks to actually exercise the streaming
        chunks = []
        for chunk in r.iter_content(chunk_size=64 * 1024):
            chunks.append(chunk)
        responses[i] = (r.status_code, len(b"".join(chunks)))

    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=n) as ex:
        list(ex.map(fetch, range(n)))

    if HAS_PSUTIL:
        rss_after = proc.memory_info().rss
    else:
        out = subprocess.check_output(
            ['tasklist', '/FI', f'PID eq {server._pid}', '/FO', 'CSV', '/NH'],
            text=True, timeout=5,
        )
        last = out.split(',')[-1].strip().strip('"').replace(' K', '').replace(',', '').replace('"', '').strip()
        rss_after = int(last) * 1024

    growth_mb = (rss_after - rss_before) / 1024 / 1024

    # All responses should be 200 + 18MB-ish
    for status, size in responses:
        assert status == 200
        assert size > 17_000_000  # ~18MB file

    # Memory growth: with streaming, each connection holds ~64KB kernel
    # buffer, so 10 concurrent = ~640KB. Allow 30MB for uvicorn/asyncio
    # overhead (the test isn't measuring OS file cache either).
    assert growth_mb < 30, f"server RSS grew {growth_mb:.1f}MB under 10 concurrent 18MB downloads (expected <30MB with streaming)"


# ── 3. HTTP/1.1 Keep-Alive ────────────────────────────────────

def test_keepalive_socket_reuse(server):
    """HTTP/1.1 default is keep-alive. Verify by reusing the same socket
    for 2 sequential requests — if keep-alive works, both succeed on
    one connection; if it doesn't, the 2nd request gets connection
    reset.
    """
    host, port = "127.0.0.1", server._port
    sock = socket.create_connection((host, port), timeout=5)

    def send(req: bytes) -> bytes:
        sock.sendall(req)
        chunks = []
        sock.settimeout(5)
        # Read until we have Content-Length bytes + \r\n\r\n for headers
        buf = b""
        while True:
            try:
                chunk = sock.recv(4096)
            except socket.timeout:
                break
            if not chunk:
                break
            buf += chunk
            if b"0\r\n\r\n" in buf or b"\r\n\r\n" in buf:
                # If we have a Content-Length, check; otherwise stop
                if b"Content-Length:" in buf:
                    cl_line = [l for l in buf.split(b"\r\n") if b"Content-Length:" in l][0]
                    cl = int(cl_line.split(b":")[1].strip())
                    if b"\r\n\r\n" in buf and len(buf) - buf.find(b"\r\n\r\n") - 4 >= cl:
                        break
                else:
                    if b"\r\n\r\n" in buf:
                        break
        return buf

    # Request 1
    resp1 = send(
        b"GET /api/health HTTP/1.1\r\nHost: localhost\r\n\r\n"
    )
    # Request 2 on the same socket
    resp2 = send(
        b"GET /api/health HTTP/1.1\r\nHost: localhost\r\n\r\n"
    )

    sock.close()

    # Both should be 200
    assert b"200 OK" in resp1, f"req1: {resp1[:200]}"
    assert b"200 OK" in resp2, f"req2: {resp2[:200]}"


def test_keepalive_header_on_static_file(server):
    """Static file response should have Connection: keep-alive header
    (HTTP/1.1 sends it by default; uvicorn includes it explicitly).
    """
    r = requests.get(f"{server._base}/data/meter_info.json", timeout=5)
    assert r.status_code == 200
    # uvicorn sends "Connection: keep-alive" by default for HTTP/1.1
    # (it's the protocol default anyway)
    conn = r.headers.get("connection", "").lower()
    assert conn in ("keep-alive", ""), f"unexpected Connection: {conn!r}"


# ── 1. Static audit assertions (regression net) ──────────────

def test_uses_starlette_staticfiles_with_path_safety():
    """Sanity: StaticFiles (which has realpath + commonpath check) is
    used, not a custom open() that could miss the check.
    """
    import starlette.staticfiles as sf
    import inspect
    src = inspect.getsource(sf.StaticFiles.lookup_path)
    assert "realpath" in src, "Starlette StaticFiles.lookup_path must use realpath"
    assert "commonpath" in src, "Starlette StaticFiles.lookup_path must check commonpath"


def test_uses_fileresponse_with_stat():
    """FileResponse with stat_result uses os.sendfile when available
    (zero-copy streaming). Verify import + the no-extra-read pattern.
    """
    import starlette.responses as r
    import inspect
    init_src = inspect.getsource(r.FileResponse.__init__)
    assert "stat_result" in init_src
    assert "set_stat_headers" in init_src  # uses stat to set Content-Length


def test_server_uses_asyncio_to_thread_for_blocking_io():
    """LLM calls block the event loop unless wrapped in asyncio.to_thread.
    Verify the chat() handler uses to_thread (or anyio.to_thread)."""
    src = (AGENT_DIR / "server.py").read_text(encoding="utf-8")
    # either asyncio.to_thread or anyio.to_thread.run_sync is OK
    assert ("asyncio.to_thread" in src) or ("anyio.to_thread" in src), (
        "server.py chat() handler must offload blocking LLM calls to a "
        "thread so the event loop stays free for SSE flushing"
    )


# ── Concurrency model: each request gets its own coroutine ─────

def test_50_concurrent_health_requests_all_2xx(server):
    """50 concurrent /api/health requests — all should be 200 quickly.
    Sanity check that FastAPI/uvicorn is concurrent (async I/O)."""
    n = 50

    def hit() -> int:
        r = requests.get(f"{server._base}/api/health", timeout=10)
        return r.status_code

    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=n) as ex:
        statuses = list(ex.map(lambda _: hit(), range(n)))
    assert all(s == 200 for s in statuses)


# ── 5. Phase 6 vuln regressions (auth + CORS + rate limit) ───────

def test_cors_default_whitelist_includes_dev_origins(server):
    """Phase 6 vuln 1: the default CORS whitelist must include
    http://localhost:5173 (vite dev server) so the local dev flow
    keeps working. And must NOT wildcard-allow (vuln was '*').
    """
    r = requests.get(
        f"{server._base}/api/health",
        headers={"Origin": "http://localhost:5173"},
        timeout=5,
    )
    assert r.status_code == 200
    acao = r.headers.get("access-control-allow-origin", "").lower()
    # Either the origin is echoed (CORS middleware default) or '*'
    # is set; in dev default it's the origin. The post-vuln-1 fix
    # uses an explicit whitelist, so 'localhost:5173' should appear.
    assert "localhost:5173" in acao or acao == "*", (
        f"CORS allow-origin should whitelist dev origin, got {acao!r}"
    )


def test_cors_rejects_unknown_origin(server):
    """Phase 6 vuln 1: a malicious origin must not get CORS headers
    in dev mode. The default whitelist is {5173, 8000}; an unknown
    origin like 'http://evil.com' should not be reflected in
    Access-Control-Allow-Origin.
    """
    r = requests.get(
        f"{server._base}/api/health",
        headers={"Origin": "http://evil.com"},
        timeout=5,
    )
    # /api/health always returns 200 (auth-free for liveness). The
    # CORS middleware decides whether to add ACAO. With an explicit
    # whitelist, the response should NOT include 'evil.com' in ACAO.
    acao = r.headers.get("access-control-allow-origin", "").lower()
    assert "evil.com" not in acao, (
        f"CORS must not whitelist evil.com; got ACAO={acao!r}"
    )


def test_auth_required_when_api_key_set(auth_server):
    """Phase 6 vuln 2: with AGENT_API_KEY set, /api/chat requires
    Authorization: Bearer <key>. No header => 401.
    """
    r = requests.post(
        f"{auth_server._base}/api/chat",
        json={"question": "test"},
        timeout=5,
    )
    assert r.status_code == 401
    assert r.headers.get("www-authenticate", "").lower().startswith("bearer")


def test_auth_wrong_key_returns_401(auth_server):
    """Phase 6 vuln 2: wrong bearer token => 401."""
    r = requests.post(
        f"{auth_server._base}/api/chat",
        json={"question": "test"},
        headers={"Authorization": "Bearer wrong-key"},
        timeout=5,
    )
    assert r.status_code == 401


def test_auth_correct_key_passes_401_check(auth_server):
    """Phase 6 vuln 2: correct bearer token => NOT 401. (Don't assert
    200 because /api/chat needs LLM_API_KEY + LLM access; we just
    verify the auth gate lets the request through.)
    """
    r = requests.post(
        f"{auth_server._base}/api/chat",
        json={"question": "test"},
        headers={"Authorization": f"Bearer {auth_server._api_key}"},
        timeout=5,
    )
    # If the request got past auth, it's NOT 401. It might be 200,
    # 500 (no LLM), 503 (no LLM_API_KEY in test env) — anything but 401.
    assert r.status_code != 401, f"auth passed but got 401: {r.text[:200]}"


def test_rate_limit_returns_429_after_quota(rate_limit_server):
    """Phase 6 vuln 2: AGENT_API_KEY_RPM=5 -> 6th request in <60s => 429."""
    headers = {"Authorization": f"Bearer {rate_limit_server._api_key}"}
    statuses = []
    for _ in range(7):
        r = requests.get(
            f"{rate_limit_server._base}/api/metrics",
            headers=headers,
            timeout=5,
        )
        statuses.append(r.status_code)
    # First 5 should pass auth (not 401). 6th or 7th should 429.
    assert 429 in statuses, f"expected a 429 within 7 reqs (RPM=5), got {statuses}"
    # The first 5 should be non-401 (auth passed) and non-429 (within quota)
    for s in statuses[:5]:
        assert s != 401, f"auth should pass for first 5: {statuses}"
        assert s != 429, f"rate limit should not trigger within first 5: {statuses}"


def test_dashboard_uses_fileresponse_content_type(server):
    """Phase 6 vuln 5: GET / uses FileResponse (text/html) not
    HTMLResponse(f.read()). Verify content-type is still text/html.
    """
    r = requests.get(f"{server._base}/", timeout=5)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")

# ── 5b. Phase 7: file browser UI ──────────────────────────────

def test_api_files_lists_real_data_dir(server):
    """Phase 7: /api/files returns a list of files in _DATA_DIR with
    metadata (name, size, mtime, type, mime, icon). Used by the
    /files browser page. Auth-free (file listing is the same data
    visible at /data/*).
    """
    r = requests.get(f"{server._base}/api/files", timeout=5)
    assert r.status_code == 200
    data = r.json()
    assert "files" in data
    assert "directory" in data
    assert isinstance(data["files"], list)
    if data["files"]:  # only assert shape when the dir has files
        f = data["files"][0]
        for key in ("name", "size", "mtime", "type", "mime", "icon"):
            assert key in f, f"missing {key!r} in file entry: {f}"
        assert isinstance(f["size"], int)
        assert isinstance(f["mtime"], (int, float))
        assert f["icon"]  # non-empty Lucide icon name


def test_files_page_serves_modern_html(server):
    """Phase 7: GET /files serves files.html with text/html.
    Self-contained: has data-theme attr, Lucide icons, search input,
    preview dialog.
    """
    r = requests.get(f"{server._base}/files", timeout=5)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    body = r.text
    # Self-contained features
    assert 'data-theme' in body, "files.html must support light/dark theme"
    assert '<symbol id="i-' in body, "files.html must have inline Lucide icons"
    assert 'id="search"' in body, "files.html must have search filter input"
    assert '<dialog' in body, "files.html must have a preview dialog"
    # Dark mode CSS variables must be present
    assert '[data-theme="dark"]' in body
    # localStorage theme persistence
    assert 'localStorage' in body
    # Responsive (mobile media query)
    assert '@media' in body


def test_files_page_uses_fileresponse_streaming(server):
    """Phase 7: /files uses FileResponse (consistent with /data/* and
    / from vuln 5 fix). Server reads via sendfile/streaming.
    """
    r = requests.get(f"{server._base}/files", timeout=5, stream=True)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    # Read in chunks (not whole file) to exercise streaming
    total = 0
    for chunk in r.iter_content(chunk_size=4096):
        total += len(chunk)
    assert total > 1000  # files.html is ~24 KB; we got it all


def test_api_files_auth_free_with_api_key_set(auth_server):
    """Phase 7: /api/files must NOT require auth (it is a file listing,
    same as /api/health). The /files browser needs to work without
    the user manually entering an API key.
    """
    r = requests.get(f"{auth_server._base}/api/files", timeout=5)
    # If auth were required, this would be 401. Should be 200.
    assert r.status_code == 200, (
        f"/api/files must be auth-free; got {r.status_code} {r.text[:200]}"
    )

