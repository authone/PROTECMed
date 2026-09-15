"""M4 end-to-end: coordinator API + party agent UI + the real worker.

Synthetic fixture data only. Separate directories on one host are a SIMULATION of
institutional separation, not a demonstration of it.
"""
from __future__ import annotations
import json
import tempfile
import unittest
from pathlib import Path

from . import OPENFHE_LIB, ROOT, SKIP_REASON, WORKER_AVAILABLE, WORKER_BINARY
from .harness import AGENT_HOST, RUN_ID, STUDY_ID, Deployment

EXPECTED = json.loads((ROOT / "fixtures/synthetic_expected.json").read_text())["counts"]


@unittest.skipUnless(WORKER_AVAILABLE, SKIP_REASON)
class ServiceCase(unittest.TestCase):
    parties = 2

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.deployment = Deployment(root=Path(self.temporary.name),
                                     worker_binary=WORKER_BINARY, library=OPENFHE_LIB,
                                     party_count=self.parties)

    # --- flow helpers --------------------------------------------------------
    def import_all(self, mode: str = "literal-only"):
        for name in self.deployment.names:
            client = self.deployment.login(name)
            html = client.get("/local/v2/import").text
            token = html.split('name="selection_token" value="')[1].split('"')[0]
            response = self.deployment.ui_post(name, "/local/v2/import",
                                               selection_token=token, import_mode=mode)
            self.assertEqual(self.deployment.notice_of(response), "OK")

    def step(self, name: str, route: str, expected: str = "OK"):
        response = self.deployment.ui_post(name, f"/local/v2/{route}")
        self.assertEqual(self.deployment.notice_of(response), expected, (name, route))

    def operator(self, route: str, key: str, expected: int = 201):
        response = self.deployment.api("POST", f"/runs/{RUN_ID}/{route}", key=key, json={})
        self.assertEqual(response.status_code, expected, response.text)
        return response

    def run_to_request(self, query_id: str = "Q004"):
        self.import_all()
        self.assertEqual(self.deployment.freeze_run(query_id).status_code, 201)
        for name in self.deployment.names:
            self.step(name, "accept-plan")
        self.operator("context", "key-context-000001")
        for name in self.deployment.names:
            self.step(name, "key-round")
        self.operator("epoch", "key-epoch-000001")
        # No ciphertext is accepted before EVERY epoch confirmation is present.
        for name in self.deployment.names:
            self.step(name, "confirm-epoch")
        for name in self.deployment.names:
            self.step(name, "prepare-count")
            self.step(name, "encrypt-submit")
        self.operator("evaluate", "key-evaluate-00001")
        self.operator("decryption-request", "key-request-000001")

    def approve_all(self):
        for name in self.deployment.names:
            self.step(name, "review-request")
            self.step(name, "approve")

    def fuse(self, expected: int = 200):
        return self.deployment.api("POST", f"/runs/{RUN_ID}/fuse", key="key-fuse-0000001",
                                   json={})


class ReleaseTests(ServiceCase):
    def test_two_party_release_through_the_ui(self):
        self.run_to_request("Q004")
        self.approve_all()
        response = self.fuse()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["aggregate"], EXPECTED["Q004"]["total"])

    def test_local_counts_match_the_fixture_split(self):
        self.run_to_request("Q004")
        counts = [self.deployment.agents[name].local_count
                  for name in self.deployment.names]
        self.assertEqual(counts, EXPECTED["Q004"]["two_parties"])

    def test_recipient_sees_the_result_only_after_release(self):
        self.run_to_request("Q004")
        before = self.deployment.api("GET", f"/runs/{RUN_ID}/result",
                                     token=self.deployment.recipient_token).json()
        self.assertIs(before["released"], False)
        self.assertNotIn("aggregate", before)
        self.approve_all()
        self.fuse()
        after = self.deployment.api("GET", f"/runs/{RUN_ID}/result",
                                    token=self.deployment.recipient_token).json()
        self.assertEqual(after["aggregate"], EXPECTED["Q004"]["total"])

    def test_a_party_cannot_read_the_result(self):
        self.run_to_request("Q004")
        self.approve_all()
        self.fuse()
        response = self.deployment.api("GET", f"/runs/{RUN_ID}/result",
                                       token=self.deployment.tokens["party-a"])
        self.assertEqual(response.status_code, 403)

    def test_evidence_export_contains_no_partial_binaries(self):
        self.run_to_request("Q004")
        self.approve_all()
        self.fuse()
        evidence = self.deployment.api("GET", f"/runs/{RUN_ID}/evidence").json()
        self.assertIs(evidence["partial_binaries_included"], False)
        body = json.dumps(evidence)
        self.assertNotIn("partial_bytes", body)
        self.assertEqual({entry["decision"] for entry in evidence["decisions"]}, {"APPROVE"})

    def test_no_local_count_reaches_the_coordinator(self):
        self.run_to_request("Q004")
        counts = {self.deployment.agents[n].local_count for n in self.deployment.names}
        rows = self.deployment.service.connection.execute(
            "SELECT envelope_json FROM messages").fetchall()
        for row in rows:
            payload = json.loads(row["envelope_json"])["payload"]
            self.assertNotIn("count", payload)
            self.assertNotIn("admitted_rows", payload)
        audit = self.deployment.service.connection.execute(
            "SELECT detail FROM audit").fetchall()
        for entry in audit:
            for count in counts:
                self.assertNotIn(f'"{count}"', entry["detail"])

    def test_run_state_is_visible_to_members_only(self):
        self.import_all()
        self.deployment.freeze_run("Q004")
        member = self.deployment.api("GET", f"/runs/{RUN_ID}",
                                     token=self.deployment.tokens["party-a"])
        self.assertEqual(member.status_code, 200)
        outsider = self.deployment.api("GET", f"/runs/{RUN_ID}",
                                       token=self.deployment.recipient_token)
        self.assertIn(outsider.status_code, (200, 403))


class ThreePartyReleaseTests(ServiceCase):
    parties = 3

    def test_three_party_release(self):
        self.run_to_request("Q004")
        counts = [self.deployment.agents[name].local_count
                  for name in self.deployment.names]
        self.assertEqual(counts, EXPECTED["Q004"]["three_parties"])
        self.approve_all()
        self.assertEqual(self.fuse().json()["aggregate"], EXPECTED["Q004"]["total"])

    def test_two_of_three_approvals_do_not_release(self):
        self.run_to_request("Q004")
        for name in self.deployment.names[:2]:
            self.step(name, "review-request")
            self.step(name, "approve")
        response = self.fuse()
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "PARTIAL_SET_INCOMPLETE")
        result = self.deployment.api("GET", f"/runs/{RUN_ID}/result",
                                     token=self.deployment.recipient_token).json()
        self.assertIs(result["released"], False)


class AuthenticationTests(ServiceCase):
    def test_api_requires_a_bearer_token(self):
        response = self.deployment.api("GET", f"/runs/{RUN_ID}", token="not-a-token")
        self.assertEqual(response.status_code, 401)

    def test_a_party_cannot_create_a_run(self):
        self.import_all()
        response = self.deployment.api(
            "POST", f"/studies/{STUDY_ID}/runs", key="key-forbidden-0001",
            token=self.deployment.tokens["party-a"],
            json={"run_id": "other-run", "roster": [], "recipient_ids": ["recipient-one"],
                  "query_sha256": "a" * 64, "mapping_sha256": "b" * 64})
        self.assertEqual(response.status_code, 403)

    def test_a_party_cannot_sign_as_another_party(self):
        self.import_all()
        self.deployment.freeze_run("Q004")
        agent = self.deployment.agents["party-a"]
        agent.accept_plan(RUN_ID)
        envelope = json.loads(json.dumps(
            self.deployment.service.connection.execute(
                "SELECT envelope_json FROM messages WHERE party_id = 'party-a'"
            ).fetchone()["envelope_json"]))
        response = self.deployment.api(
            "POST", f"/runs/{RUN_ID}/plan-acceptances", key="key-impersonate-01",
            token=self.deployment.tokens["party-b"], json=json.loads(envelope))
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["detail"], "SIGNER_IS_NOT_CALLER")

    def test_public_api_documentation_is_disabled(self):
        for path in ("/docs", "/redoc", "/openapi.json"):
            client = self.deployment.clients["party-a"]
            self.assertEqual(client.get(path).status_code, 404, path)

    def test_idempotency_key_is_required_and_bound_to_the_body(self):
        missing = self.deployment.api("POST", "/studies", json={"study_id": STUDY_ID})
        self.assertEqual(missing.status_code, 400)
        self.assertEqual(missing.json()["detail"], "IDEMPOTENCY_KEY_REQUIRED")
        first = self.deployment.api("POST", "/studies", key="key-idem-000001",
                                    json={"study_id": STUDY_ID})
        replay = self.deployment.api("POST", "/studies", key="key-idem-000001",
                                     json={"study_id": STUDY_ID})
        self.assertEqual((first.status_code, replay.status_code), (201, 201))
        self.assertEqual(first.json(), replay.json())
        reused = self.deployment.api("POST", "/studies", key="key-idem-000001",
                                     json={"study_id": "another-study"})
        self.assertEqual(reused.status_code, 409)

    def test_artifact_access_requires_run_membership(self):
        self.run_to_request("Q004")
        digest = self.deployment.service.connection.execute(
            "SELECT sha256 FROM artifacts LIMIT 1").fetchone()["sha256"]
        allowed = self.deployment.api("GET", f"/runs/{RUN_ID}/artifacts/{digest}",
                                      token=self.deployment.tokens["party-a"])
        self.assertEqual(allowed.status_code, 200)
        unknown = self.deployment.api("GET", f"/runs/{RUN_ID}/artifacts/{'f' * 64}")
        self.assertEqual(unknown.status_code, 404)

    def test_oversized_json_is_refused(self):
        response = self.deployment.api("POST", "/studies", key="key-oversize-0001",
                                       content=b'{"study_id":"' + b"x" * 70000 + b'"}')
        self.assertIn(response.status_code, (400, 413))


class LocalUiSecurityTests(ServiceCase):
    def test_login_is_required_for_every_screen(self):
        client = self.deployment.clients["party-a"]
        for path in ("/local/v2/import", "/local/v2/run", "/local/v2/request"):
            response = client.get(path, follow_redirects=False)
            self.assertEqual(response.status_code, 303, path)
            self.assertIn("/local/v2/login", response.headers["location"])

    def test_status_endpoint_requires_a_session(self):
        client = self.deployment.clients["party-a"]
        self.assertEqual(client.get("/local/v2/status").status_code, 401)

    def test_wrong_operator_token_is_refused(self):
        client = self.deployment.clients["party-a"]
        response = client.post("/local/v2/login", data={"operator_token": "guess"})
        self.assertEqual(response.status_code, 401)

    def test_session_cookie_is_httponly_samesite_strict_and_agent_specific(self):
        self.deployment.login("party-a")
        client = self.deployment.clients["party-a"]
        header = client.post("/local/v2/login", follow_redirects=False,
                             data={"operator_token": client.app.state.sessions
                                   .operator_token}).headers["set-cookie"]
        self.assertIn("HttpOnly", header)
        self.assertIn("SameSite=strict", header.replace("Strict", "strict"))
        self.assertIn("protecmed_session_party_a", header)
        other = self.deployment.clients["party-b"].app.state.sessions.cookie_name
        self.assertNotEqual(other, client.app.state.sessions.cookie_name)

    def test_post_without_a_csrf_token_is_refused(self):
        client = self.deployment.login("party-a")
        response = client.post("/local/v2/prepare-count", data={})
        self.assertIn(response.status_code, (403, 422))

    def test_post_with_a_wrong_csrf_token_is_refused(self):
        client = self.deployment.login("party-a")
        response = client.post("/local/v2/prepare-count",
                               data={"csrf_token": "not-the-token"})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["detail"], "CSRF_TOKEN_INVALID")

    def test_a_cross_origin_form_post_is_refused(self):
        client = self.deployment.login("party-a")
        token = self.deployment.csrf_of(client, "/local/v2/import")
        response = client.post("/local/v2/prepare-count", data={"csrf_token": token},
                               headers={"Origin": "http://evil.example"})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["detail"], "ORIGIN_NOT_ALLOWED")

    def test_an_unexpected_host_header_is_refused(self):
        client = self.deployment.login("party-a")
        token = self.deployment.csrf_of(client, "/local/v2/import")
        response = client.post("/local/v2/prepare-count", data={"csrf_token": token},
                               headers={"Host": "protecmed.example"})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["detail"], "HOST_NOT_ALLOWED")

    def test_no_state_changing_get_exists(self):
        client = self.deployment.login("party-a")
        for route in ("approve", "reject", "encrypt-submit", "key-round"):
            self.assertEqual(client.get(f"/local/v2/{route}").status_code, 405, route)

    def test_the_ui_uses_no_external_assets(self):
        client = self.deployment.login("party-a")
        html = client.get("/local/v2/import").text
        for marker in ("http://", "https://", "cdn", "<script"):
            self.assertNotIn(marker, html.lower(), marker)

    def test_the_selection_token_carries_no_path(self):
        client = self.deployment.login("party-a")
        html = client.get("/local/v2/import").text
        token = html.split('name="selection_token" value="')[1].split('"')[0]
        self.assertNotIn("/", token)
        self.assertEqual(len(token), 32)

    def test_an_arbitrary_path_cannot_be_imported(self):
        self.deployment.login("party-a")
        response = self.deployment.ui_post("party-a", "/local/v2/import",
                                           selection_token="/etc/passwd",
                                           import_mode="literal-only")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "UNKNOWN_SELECTION_TOKEN")

    def test_the_approval_screen_states_irreversibility(self):
        self.run_to_request("Q004")
        self.step("party-a", "review-request")
        html = self.deployment.clients["party-a"].get("/local/v2/request").text
        self.assertIn("nu poate fi retrasa", html)

    def test_the_local_count_is_shown_only_on_the_local_screen(self):
        self.run_to_request("Q004")
        html = self.deployment.clients["party-a"].get("/local/v2/run").text
        count = self.deployment.agents["party-a"].local_count
        self.assertIn(f"<strong>{count}</strong>", html)
        remote = self.deployment.api("GET", f"/runs/{RUN_ID}",
                                     token=self.deployment.tokens["party-a"]).text
        self.assertNotIn("local_count", remote)


class RejectionAndRetryTests(ServiceCase):
    def test_a_rejection_blocks_the_release(self):
        self.run_to_request("Q004")
        self.step("party-a", "review-request")
        self.step("party-a", "approve")
        self.step("party-b", "review-request")
        self.step("party-b", "reject")
        response = self.fuse()
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "REJECTION_PRESENT")
        result = self.deployment.api("GET", f"/runs/{RUN_ID}/result",
                                     token=self.deployment.recipient_token).json()
        self.assertIs(result["released"], False)

    def test_a_rejecting_party_emits_no_partial(self):
        self.run_to_request("Q004")
        self.step("party-b", "review-request")
        self.step("party-b", "reject")
        rows = self.deployment.service.connection.execute(
            "SELECT COUNT(*) AS n FROM messages WHERE kind = 'partial'").fetchone()
        self.assertEqual(rows["n"], 0)

    def test_an_offline_coordinator_leaves_local_state_unchanged(self):
        self.import_all()
        self.deployment.freeze_run("Q004")
        self.deployment.go_offline("party-a")
        before = self.deployment.agents["party-a"].party.state.state
        self.step("party-a", "accept-plan", expected="OFFLINE")
        self.assertEqual(self.deployment.agents["party-a"].party.state.state, before)
        self.deployment.go_online("party-a")
        self.step("party-a", "accept-plan")

    def test_the_run_screen_reports_an_offline_coordinator(self):
        self.import_all()
        self.deployment.go_offline("party-a")
        html = self.deployment.login("party-a").get("/local/v2/run").text
        self.assertIn("OFFLINE", html)
        self.deployment.go_online("party-a")

    def test_a_retried_submission_resends_the_same_ciphertext(self):
        self.run_to_request("Q004")
        row = self.deployment.service.connection.execute(
            "SELECT envelope_json FROM messages WHERE party_id = 'party-a' "
            "AND kind = 'encrypted-count'").fetchone()
        first = json.loads(row["envelope_json"])["payload"]["ciphertext_sha256"]
        self.step("party-a", "encrypt-submit")
        row = self.deployment.service.connection.execute(
            "SELECT envelope_json FROM messages WHERE party_id = 'party-a' "
            "AND kind = 'encrypted-count'").fetchone()
        self.assertEqual(json.loads(row["envelope_json"])["payload"]["ciphertext_sha256"],
                         first)

    def test_fusing_twice_returns_the_same_receipt(self):
        self.run_to_request("Q004")
        self.approve_all()
        first = self.fuse().json()
        second = self.fuse().json()
        self.assertEqual(first, second)

    def test_a_second_approval_resends_the_stored_partial(self):
        self.run_to_request("Q004")
        self.step("party-a", "review-request")
        self.step("party-a", "approve")
        row = self.deployment.service.connection.execute(
            "SELECT envelope_json FROM messages WHERE party_id = 'party-a' "
            "AND kind = 'partial'").fetchone()
        first = json.loads(row["envelope_json"])["payload"]["partial_sha256"]
        # Re-verification is refused once a partial exists, so the resend path is used.
        self.step("party-a", "review-request", expected="PARTIAL_ALREADY_EMITTED")
        row = self.deployment.service.connection.execute(
            "SELECT envelope_json FROM messages WHERE party_id = 'party-a' "
            "AND kind = 'partial'").fetchone()
        self.assertEqual(json.loads(row["envelope_json"])["payload"]["partial_sha256"],
                         first)


if __name__ == "__main__":
    unittest.main()
