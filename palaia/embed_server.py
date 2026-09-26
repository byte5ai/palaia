"""Embedding server — long-lived process for fast semantic search.

Loads the embedding model once and serves queries over stdin/stdout or Unix socket.
Eliminates the ~3-23s model loading penalty on every CLI invocation.

Usage:
    palaia embed-server              # stdio mode (OpenClaw plugin)
    palaia embed-server --socket     # Unix socket mode (CLI, MCP)
    palaia embed-server --socket --daemon  # detached background process

Protocol: One JSON object per line (newline-delimited JSON-RPC).
Requests:
    {"method": "query", "params": {"text": "...", "top_k": 10, ...}}
    {"method": "embed", "params": {"texts": ["...", "..."]}}
    {"method": "warmup"}
    {"method": "ping"}
    {"method": "status"}
    {"method": "shutdown"}
"""

from __future__ import annotations

import json
import logging
import os
import selectors
import signal
import socket
import sys
import threading
import time
import traceback
from pathlib import Path

from palaia.config import get_root
from palaia.embeddings import BM25Provider
from palaia.search import SearchEngine
from palaia.store import Store

logger = logging.getLogger(__name__)

# Defaults
DEFAULT_IDLE_TIMEOUT = 1800  # 30 minutes
PID_FILENAME = "embed-server.pid"
SOCKET_FILENAME = "embed.sock"


def get_socket_path(palaia_root: Path) -> Path:
    """Return the Unix socket path for a given .palaia root."""
    return palaia_root / SOCKET_FILENAME


def get_pid_path(palaia_root: Path) -> Path:
    """Return the PID file path for a given .palaia root."""
    return palaia_root / PID_FILENAME


def _count_entries(store: Store) -> int:
    """Count total entries across hot+warm tiers (fast, no parsing)."""
    count = 0
    for tier in ("hot", "warm"):
        tier_dir = store.root / tier
        if tier_dir.exists():
            count += sum(1 for _ in tier_dir.glob("*.md"))
    return count


_TIERS = ("hot", "warm", "cold")


def _entry_files(store: Store, tier: str) -> frozenset[str]:
    """Names of the entry files in one tier (listing only, no parsing)."""
    tier_dir = store.root / tier
    if not tier_dir.exists():
        return frozenset()
    return frozenset(p.name for p in tier_dir.glob("*.md"))


def _warmup_missing(store: Store, engine: SearchEngine) -> dict:
    """Index any entries missing from the embedding cache. Returns stats."""
    provider = engine.provider
    if isinstance(provider, BM25Provider):
        return {"indexed": 0, "new": 0, "cached": 0}

    entries = store.all_entries_unfiltered(include_cold=False)
    total = len(entries)
    if total == 0:
        return {"indexed": 0, "new": 0, "cached": 0}

    uncached = []
    cached_count = 0
    for meta, body, _tier in entries:
        entry_id = meta.get("id", "")
        if not entry_id:
            continue
        if store.embedding_cache.get_cached(entry_id) is not None:
            cached_count += 1
        else:
            title = meta.get("title", "")
            tags = " ".join(meta.get("tags", []))
            full_text = f"{title} {tags} {body}"
            uncached.append((entry_id, full_text))

    if not uncached:
        return {"indexed": total, "new": 0, "cached": cached_count}

    model_name = getattr(provider, "model_name", None) or getattr(provider, "model", "unknown")
    new_count = 0
    batch_size = 32

    for i in range(0, len(uncached), batch_size):
        batch = uncached[i : i + batch_size]
        texts = [text for _, text in batch]
        ids = [eid for eid, _ in batch]
        try:
            vectors = provider.embed(texts)
            for eid, vec in zip(ids, vectors):
                store.embedding_cache.set_cached(eid, vec, model=model_name)
                new_count += 1
        except Exception as e:
            logger.warning("Batch embedding failed at offset %d: %s", i, e)
            break

    return {"indexed": cached_count + new_count, "new": new_count, "cached": cached_count}


class EmbedServer:
    """JSON-RPC server for embedding queries. Supports stdio and Unix socket transport."""

    def __init__(self, root: Path, idle_timeout: float = 0):
        self.root = root
        self.store = Store(root)
        self.engine = SearchEngine(self.store)
        # BM25-only fallback engine for queries during warmup (no GIL contention)
        self._bm25_engine = SearchEngine(self.store)
        self._bm25_engine._provider = BM25Provider()
        # Entry files per tier as last seen — see _refresh_if_store_changed()
        self._tier_files = {tier: _entry_files(self.store, tier) for tier in _TIERS}
        self._running = True
        self._warming_up = False
        self._idle_timeout = idle_timeout  # 0 = no timeout
        self._last_activity = time.monotonic()

    def _touch_activity(self) -> None:
        """Update last activity timestamp."""
        self._last_activity = time.monotonic()

    def _refresh_if_store_changed(self, include_cold: bool = False) -> None:
        """Drop the search index and embedding cache if the store changed.

        Other processes (the CLI) add, remove and move entries. Checking before
        each request that reads the store makes a new entry visible at once —
        memory_write's duplicate guard in the OpenClaw plugin depends on it.
        The change signal is the set of entry files per tier: directory mtimes
        would not do, because every search rewrites the access metadata of its
        hits via temp file and rename. The cold archive is listed only when the
        request reads it. On a change the index is rebuilt and the embedding
        cache reloaded from disk (so a later save does not overwrite vectors
        another process added); the loaded embedding model is kept.
        """
        changed = False
        for tier in _TIERS if include_cold else ("hot", "warm"):
            files = _entry_files(self.store, tier)
            if files != self._tier_files[tier]:
                self._tier_files[tier] = files
                changed = True
        if changed:
            self.engine.invalidate_index()
            self._bm25_engine.invalidate_index()
            self.store.embedding_cache.reload()

    def _start_idle_monitor(self) -> None:
        """Start background thread that shuts down after idle timeout."""
        if self._idle_timeout <= 0:
            return

        def _idle_loop():
            while self._running:
                time.sleep(min(30, self._idle_timeout / 2))
                if not self._running:
                    break
                elapsed = time.monotonic() - self._last_activity
                if elapsed >= self._idle_timeout:
                    logger.info("Idle timeout (%.0fs), shutting down.", elapsed)
                    self._running = False
                    break

        t = threading.Thread(target=_idle_loop, daemon=True)
        t.start()

    def handle_request(self, request: dict) -> dict:
        """Dispatch a single JSON-RPC request. Always returns a dict."""
        self._touch_activity()
        method = request.get("method", "")

        if method == "ping":
            return {"result": "pong"}

        if method == "shutdown":
            self._running = False
            return {"result": "shutting_down"}

        if method == "status":
            return self._handle_status()

        if method == "warmup":
            return self._handle_warmup()

        if method == "query":
            return self._handle_query(request.get("params", {}))

        if method == "embed":
            return self._handle_embed(request.get("params", {}))

        return {"error": f"Unknown method: {method}"}

    def _handle_status(self) -> dict:
        """Return entry count, cache coverage, and provider info."""
        self._refresh_if_store_changed()
        entries = _count_entries(self.store)
        cache_stats = self.store.embedding_cache.stats()
        provider = self.engine.provider
        provider_name = getattr(provider, "name", "unknown")
        model = getattr(provider, "model_name", None) or getattr(provider, "model", None) or ""
        return {
            "result": {
                "entries": entries,
                "cached": cache_stats.get("cached_entries", 0),
                "provider": provider_name,
                "model": model,
                "has_embeddings": self.engine.has_embeddings,
                "warming_up": self._warming_up,
            }
        }

    def _handle_warmup(self) -> dict:
        """Index all missing entries."""
        self._refresh_if_store_changed()
        stats = _warmup_missing(self.store, self.engine)
        return {"result": stats}

    def _handle_query(self, params: dict) -> dict:
        """Execute a search query using the existing SearchEngine."""
        text = params.get("text", "")
        if not text:
            return {"error": "Missing 'text' parameter"}

        top_k = params.get("top_k", 10)
        agent = params.get("agent")
        project = params.get("project")
        scope_visibility = params.get("scope_visibility")  # Issue #145: agent isolation
        entry_type = params.get("type")
        status = params.get("status")
        priority = params.get("priority")
        assignee = params.get("assignee")
        instance = params.get("instance")
        include_cold = params.get("include_cold", False)
        cross_project = params.get("cross_project", False)
        before = params.get("before")
        after = params.get("after")

        self._refresh_if_store_changed(include_cold=include_cold)
        engine = self._bm25_engine if self._warming_up else self.engine
        results = engine.search(
            text,
            top_k=top_k,
            include_cold=include_cold,
            project=project,
            agent=agent,
            entry_type=entry_type,
            status=status,
            priority=priority,
            assignee=assignee,
            instance=instance,
            before=before,
            after=after,
            cross_project=cross_project,
            scope_visibility=scope_visibility,
        )

        return {"result": {"results": results}}

    def _handle_embed(self, params: dict) -> dict:
        """Compute raw embeddings for a list of texts."""
        texts = params.get("texts", [])
        if not texts:
            return {"error": "Missing 'texts' parameter"}
        if not isinstance(texts, list):
            return {"error": "'texts' must be a list of strings"}

        provider = self.engine.provider
        if isinstance(provider, BM25Provider):
            return {"error": "No semantic embedding provider available (BM25-only)"}

        try:
            vectors = provider.embed(texts)
            provider_name = getattr(provider, "name", "unknown")
            model = getattr(provider, "model_name", None) or getattr(provider, "model", None) or ""
            return {
                "result": {
                    "vectors": [v if isinstance(v, list) else list(v) for v in vectors],
                    "provider": provider_name,
                    "model": model,
                }
            }
        except Exception as e:
            return {"error": f"Embedding failed: {e}"}

    # ── stdio transport ─────────────────────────────────────────

    def run_stdio(self) -> None:
        """Main loop: read JSON lines from stdin, write JSON responses to stdout."""
        self._start_idle_monitor()

        # Signal ready IMMEDIATELY — warmup runs in background
        self._warming_up = True
        self._write_stdout({"result": "ready"})

        # Background warmup thread
        def _bg_warmup():
            try:
                _warmup_missing(self.store, self.engine)
            except Exception as e:
                logger.warning("Background warmup failed: %s", e)
            finally:
                self._warming_up = False

        warmup_thread = threading.Thread(target=_bg_warmup, daemon=True)
        warmup_thread.start()

        while self._running:
            try:
                line = sys.stdin.readline()
                if not line:
                    break
                line = line.strip()
                if not line:
                    continue

                try:
                    request = json.loads(line)
                except json.JSONDecodeError as e:
                    self._write_stdout({"error": f"Invalid JSON: {e}"})
                    continue

                response = self.handle_request(request)
                self._write_stdout(response)

            except Exception as e:
                try:
                    self._write_stdout({"error": f"Internal error: {e}", "traceback": traceback.format_exc()})
                except Exception:
                    break

    def _write_stdout(self, response: dict) -> None:
        """Write a JSON response line to stdout."""
        sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
        sys.stdout.flush()

    # Keep backward compat alias
    run = run_stdio

    # ── Unix socket transport ───────────────────────────────────

    def run_socket(self, socket_path: Path | None = None) -> None:
        """Serve over a Unix domain socket. Multiple clients can connect."""
        sock_path = socket_path or get_socket_path(self.root)
        pid_path = get_pid_path(self.root)

        # Clean up stale socket
        _cleanup_stale_socket(sock_path, pid_path)

        # Create socket
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            sock.bind(str(sock_path))
        except OSError as e:
            raise RuntimeError(f"Cannot bind to {sock_path}: {e}") from e
        sock.listen(8)
        sock.setblocking(False)

        # Write PID file
        _write_pid_file(pid_path)

        # Start background services
        self._start_idle_monitor()

        # Background warmup
        self._warming_up = True

        def _bg_warmup():
            try:
                _warmup_missing(self.store, self.engine)
            except Exception as e:
                logger.warning("Background warmup failed: %s", e)
            finally:
                self._warming_up = False

        warmup_thread = threading.Thread(target=_bg_warmup, daemon=True)
        warmup_thread.start()

        logger.info("Embed server listening on %s (pid %d)", sock_path, os.getpid())

        sel = selectors.DefaultSelector()
        sel.register(sock, selectors.EVENT_READ)

        # Per-connection read buffers
        buffers: dict[int, bytearray] = {}

        try:
            while self._running:
                events = sel.select(timeout=1.0)
                for key, mask in events:
                    if key.fileobj is sock:
                        # New connection
                        conn, _ = sock.accept()
                        conn.setblocking(False)
                        sel.register(conn, selectors.EVENT_READ)
                        buffers[conn.fileno()] = bytearray()
                    else:
                        conn = key.fileobj
                        self._handle_socket_data(conn, sel, buffers)
        except Exception as e:
            logger.error("Socket server error: %s", e)
        finally:
            sel.close()
            sock.close()
            _remove_file(sock_path)
            _remove_file(pid_path)
            logger.info("Embed server stopped.")

    def _handle_socket_data(self, conn, sel, buffers: dict) -> None:
        """Read data from a socket connection, process complete lines."""
        fd = conn.fileno()
        try:
            data = conn.recv(65536)
        except (ConnectionError, OSError):
            self._close_connection(conn, sel, buffers)
            return

        if not data:
            self._close_connection(conn, sel, buffers)
            return

        buf = buffers.get(fd, bytearray())
        buf.extend(data)

        # Process complete lines (newline-delimited JSON)
        while b"\n" in buf:
            line, _, buf = buf.partition(b"\n")
            buffers[fd] = buf
            line_str = line.decode("utf-8", errors="replace").strip()
            if not line_str:
                continue
            try:
                request = json.loads(line_str)
            except json.JSONDecodeError as e:
                self._send_to_conn(conn, {"error": f"Invalid JSON: {e}"})
                continue

            response = self.handle_request(request)
            self._send_to_conn(conn, response)

            if not self._running:
                return

        buffers[fd] = buf

    def _send_to_conn(self, conn, response: dict) -> None:
        """Send a JSON response to a socket connection."""
        try:
            msg = json.dumps(response, ensure_ascii=False) + "\n"
            conn.sendall(msg.encode("utf-8"))
        except (ConnectionError, OSError):
            pass

    def _close_connection(self, conn, sel, buffers: dict) -> None:
        """Clean up a closed connection."""
        fd = conn.fileno()
        try:
            sel.unregister(conn)
        except (KeyError, ValueError):
            pass
        buffers.pop(fd, None)
        try:
            conn.close()
        except OSError:
            pass


# ── PID / socket lifecycle helpers ──────────────────────────────

def _write_pid_file(pid_path: Path) -> None:
    """Write current PID to file."""
    pid_path.write_text(str(os.getpid()))


def _read_pid_file(pid_path: Path) -> int | None:
    """Read PID from file, return None if missing or invalid."""
    try:
        return int(pid_path.read_text().strip())
    except (FileNotFoundError, ValueError):
        return None


def _is_pid_alive(pid: int) -> bool:
    """Check if a process with the given PID is running."""
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def _remove_file(path: Path) -> None:
    """Remove a file, ignoring errors."""
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def _cleanup_stale_socket(sock_path: Path, pid_path: Path) -> None:
    """Remove socket and PID file if the owning process is dead."""
    if not sock_path.exists():
        return
    pid = _read_pid_file(pid_path)
    if pid is not None and _is_pid_alive(pid):
        raise RuntimeError(
            f"Embed server already running (pid {pid}). "
            f"Stop it with: palaia embed-server --stop"
        )
    # Stale — clean up
    _remove_file(sock_path)
    _remove_file(pid_path)


def is_server_running(palaia_root: Path) -> bool:
    """Check if an embed-server is running for the given .palaia root."""
    pid_path = get_pid_path(palaia_root)
    sock_path = get_socket_path(palaia_root)
    if not sock_path.exists():
        return False
    pid = _read_pid_file(pid_path)
    if pid is None:
        return False
    return _is_pid_alive(pid)


def stop_server(palaia_root: Path) -> bool:
    """Send SIGTERM to the running embed-server. Returns True if stopped."""
    pid_path = get_pid_path(palaia_root)
    pid = _read_pid_file(pid_path)
    if pid is None or not _is_pid_alive(pid):
        # Clean up stale files
        _remove_file(get_socket_path(palaia_root))
        _remove_file(pid_path)
        return False
    try:
        os.kill(pid, signal.SIGTERM)
        # Wait briefly for shutdown
        for _ in range(20):
            time.sleep(0.1)
            if not _is_pid_alive(pid):
                return True
        # Force kill
        os.kill(pid, signal.SIGKILL)
        return True
    except (OSError, ProcessLookupError):
        return False
    finally:
        _remove_file(get_socket_path(palaia_root))
        _remove_file(pid_path)


def start_daemon(palaia_root: Path, idle_timeout: float = DEFAULT_IDLE_TIMEOUT) -> int:
    """Start embed-server as a detached daemon. Returns the child PID."""
    import subprocess

    sock_path = get_socket_path(palaia_root)
    pid_path = get_pid_path(palaia_root)
    lock_path = palaia_root / "embed-server.startup.lock"

    # Already running?
    if is_server_running(palaia_root):
        pid = _read_pid_file(pid_path)
        return pid or 0

    # Atomic lock to prevent concurrent startup race condition.
    # Two CLI processes calling start_daemon simultaneously would both
    # pass is_server_running() and both spawn daemons.
    try:
        fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.close(fd)
    except FileExistsError:
        # Another process is starting the daemon — wait for it
        for _ in range(100):
            time.sleep(0.1)
            if is_server_running(palaia_root):
                pid = _read_pid_file(pid_path)
                return pid or 0
        return 0  # Give up

    try:
        # Clean stale files
        _remove_file(sock_path)
        _remove_file(pid_path)

        # Spawn detached subprocess
        cmd = [
            sys.executable, "-m", "palaia", "embed-server",
            "--socket",
            "--idle-timeout", str(int(idle_timeout)),
        ]
        env = {**os.environ, "PALAIA_HOME": str(palaia_root)}

        proc = subprocess.Popen(
            cmd,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )

        # Wait for socket to appear (up to 10s for model loading)
        for _ in range(100):
            time.sleep(0.1)
            if sock_path.exists():
                return proc.pid

        # Check if process died
        if proc.poll() is not None:
            raise RuntimeError(f"Embed server exited with code {proc.returncode}")

        return proc.pid
    finally:
        _remove_file(lock_path)


# ── Entry point ─────────────────────────────────────────────────

def main(
    transport: str = "stdio",
    root: Path | None = None,
    idle_timeout: float = 0,
    stop: bool = False,
    status: bool = False,
) -> None:
    """Entry point for `palaia embed-server`."""
    palaia_root = root or get_root()

    if stop:
        if stop_server(palaia_root):
            print("Embed server stopped.")
        else:
            print("No embed server running.")
        return

    if status:
        if is_server_running(palaia_root):
            pid = _read_pid_file(get_pid_path(palaia_root))
            print(f"Embed server running (pid {pid})")
        else:
            print("No embed server running.")
        return

    server = EmbedServer(palaia_root, idle_timeout=idle_timeout)

    # Handle SIGTERM for clean shutdown
    def _handle_sigterm(signum, frame):
        server._running = False

    signal.signal(signal.SIGTERM, _handle_sigterm)

    if transport == "socket":
        server.run_socket()
    else:
        server.run_stdio()


if __name__ == "__main__":
    main()
