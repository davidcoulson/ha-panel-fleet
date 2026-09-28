import os
import tempfile

# main.py reads its data directory and options at import: point it at a
# scratch directory before any test imports it, and run as if by hand
# (no Supervisor, so the ingress-only gate is open to the test client).
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="panel-fleet-test-")
os.environ.pop("SUPERVISOR_TOKEN", None)
