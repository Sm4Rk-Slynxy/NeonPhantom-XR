import unittest
from scripts.release_audit import check_content


class ReleaseAuditTests(unittest.TestCase):
    def test_key_and_private_path_are_blocked(self):
        for data in (b'-----BEGIN '+b'PRIVATE KEY-----', b'/home'+b'/example/private', b'192.'+b'168.23.5'):
            with self.assertRaises(ValueError):check_content('accidental.txt',data)

    def test_normal_code_and_public_attribution_are_allowed(self):
        check_content('example.py',b'ROOT = Path(__file__).resolve().parent')
        check_content('THIRD-PARTY-NOTICES.txt',b'Copyright upstream authors')
