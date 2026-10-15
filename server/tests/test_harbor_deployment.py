"""Deployment contracts which do not require a Docker daemon or cluster."""
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_kubernetes_keeps_browser_and_state_private():
    yaml = pytest.importorskip("yaml")
    objects = list(yaml.safe_load_all((ROOT / "deploy" / "kubernetes.yaml").read_text()))
    deployment = next(o for o in objects if o["kind"] == "Deployment")
    assert deployment["spec"]["replicas"] == 1
    assert deployment["spec"]["strategy"]["type"] == "Recreate"
    pod = deployment["spec"]["template"]["spec"]
    assert pod["nodeSelector"]["kubernetes.io/arch"] == "amd64"
    assert not pod["automountServiceAccountToken"]
    assert pod["securityContext"]["seccompProfile"]["type"] == "Localhost"
    container = pod["containers"][0]
    assert container["securityContext"]["runAsNonRoot"]
    assert container["securityContext"]["readOnlyRootFilesystem"]
    assert container["securityContext"]["capabilities"]["drop"] == ["ALL"]
    assert [port["containerPort"] for port in container["ports"]] == [8765]
    assert {"/profiles", "/config", "/data", "/browser", "/paperless"} <= {m["mountPath"] for m in container["volumeMounts"]}
    service = next(o for o in objects if o["kind"] == "Service")
    assert service["spec"]["type"] == "ClusterIP"
    assert not any(o["kind"] == "Ingress" for o in objects)


def test_compose_trial_publishes_only_private_dashboard_and_preserves_sandbox():
    yaml = pytest.importorskip("yaml")
    config = yaml.safe_load((ROOT / "deploy" / "compose.yaml").read_text())
    service = config["services"]["collector"]
    assert service["ports"] == ["127.0.0.1:8765:8765"]
    assert service["security_opt"] == ["seccomp=../server/seccomp-chrome.json"]
    assert "privileged" not in service
    assert service["environment"]["TZ"] == "America/New_York"
