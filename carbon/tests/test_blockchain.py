"""
What `carbon/services/blockchain.py` is still allowed to say.

Blockchain was withdrawn as a product on 2026-08-03 and `BLOCKCHAIN_ENABLED` has defaulted False
since 2026-08-06. One module survived that: this one. It writes the production data hash the
certifier packet's integrity line cites, and `backend/settings/base.py` records a deliberate
decision to keep the restore path in case an export buyer ever requires chain anchoring.

Kept code with no product behind it is exactly the code nobody re-reads, so what it may assert
needs a test rather than a comment. The rules below are the whole point of the file:

  * With blockchain disabled, the service must construct QUIETLY and report itself not-ready. It
    must not raise on boot (that was the 2026-08 failure mode in prod.py) and it must not invent
    an answer instead (that was `production_blockchain.py`, deleted 2026-09-08, whose mock branch
    answered `{"status": "completed", "transaction_hashes": ["0x000...0"]}` to a live caller).
  * A mock record must never claim to be verified, and must never be produced in production.
  * `verify_on_chain_hash` must report `blockchain_verified` equal to whether the hash actually
    matched. It used to hardcode True — on the exact call that had just proven a mismatch.
  * The hash must be deterministic and must change when the data changes, because the certifier
    packet's integrity line is only worth printing if that holds.

⛔ This file used to contain 18 tests, and 15 of them were broken. Fourteen errored with
`AttributeError` against twelve distinct methods that do not exist on the service —
`_calculate_data_hash`, `batch_verify_carbon_records`, `create_carbon_verification`,
`multisig_enabled`, `_validate_private_key` and seven more. They tested an API that was refactored
away and were never run by CI, so nothing noticed. A test suite for a fictional service is worse
than none: it reports coverage of a module it never touches.

The four initialization tests were the only ones that named real code, and all four are kept
below. The fifteenth breakage was one of them: it asserted the opposite of correct behaviour —
see `test_disabled_in_production_degrades_quietly`.
"""

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

from carbon.services.blockchain import BlockchainCarbonService, BlockchainUnavailableError

PROD = dict(ENVIRONMENT="production", DEBUG=False)
RPC = "https://rpc-amoy.polygon.technology/"
CONTRACT = "0x1234567890123456789012345678901234567890"


class BlockchainServiceInitializationTests(SimpleTestCase):
    @override_settings(BLOCKCHAIN_ENABLED=True, POLYGON_RPC_URL=RPC, CARBON_CONTRACT_ADDRESS=CONTRACT, **PROD)
    @patch("carbon.services.blockchain.WEB3_AVAILABLE", True)
    @patch("carbon.services.blockchain.Web3")
    @patch("carbon.services.blockchain.get_secure_blockchain_key")
    def test_production_initialization_success(self, mock_get_key, mock_web3_class):
        """The restore path still works: flag on, keys present, service comes up connected."""
        mock_web3 = MagicMock()
        mock_web3.is_connected.return_value = True
        mock_web3_class.return_value = mock_web3
        mock_get_key.return_value = "0x" + "1" * 64
        mock_web3.eth.account.from_key.return_value = MagicMock(address="0xabcdef1234567890abcdef1234567890abcdef12")

        service = BlockchainCarbonService()

        self.assertTrue(service.production_mode)
        self.assertTrue(service.blockchain_required)
        self.assertTrue(service._is_blockchain_ready())

    @override_settings(BLOCKCHAIN_ENABLED=False, **PROD)
    def test_disabled_in_production_degrades_quietly(self):
        """⚠️ INVERTED 2026-09-08. This test previously asserted the opposite.

        It demanded `BlockchainUnavailableError` when the service was constructed with
        BLOCKCHAIN_ENABLED=False in production — i.e. that turning the feature off crashed the
        app. That was the pre-withdrawal expectation, when blockchain was mandatory in production
        and `prod.py` refused to boot without Polygon keys. Since the add-on was withdrawn on
        2026-08-03 the correct behaviour is the reverse, and `blockchain_required` is now
        `(production_mode and blockchain_enabled) or force_blockchain`, which is False here.

        The test had been failing against correct code, in a suite CI never ran — the same shape
        as the emission-factor guards found red against the right values on 2026-09-07.

        What matters is that "off" means off in BOTH directions: no crash, and no invented
        answer either.
        """
        service = BlockchainCarbonService()

        self.assertFalse(service.blockchain_required)
        self.assertFalse(service._is_blockchain_ready())

    @override_settings(BLOCKCHAIN_ENABLED=True, POLYGON_RPC_URL=None, **PROD)
    @patch("carbon.services.blockchain.WEB3_AVAILABLE", True)
    def test_required_but_unconfigured_raises_rather_than_pretending(self):
        """Flag ON with no RPC is a misconfiguration, not a mode. Fail loudly.

        `WEB3_AVAILABLE` is pinned True deliberately. `_initialize_blockchain_connection` checks
        the library BEFORE the RPC URL, so without the patch this test would still pass on a
        machine where web3 is not installed — for the wrong reason, and it would stop testing the
        thing it is named after the moment that dependency moved.
        """
        with self.assertRaises(BlockchainUnavailableError):
            BlockchainCarbonService()

    @override_settings(BLOCKCHAIN_ENABLED=True, POLYGON_RPC_URL=RPC, ENVIRONMENT="development", DEBUG=True)
    @patch("carbon.services.blockchain.WEB3_AVAILABLE", False)
    def test_development_without_web3_degrades_gracefully(self):
        service = BlockchainCarbonService()

        self.assertFalse(service.production_mode)
        self.assertFalse(service.blockchain_required)
        self.assertIsNone(service.web3)


class MockRecordTests(SimpleTestCase):
    """The mock is the part that lies if nobody watches it."""

    @override_settings(BLOCKCHAIN_ENABLED=False, ENVIRONMENT="development", DEBUG=True)
    def test_a_mock_record_never_claims_to_be_verified(self):
        service = BlockchainCarbonService()

        record = service._create_mock_record(42, "ab" * 32)

        self.assertTrue(record["mock"], "a mock record must say so in its own payload")
        self.assertFalse(
            record["blockchain_verified"],
            "a development mock asserting blockchain_verified is the class of defect that "
            "deleted production_blockchain.py: a disabled feature answering as if it ran",
        )
        self.assertIn("development_mock", record["network"])

    @override_settings(BLOCKCHAIN_ENABLED=False, **PROD)
    def test_a_mock_record_is_refused_in_production(self):
        service = BlockchainCarbonService()

        with self.assertRaises(BlockchainUnavailableError):
            service._create_mock_record(42, "ab" * 32)

    @override_settings(BLOCKCHAIN_ENABLED=False, **PROD)
    def test_submitting_in_production_while_disabled_returns_nothing(self):
        """The whole path, not just the mock helper: prod + disabled must produce no record.

        `submit_production` reaches `_create_mock_record` when the chain is not ready and
        `blockchain_required` is False — precisely the production configuration today. The mock
        then raises `BlockchainUnavailableError` because `production_mode` is True, and
        `submit_production`'s broad `except` turns that into `None` (it only re-raises when
        blockchain is *required*).

        `None` is the right answer and the reason this test exists: the caller gets nothing, not
        a plausible-looking record. Contrast the deleted `production_blockchain.py`, which
        answered the same configuration with `{"status": "completed", "transaction_hashes":
        ["0x000...0"]}`. Assert the whole call, so an edit that softens the `production_mode`
        check inside the mock fails here rather than in a certifier packet.
        """
        service = BlockchainCarbonService()

        self.assertIsNone(service.submit_production(42, "ab" * 32))


class OnChainHashClaimTests(SimpleTestCase):
    @override_settings(BLOCKCHAIN_ENABLED=True, POLYGON_RPC_URL=RPC, CARBON_CONTRACT_ADDRESS=CONTRACT, **PROD)
    @patch("carbon.services.blockchain.WEB3_AVAILABLE", True)
    @patch("carbon.services.blockchain.Web3")
    @patch("carbon.services.blockchain.get_secure_blockchain_key")
    def _ready_service(self, mock_get_key, mock_web3_class, *, verify_hash_returns):
        mock_web3 = MagicMock()
        mock_web3.is_connected.return_value = True
        mock_web3_class.return_value = mock_web3
        mock_get_key.return_value = "0x" + "1" * 64
        mock_web3.eth.account.from_key.return_value = MagicMock(address="0x" + "a" * 40)

        service = BlockchainCarbonService()
        # Both tests below read `result["blockchain_verified"]`, a key `verify_on_chain_hash` only
        # emits on the ready path — so a broken fixture would raise KeyError rather than pass
        # quietly. Assert it anyway: the failure should name the setup, not a missing key.
        assert service._is_blockchain_ready(), "fixture did not produce a connected service"
        service.contract.functions.verifyHash.return_value.call.return_value = verify_hash_returns
        return service

    def test_a_hash_mismatch_is_not_reported_as_blockchain_verified(self):
        """`blockchain_verified` was hardcoded True, including when `matches` was False.

        That put the UNSAFE word on the one call that had just disproved it. `matches` is the
        answer to the question the method asks; nothing else belongs in that field.
        """
        service = self._ready_service(verify_hash_returns=False)

        result = service.verify_on_chain_hash(1, "ab" * 32)

        self.assertFalse(result["verified"])
        self.assertFalse(result["blockchain_verified"])

    def test_a_hash_match_is_reported_as_such(self):
        """The negative test above passes trivially if the mock never reaches the contract."""
        service = self._ready_service(verify_hash_returns=True)

        result = service.verify_on_chain_hash(1, "ab" * 32)

        self.assertTrue(result["verified"])
        self.assertTrue(result["blockchain_verified"])


class ProductionDataHashTests(SimpleTestCase):
    """The certifier packet's integrity line is only worth printing if these hold."""

    def setUp(self):
        with override_settings(BLOCKCHAIN_ENABLED=False, ENVIRONMENT="development", DEBUG=True):
            self.service = BlockchainCarbonService()
        self.data = {
            "production_id": 7,
            "company_id": 3,
            "start_date": "2026-03-01",
            "finish_date": "2026-09-01",
            "finalization_hash": "cd" * 32,
            "finalization_event_count": 14,
            "total_co2e": 812.5,
            "carbon_entry_count": 14,
        }

    def test_the_same_data_hashes_to_the_same_value(self):
        self.assertEqual(
            self.service.hash_production_data(dict(self.data)),
            self.service.hash_production_data(dict(self.data)),
        )

    def test_a_field_outside_the_hash_input_does_not_move_the_hash(self):
        """The hash covers an explicit allowlist, not whatever the caller happened to pass.

        This replaced a `test_key_order_does_not_change_the_hash`, which could never fail:
        `hash_production_data` builds its own `hash_input` dict from literal keys, so the order —
        and the presence — of anything in the argument is irrelevant by construction. A test that
        cannot fail is a claim about coverage, not coverage.

        The allowlist is the part worth pinning, and it cuts both ways: this test with
        `test_changing_any_hashed_field_changes_the_hash` fixes the hash's exact scope. Widening
        it is a deliberate act, because every historical hash a certifier packet has printed was
        computed under the old scope and would stop reproducing.
        """
        widened = dict(self.data, parcel_id=99, weather_summary="hot")

        self.assertEqual(
            self.service.hash_production_data(self.data),
            self.service.hash_production_data(widened),
        )

    def test_changing_any_hashed_field_changes_the_hash(self):
        baseline = self.service.hash_production_data(self.data)
        for field in self.data:
            with self.subTest(field=field):
                mutated = dict(self.data)
                mutated[field] = "mutated" if isinstance(mutated[field], str) else 999999
                self.assertNotEqual(
                    baseline,
                    self.service.hash_production_data(mutated),
                    f"{field} is in the hash input but changing it did not move the hash",
                )

    def test_the_backward_compatible_alias_is_the_same_function(self):
        self.assertEqual(
            self.service.hash_production_data(self.data),
            self.service.hash_carbon_data(self.data),
        )
