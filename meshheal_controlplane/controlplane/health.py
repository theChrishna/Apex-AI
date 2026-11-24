"""Liveness and metrics for the controller process, with no extra dependencies.

  GET /healthz   200 while the control loop keeps finishing iterations, 503 if it has stalled
  GET /metrics   Prometheus text format: loop counts, decisions by type, active reroutes, paused, shadow/acting mode
"""
import http.server
import threading
import time


def _label(v):
    return str(v).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


class Health:
    def __init__(self, ctrl, interval_s, clock=time.time, grace_s=60.0):
        self.ctrl, self.interval_s, self.clock, self.grace_s = ctrl, interval_s, clock, grace_s
        self.started = clock()
        self.loops = 0
        self.loop_errors = 0
        self.last_loop = None

    def loop_done(self, ok=True):
        self.loops += 1
        self.loop_errors += 0 if ok else 1
        self.last_loop = self.clock()

    def healthy(self):
        """Alive if a loop finished recently; a freshly started process gets a grace period for its first one."""
        if self.last_loop is None:
            return self.clock() - self.started < self.grace_s
        return self.clock() - self.last_loop < 3 * self.interval_s + 5

    def metrics_text(self):
        st = self.ctrl.status()
        lines = [
            "# HELP meshheal_loops_total Control loop iterations finished.",
            "# TYPE meshheal_loops_total counter", f"meshheal_loops_total {self.loops}",
            "# HELP meshheal_loop_errors_total Iterations that raised an unexpected error.",
            "# TYPE meshheal_loop_errors_total counter", f"meshheal_loop_errors_total {self.loop_errors}",
            "# HELP meshheal_last_loop_timestamp_seconds Unix time the last iteration finished.",
            "# TYPE meshheal_last_loop_timestamp_seconds gauge",
            f"meshheal_last_loop_timestamp_seconds {self.last_loop or 0}",
            "# HELP meshheal_active_reroutes Reroutes currently in place.",
            "# TYPE meshheal_active_reroutes gauge", f"meshheal_active_reroutes {st['active_reroutes']}",
            "# HELP meshheal_paused 1 when the control ConfigMap has frozen all writes.",
            "# TYPE meshheal_paused gauge", f"meshheal_paused {int(st['paused'])}",
            "# HELP meshheal_shadow_mode 1 when the controller only reads and never writes.",
            "# TYPE meshheal_shadow_mode gauge", f"meshheal_shadow_mode {int(st['dry_run'])}",
            "# HELP meshheal_events_total Audit-log events by type.",
            "# TYPE meshheal_events_total counter",
        ]
        for event, n in sorted(self.ctrl.audit.counts.items()):
            lines.append(f'meshheal_events_total{{event="{_label(event)}"}} {n}')
        return "\n".join(lines) + "\n"


def start_server(health, port, host="0.0.0.0"):
    """Serve /healthz and /metrics in a daemon thread. port 0 picks a free port (see server.server_address)."""
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/healthz":
                ok = health.healthy()
                body, code = (b"ok\n", 200) if ok else (b"control loop stalled\n", 503)
            elif self.path == "/metrics":
                body, code = health.metrics_text().encode("utf-8"), 200
            else:
                body, code = b"not found\n", 404
            self.send_response(code)
            self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):      # keep probe requests out of the logs
            pass

    server = http.server.ThreadingHTTPServer((host, port), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread
