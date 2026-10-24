"""Route/credential boundary tests; no model or external requests."""
import os
import unittest
from unittest.mock import patch

from adaptive_inference.client_routing import gateway_client_options


class GatewayClientRoutingTests(unittest.TestCase):
    def test_default_and_explicit_proxy_prefix_preserve_authority(self):
        self.assertEqual(gateway_client_options(), {
            "base_url": "http://127.0.0.1:18100/v1", "api_key": "local"})
        self.assertEqual(gateway_client_options(
            base_url="https://gateway.example:8443/team/inference/v1/", background=True), {
                "base_url": "https://gateway.example:8443/team/inference/background/v1",
                "api_key": "local"})
        self.assertEqual(gateway_client_options(
            base_url="http://[::1]:18101/v1", background=True)["base_url"],
            "http://[::1]:18101/background/v1")

    def test_background_is_idempotent_and_cannot_promote_a_worker(self):
        for background in (False, True):
            self.assertEqual(gateway_client_options(
                base_url="https://gateway.example/prefix/background/v1/",
                background=background)["base_url"],
                "https://gateway.example/prefix/background/v1")

    def test_credential_resolution_is_explicit_and_not_cached(self):
        with patch.dict(os.environ, {"ADAPTIVE_TEST_KEY": "first"}, clear=True):
            self.assertEqual(gateway_client_options(api_key_env="ADAPTIVE_TEST_KEY")["api_key"], "first")
            os.environ["ADAPTIVE_TEST_KEY"] = "second"
            self.assertEqual(gateway_client_options(api_key_env="ADAPTIVE_TEST_KEY")["api_key"], "second")
            self.assertEqual(gateway_client_options()["api_key"], "local")
            for value in ("", "bad\nheader"):
                os.environ["ADAPTIVE_TEST_KEY"] = value
                with self.assertRaises(ValueError):
                    gateway_client_options(api_key_env="ADAPTIVE_TEST_KEY")
            with self.assertRaises(ValueError):
                gateway_client_options(api_key_env="MISSING_TEST_KEY")
            with self.assertRaises(ValueError):
                gateway_client_options(api_key_env="literal-secret-not-a-variable")

    def test_ambiguous_bases_and_nonboolean_selection_fail_before_client_use(self):
        for base in (None, "", "ftp://localhost/v1", "http://user:secret@localhost/v1",
                     "http://@localhost/v1", "http://localhost/v1?token=secret",
                     "http://localhost/v1#fragment", "http://localhost:0/v1",
                     "http://localhost:65536/v1", "http://localhost/v1\n",
                     "http://local\x7fhost/v1",
                     "http://localhost/base/../v1", "http://localhost/%2e%2e/v1",
                     "http://localhost//v1", "http://localhost\\example/v1",
                     "http://localhost/v1/chat/completions"):
            with self.subTest(base=base), self.assertRaises(ValueError):
                gateway_client_options(base_url=base)
        for value in (0, 1, "background", None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                gateway_client_options(background=value)


if __name__ == "__main__":
    unittest.main()
