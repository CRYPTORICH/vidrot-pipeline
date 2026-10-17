"""Instagram connect state machine. The client is fake; nothing talks to Instagram."""
import tempfile
import unittest
from pathlib import Path

from vidrot.instagram import (
    approve_challenge,
    connect_account,
    connection,
    disconnect_account,
    session_saved,
    submit_code,
)


class BadPassword(Exception):
    pass


class TwoFactorRequired(Exception):
    pass


class ChallengeRequired(Exception):
    pass


class FakeClient:
    def __init__(self, gate):
        self.gate = gate
        self.settings = {}
        self.proxy = ""

    def set_proxy(self, proxy):
        self.proxy = proxy

    def set_settings(self, settings):
        self.settings = settings

    def get_settings(self):
        return {"uuids": {"phone_id": "abc"}, "cookies": {"sessionid": "saved"}}

    def login(self, username, password, verification_code=""):
        self.gate.calls.append((username, password, verification_code, self.settings))
        if password == "wrong-password":
            raise BadPassword("nope")
        if self.gate.mode == "2fa" and not verification_code:
            raise TwoFactorRequired("need the code")
        if self.gate.mode == "challenge" and not self.gate.approved:
            self.gate.approved = True
            raise ChallengeRequired("approve this login")
        return True


class Gate:
    def __init__(self, mode):
        self.mode = mode
        self.approved = False
        self.calls = []

    def __call__(self):
        return FakeClient(self)


def settings(password="instagram-password"):
    return {"ig_username": "vidrot.ai", "ig_password": password, "ig_proxy": ""}


class ConnectStateTests(unittest.TestCase):
    def test_success_saves_an_encrypted_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            gate = Gate("ok")
            result = connect_account(settings(), Path(tmp), client_factory=gate)
            self.assertTrue(result["ok"])
            self.assertEqual(result["state"], "connected")
            self.assertEqual(result["username"], "vidrot.ai")
            self.assertTrue(session_saved(tmp))
            self.assertEqual(connection(settings(), tmp)["state"], "connected")
            self.assertEqual(gate.calls[0][0], "vidrot.ai")
            gone = disconnect_account(tmp)
            self.assertEqual(gone["state"], "disconnected")
            self.assertFalse(session_saved(tmp))
            self.assertEqual(connection(settings(), tmp)["state"], "disconnected")

    def test_bad_password_does_not_save_a_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            gate = Gate("ok")
            result = connect_account(settings("wrong-password"), Path(tmp), client_factory=gate)
            self.assertFalse(result["ok"])
            self.assertEqual(result["state"], "error")
            self.assertIn("password", result["error"].lower())
            self.assertFalse(session_saved(tmp))
            self.assertEqual(connection(settings("wrong-password"), tmp)["state"], "disconnected")

    def test_two_factor_then_code_connects(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            gate = Gate("2fa")
            started = connect_account(settings(), folder, client_factory=gate)
            self.assertFalse(started["ok"])
            self.assertEqual(started["state"], "needs_code")
            self.assertTrue(started["needs_code"])
            self.assertFalse(started["challenge"])
            self.assertFalse(session_saved(folder))
            self.assertEqual(connection(settings(), folder)["state"], "needs_code")
            empty = submit_code(settings(), folder, "", client_factory=gate)
            self.assertFalse(empty["ok"])
            self.assertEqual(connection(settings(), folder)["state"], "needs_code")
            done = submit_code(settings(), folder, "123456", client_factory=gate)
            self.assertTrue(done["ok"], done)
            self.assertEqual(done["state"], "connected")
            self.assertTrue(session_saved(folder))
            self.assertEqual(gate.calls[-1][2], "123456")
            self.assertIn("phone_id", gate.calls[-1][3].get("uuids", {}))

    def test_challenge_then_approval_connects(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            gate = Gate("challenge")
            started = connect_account(settings(), folder, client_factory=gate)
            self.assertEqual(started["state"], "needs_approval")
            self.assertTrue(started["challenge"])
            self.assertIn("approve", started["error"].lower())
            self.assertFalse(session_saved(folder))
            done = approve_challenge(settings(), folder, client_factory=gate)
            self.assertTrue(done["ok"], done)
            self.assertEqual(done["state"], "connected")
            self.assertTrue(session_saved(folder))
            self.assertEqual(connection(settings(), folder)["state"], "connected")
