"""MeshHeal fleet dashboard backend (Phase 6): a small, stdlib-only, authenticated API that stores what each cluster's
agent pushes (snapshots and controller decisions) in SQLite and serves it for any mesh, for any number of clusters.

  python -m dashboard.tokens add-read                 # prints a read token once; only its hash is stored
  python -m dashboard.tokens add-ingest <cluster>     # an ingest token bound to one cluster name
  python -m dashboard.server --db fleet.db --tokens tokens.json --port 8780 [--baseline cluster=baseline.yaml ...]
  python -m dashboard.agent --url http://host:8780 --cluster <name> --token-file t --snapshots s.jsonl --audit a.jsonl
"""
