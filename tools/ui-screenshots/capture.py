"""Capture screenshots of the three local provider screens (M4 evidence tool).

Starts the D1 synthetic demo, drives party-a through a real Chromium with Playwright and
party-b plus the coordinator operator with ordinary HTTP calls, and writes one PNG per
screen. Invented fixture data only; never point this at a clinical workbook.

Requires Playwright and a Chromium binary. It drives the shipped UI through real forms,
real session cookies and real CSRF tokens; nothing is stubbed for the camera.
"""
from __future__ import annotations
import argparse
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import requests
from playwright.sync_api import Page, sync_playwright

ROOT = Path(__file__).resolve().parents[2]
COORDINATOR = "http://127.0.0.1:8080/api/v2"
PORTS = {"party-a": 8081, "party-b": 8082}
VIEWPORT = {"width": 1180, "height": 900}


def start_demo(state: Path, interpreter: str) -> tuple[subprocess.Popen, dict[str, str]]:
    # The launcher needs the interpreter that has the service dependencies, which is not
    # necessarily the one running Playwright.
    process = subprocess.Popen(
        [interpreter, str(ROOT / "deployment/synthetic_demo.py"), "--parties", "2",
         "--state", str(state)],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, cwd=str(ROOT))
    banner, tokens = [], {}
    deadline = time.time() + 90
    while time.time() < deadline:
        line = process.stdout.readline()
        if not line:
            break
        banner.append(line.rstrip())
        match = re.match(r"(party-\w|operator)\s+token\s+(\S+)", line.strip())
        if match:
            tokens[match.group(1)] = match.group(2)
        if "operator token" in line:
            tokens["operator"] = line.split()[-1]
        if "Ctrl-C to stop" in line:
            break
    if "operator" not in tokens or "party-a" not in tokens or "party-b" not in tokens:
        process.kill()
        raise SystemExit("demo did not start:\n" + "\n".join(banner))
    return process, tokens


class Driver:
    """party-b and the coordinator operator, over plain HTTP."""

    def __init__(self, tokens: dict[str, str]) -> None:
        self.tokens = tokens
        self.session = requests.Session()
        self.base = f"http://127.0.0.1:{PORTS['party-b']}"
        self.session.post(f"{self.base}/local/v2/login",
                          data={"operator_token": tokens["party-b"]})

    def csrf(self, path: str) -> str:
        html = self.session.get(self.base + path).text
        return re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)

    def ui(self, route: str, **data) -> str:
        path = "/local/v2/import" if route == "import" else "/local/v2/run"
        response = self.session.post(f"{self.base}/local/v2/{route}",
                                     data={"csrf_token": self.csrf(path), **data},
                                     allow_redirects=False)
        return response.headers.get("location", str(response.status_code))

    def api(self, method: str, path: str, key: str | None = None, **kwargs):
        headers = {"Authorization": f"Bearer {self.tokens['operator']}"}
        if key:
            headers["Idempotency-Key"] = key
        return requests.request(method, COORDINATOR + path, headers=headers, **kwargs)

    def status(self) -> dict:
        return self.session.get(f"{self.base}/local/v2/status").json()


def shoot(page: Page, output: Path, name: str) -> None:
    page.wait_for_load_state("networkidle")
    page.screenshot(path=str(output / f"{name}.png"), full_page=True)
    print(f"  captured {name}.png")


def click(page: Page, label: str) -> None:
    page.get_by_role("button", name=label).click()
    page.wait_for_load_state("networkidle")


def main() -> int:
    parser = argparse.ArgumentParser(description="Capture UI screenshots. Synthetic only.")
    parser.add_argument("--out", type=Path, default=ROOT / "evidence/m4/screenshots")
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--chromium", default="/usr/bin/chromium")
    parser.add_argument("--demo-python", default="python3",
                        help="interpreter that has the service dependencies installed")
    arguments = parser.parse_args()

    if arguments.state.exists():
        shutil.rmtree(arguments.state)
    arguments.out.mkdir(parents=True, exist_ok=True)

    process, tokens = start_demo(arguments.state, arguments.demo_python)
    try:
        driver = Driver(tokens)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                executable_path=arguments.chromium,
                args=["--no-sandbox", "--disable-dev-shm-usage"])
            page = browser.new_page(viewport=VIEWPORT)
            base = f"http://127.0.0.1:{PORTS['party-a']}"

            page.goto(f"{base}/local/v2/login")
            shoot(page, arguments.out, "01-login")
            page.fill("input[name=operator_token]", tokens["party-a"])
            click(page, "Intra")
            shoot(page, arguments.out, "02-import-before")

            page.check("input[name=selection_token]")
            click(page, "Importa si valideaza")
            shoot(page, arguments.out, "03-import-validated")

            # party-b imports; the operator freezes the run over the same live API.
            driver.ui("import",
                      selection_token=re.search(
                          r'name="selection_token" value="([^"]+)"',
                          driver.session.get(driver.base + "/local/v2/import").text
                      ).group(1), import_mode="literal-only")
            snapshots = {"party-a": requests.get(
                f"{base}/local/v2/status",
                cookies={c["name"]: c["value"] for c in page.context.cookies()}
            ).json()["import"]["snapshot_token"],
                "party-b": driver.status()["import"]["snapshot_token"]}
            fingerprints = _fingerprints(arguments.state)
            roster = [{"party_id": name,
                       "identity_key_sha256": fingerprints[name],
                       "snapshot_token": snapshots[name]}
                      for name in ("party-a", "party-b")]
            driver.api("POST", "/studies", key="key-shot-study-01",
                       json={"study_id": "synthetic-study"})
            created = driver.api("POST", "/studies/synthetic-study/runs",
                                 key="key-shot-run-0001",
                                 json={"run_id": "synthetic-run", "roster": roster,
                                       "recipient_ids": ["recipient-one"],
                                       "query_sha256": _query_hash(),
                                       "mapping_sha256": _mapping_hash()})
            if created.status_code != 201:
                raise SystemExit(f"run creation failed: {created.text}")

            page.goto(f"{base}/local/v2/run")
            shoot(page, arguments.out, "04-run-before-plan")
            click(page, "Accepta planul rularii")
            driver.ui("accept-plan")
            driver.api("POST", "/runs/synthetic-run/context", key="key-shot-ctx-0001",
                       json={})

            page.goto(f"{base}/local/v2/run")
            click(page, "Genereaza partea locala de cheie")
            driver.ui("key-round")
            driver.api("POST", "/runs/synthetic-run/epoch", key="key-shot-epoch-01",
                       json={})
            driver.ui("confirm-epoch")

            page.goto(f"{base}/local/v2/run")
            click(page, "Confirma epoca")
            click(page, "Calculeaza numarul local")
            shoot(page, arguments.out, "05-run-local-count")
            click(page, "Cripteaza si transmite")

            driver.ui("prepare-count")
            driver.ui("encrypt-submit")
            driver.api("POST", "/runs/synthetic-run/evaluate", key="key-shot-eval-001",
                       json={})
            driver.api("POST", "/runs/synthetic-run/decryption-request",
                       key="key-shot-req-0001", json={})

            page.goto(f"{base}/local/v2/request")
            shoot(page, arguments.out, "06-request-before-review")
            click(page, "Verifica cererea")
            shoot(page, arguments.out, "07-request-verified")

            click(page, "Aproba si emite partea de decriptare")
            shoot(page, arguments.out, "08-approved")
            # Exactly one of the two partials exists at this point.
            blocked = driver.api("POST", "/runs/synthetic-run/fuse",
                                 key="key-shot-fuse-early", json={})

            driver.ui("review-request")
            driver.ui("approve")
            released = driver.api("POST", "/runs/synthetic-run/fuse",
                                  key="key-shot-fuse-final", json={})
            (arguments.out / "release.txt").write_text(
                f"fuse with one approval : {blocked.status_code} {blocked.text}\n"
                f"fuse with both         : {released.status_code} {released.text}\n",
                encoding="ascii")
            print("  fuse with one approval:", blocked.status_code, blocked.json())
            print("  fuse with both       :", released.status_code, released.json())
            browser.close()
    finally:
        process.terminate()
        process.wait(timeout=15)
    print(f"screenshots written to {arguments.out}")
    return 0


def _fingerprints(state: Path) -> dict[str, str]:
    """Read each agent's enrolled public-key fingerprint from the coordinator."""
    import sqlite3
    from hashlib import sha256
    connection = sqlite3.connect(state / "coordinator.db")
    rows = connection.execute(
        "SELECT agent_id, public_key_hex FROM agents "
        "WHERE public_key_hex IS NOT NULL").fetchall()
    connection.close()
    return {agent: sha256(bytes.fromhex(key)).hexdigest() for agent, key in rows}


def _query_hash() -> str:
    import json
    sys.path.insert(0, str(ROOT / "services/common"))
    from protecmed_protocol.canonical import payload_hash
    catalogue = json.loads((ROOT / "config/query-catalog.json").read_text())["queries"]
    return payload_hash(next(q for q in catalogue if q["query_id"] == "Q004"))


def _mapping_hash() -> str:
    from hashlib import sha256
    return sha256((ROOT / "config/iocn-mapping.json").read_bytes()).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
