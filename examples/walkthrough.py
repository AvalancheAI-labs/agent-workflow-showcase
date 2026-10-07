"""Reproducible in-process API walkthrough; no external sockets allowed."""
import json
import ipaddress
import os
from pathlib import Path
import socket
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fastapi.testclient import TestClient
from app import app


_connect = socket.socket.connect


def no_network(sock, address):
    # Windows asyncio creates an internal loopback socket pair.
    try:
        local = ipaddress.ip_address(address[0]).is_loopback
    except ValueError:
        local = address[0] == "localhost"
    if not local:
        raise AssertionError("External network connection attempted")
    return _connect(sock, address)


with tempfile.TemporaryDirectory() as directory:
    os.environ["BRAIN_ROOT"] = directory
    with patch.object(socket.socket, "connect", no_network), TestClient(app) as client:
        response = client.post("/api/demo/run")
        assert response.status_code == 200
        workflow = response.json()
        run_id = workflow["run_id"]
        result = json.loads(workflow["tasks"][0]["result"].split("\n", 1)[1])
        assert result["total_amount"] == 2500 and result["won_amount"] == 1700
        assert workflow["state"] == "awaiting_review"
        assert client.get(f"/api/runs/{run_id}/report").status_code == 409
        assert client.post(f"/api/runs/{run_id}/review", json={"approve": True}).json()["state"] == "approved"
        assert client.get(f"/api/runs/{run_id}/report").status_code == 200
        chain = client.get("/api/audit/verify").json()
        assert chain["ok"]
        print(json.dumps({"summary": result, "before_review": workflow["state"],
                          "after_review": "approved", "audit": chain, "external_network": "blocked"}, indent=2))
