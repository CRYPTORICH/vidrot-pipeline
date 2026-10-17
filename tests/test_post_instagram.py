import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import post_instagram


class MediaTests(unittest.TestCase):
    def test_media_object_becomes_a_reel_url(self):
        class Media:
            code = "AbC123"
            pk = 99

        posted = post_instagram.media_permalink(Media())
        self.assertEqual(posted["url"], "https://www.instagram.com/reel/AbC123/")
        self.assertEqual(posted["pk"], "99")

    def test_dict_result_still_works(self):
        posted = post_instagram.media_permalink({"code": "XYZ", "pk": "5"})
        self.assertEqual(posted["code"], "XYZ")

    def test_empty_result(self):
        self.assertIsNone(post_instagram.media_permalink(None))


class CaptionTests(unittest.TestCase):
    def test_prefers_filename_stem(self):
        captions = {
            "000_FISH_AND_CHIPS_4": "from the filename",
            "FISH_AND_CHIPS_4": "from the channel",
        }
        text = post_instagram.resolve_caption("output/000_FISH_AND_CHIPS_4.mp4", captions)
        self.assertEqual(text, "from the filename")

    def test_falls_back_to_channel_key(self):
        captions = {"FISH_AND_CHIPS_4": "from the channel"}
        text = post_instagram.resolve_caption("000_FISH_AND_CHIPS_4.mp4", captions)
        self.assertEqual(text, "from the channel")


class AuthTests(unittest.TestCase):
    def test_check_reports_missing_auth_without_network(self):
        env = {
            "IG_PASSWORD": "",
            "IG_SESSION_FILE": "",
            "IG_SESSION_JSON": "",
            "IG_SESSIONID": "",
            "IG_VERIFICATION_CODE": "",
        }
        with mock.patch.dict(os.environ, env, clear=False):
            with mock.patch.object(post_instagram, "session_candidates", return_value=[]):
                info = post_instagram.describe_auth()
                self.assertFalse(post_instagram.auth_configured(info))
                code = post_instagram.print_auth_report()
        self.assertEqual(code, 0)

    def test_login_stops_before_any_client_call_when_unconfigured(self):
        client = mock.Mock()
        env = {
            "IG_PASSWORD": "",
            "IG_SESSION_FILE": "",
            "IG_SESSION_JSON": "",
            "IG_SESSIONID": "",
        }
        with mock.patch.dict(os.environ, env, clear=False):
            with mock.patch.object(post_instagram, "session_candidates", return_value=[]):
                self.assertFalse(post_instagram.login(client))
        client.login.assert_not_called()
        client.login_by_sessionid.assert_not_called()
        client.set_settings.assert_not_called()

    def test_challenge_is_explained(self):
        class ChallengeRequired(Exception):
            pass

        client = mock.Mock()
        client.login.side_effect = ChallengeRequired("checkpoint")
        with mock.patch.dict(os.environ, {"IG_PASSWORD": "secret", "IG_SESSION_JSON": ""}, clear=False):
            with mock.patch.object(post_instagram, "session_candidates", return_value=[]):
                self.assertFalse(post_instagram.login(client))

    def test_two_factor_is_explained(self):
        class TwoFactorRequired(Exception):
            pass

        client = mock.Mock()
        client.login.side_effect = TwoFactorRequired("need code")
        with mock.patch.dict(os.environ, {"IG_PASSWORD": "secret"}, clear=False):
            with mock.patch.object(post_instagram, "apply_saved_session", return_value=None):
                self.assertFalse(post_instagram.login(client))

    def test_password_login_keeps_a_loaded_session(self):
        client = mock.Mock()
        session = json.dumps({"uuids": {"uuid": "stable-phone"}})
        with mock.patch.dict(
            os.environ,
            {"IG_PASSWORD": "secret", "IG_SESSION_JSON": session, "IG_SESSION_FILE": ""},
            clear=False,
        ):
            with mock.patch.object(post_instagram, "session_candidates", return_value=[]):
                with mock.patch.object(post_instagram, "_persist_session"):
                    self.assertTrue(post_instagram.login(client))
        client.set_settings.assert_called_once()
        client.login.assert_called_once()
        self.assertEqual(client.set_settings.call_args.args[0]["uuids"]["uuid"], "stable-phone")

    def test_batch_with_no_videos_does_not_log_in(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        with mock.patch.object(post_instagram, "login") as login:
            code = post_instagram.post_batch(tmp.name)
        self.assertEqual(code, 0)
        login.assert_not_called()

    def test_upload_uses_media_code(self):
        class Media:
            code = "Reel1"
            pk = 7

        video = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
        self.addCleanup(lambda: Path(video.name).unlink(missing_ok=True))
        video.write(b"not-a-real-video")
        video.close()
        client = mock.Mock()
        client.clip_upload.return_value = Media()
        posted = post_instagram.post_video(client, video.name, "hello")
        self.assertEqual(posted["url"], "https://www.instagram.com/reel/Reel1/")
        client.clip_upload.assert_called_once()
        self.assertEqual(client.clip_upload.call_args.args[1], "hello")


if __name__ == "__main__":
    unittest.main()
