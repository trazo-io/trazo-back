"""
Management command to submit a production to the blockchain (Polygon).

This command:
1. Finds a published production with events
2. Stores the finalization hash (if not already present)
3. Submits the data hash to the TransparencyVerification contract
4. Stores the tx_hash back on the History record
5. Verifies the transaction on-chain

Usage:
    poetry run python manage.py submit_to_blockchain
    poetry run python manage.py submit_to_blockchain --production-id 99
"""

import hashlib
import json

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from history.models import History


class Command(BaseCommand):
    help = "Submit a production to the blockchain (Polygon)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--production-id",
            type=int,
            default=None,
            help="Specific production ID to submit",
        )

    def handle(self, *args, **options):
        self.stdout.write("\n=== Blockchain Submission ===\n")

        # Check configuration
        self.stdout.write("--- Checking configuration ---")
        blockchain_enabled = getattr(settings, "BLOCKCHAIN_ENABLED", False)
        rpc_url = getattr(settings, "POLYGON_RPC_URL", "")
        contract_address = getattr(settings, "CARBON_CONTRACT_ADDRESS", "")
        private_key = getattr(settings, "BLOCKCHAIN_PRIVATE_KEY", "")

        self.stdout.write(f"  BLOCKCHAIN_ENABLED: {blockchain_enabled}")
        self.stdout.write(f"  POLYGON_RPC_URL: {rpc_url[:40]}..." if rpc_url else "  POLYGON_RPC_URL: NOT SET")
        self.stdout.write(
            f"  CARBON_CONTRACT_ADDRESS: {contract_address}"
            if contract_address
            else "  CARBON_CONTRACT_ADDRESS: NOT SET"
        )
        self.stdout.write(f"  BLOCKCHAIN_PRIVATE_KEY: {'***set***' if private_key else 'NOT SET'}")

        if not blockchain_enabled:
            self.stdout.write(self.style.ERROR("\n  BLOCKCHAIN_ENABLED is False. Set it to True in .env"))
            return

        if not contract_address:
            self.stdout.write(self.style.ERROR("\n  CARBON_CONTRACT_ADDRESS not set. Deploy the contract first."))
            return

        # Check Web3 connection
        self.stdout.write("\n--- Checking blockchain connection ---")
        try:
            from web3 import Web3

            w3 = Web3(Web3.HTTPProvider(rpc_url))
            if not w3.is_connected():
                self.stdout.write(self.style.ERROR("  Cannot connect to Polygon RPC"))
                return
            self.stdout.write(self.style.SUCCESS(f"  Connected to chain ID: {w3.eth.chain_id}"))

            account = w3.eth.account.from_key(private_key)
            balance = w3.eth.get_balance(account.address)
            balance_matic = Web3.from_wei(balance, "ether")
            self.stdout.write(f"  Wallet: {account.address}")
            self.stdout.write(f"  Balance: {balance_matic} MATIC")

            if balance == 0:
                self.stdout.write(self.style.ERROR("\n  Wallet has 0 MATIC. Get testnet MATIC from faucet:"))
                self.stdout.write(f"  https://faucet.polygon.technology/ (send to {account.address})")
                return
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"  Web3 error: {e}"))
            return

        # Find production
        self.stdout.write("\n--- Finding production ---")
        prod_id = options.get("production_id")
        if prod_id:
            production = History.objects.filter(id=prod_id, published=True).first()
        else:
            production = History.objects.filter(published=True).first()

        if not production:
            self.stdout.write(self.style.ERROR("  No published production found."))
            return

        self.stdout.write(f"  Using: {production.name} (ID: {production.id})")

        # Store finalization hash if not present
        self.stdout.write("\n--- Step 1: Ensure finalization hash ---")
        if production.extra_data is None:
            production.extra_data = {}

        if not production.extra_data.get("finalization_hash"):
            events = production.get_events()
            event_data = json.dumps(events, sort_keys=True, default=str, separators=(",", ":"))
            try:
                finalization_hash = Web3.keccak(text=event_data).hex().removeprefix("0x")
            except Exception:
                finalization_hash = hashlib.sha256(event_data.encode()).hexdigest()

            production.extra_data["finalization_hash"] = finalization_hash
            production.extra_data["finalization_timestamp"] = timezone.now().isoformat()
            production.extra_data["finalization_event_count"] = len(events)
            production.save(update_fields=["extra_data"])
            self.stdout.write(f"  Stored finalization hash: {finalization_hash[:20]}...")
        else:
            finalization_hash = production.extra_data["finalization_hash"]
            self.stdout.write(f"  Already has finalization hash: {finalization_hash[:20]}...")

        # Submit to blockchain
        self.stdout.write("\n--- Step 2: Submit to blockchain ---")
        try:
            from carbon.services.blockchain import BlockchainCarbonService
            from carbon.tasks import build_blockchain_raw_data

            service = BlockchainCarbonService()

            if not service._is_blockchain_ready():
                self.stdout.write(self.style.ERROR("  BlockchainCarbonService is not ready."))
                self.stdout.write(f"  web3 connected: {service.web3 is not None and service.web3.is_connected()}")
                self.stdout.write(f"  contract loaded: {service.contract is not None}")
                self.stdout.write(f"  account loaded: {service.account is not None}")
                return

            self.stdout.write(self.style.SUCCESS("  BlockchainCarbonService is READY"))
            self.stdout.write(f"  Contract: {service.contract.address}")
            self.stdout.write(f"  Wallet: {service.account.address}")

            # Build data hash using the shared function
            company = (
                production.parcel.establishment.company
                if production.parcel and production.parcel.establishment
                else None
            )
            company_id = company.id if company else 0
            _raw_data, data_hash, _total_co2e, _carbon_count, _event_count = build_blockchain_raw_data(
                production, company_id
            )

            self.stdout.write(f"  Data hash: {data_hash[:20]}...")
            self.stdout.write("  Submitting transaction...")

            result = service.submit_production(production.id, data_hash)

            if result:
                tx_hash = result.get("transaction_hash", "")
                block_number = result.get("block_number", 0)
                is_mock = result.get("mock", False)

                self.stdout.write(f"  TX Hash: {tx_hash}")
                self.stdout.write(f"  Block: {block_number}")
                self.stdout.write(f"  Gas Used: {result.get('gas_used', 'N/A')}")
                self.stdout.write(f"  Mock: {is_mock}")

                if is_mock:
                    self.stdout.write(self.style.WARNING("  WARNING: Mock data, not a real blockchain transaction."))
                else:
                    self.stdout.write(self.style.SUCCESS("  REAL blockchain transaction submitted!"))

                # Store result on production
                production.extra_data["blockchain_tx_hash"] = tx_hash
                production.extra_data["blockchain_block_number"] = block_number
                production.extra_data["blockchain_network"] = result.get("network", "polygon_amoy")
                production.extra_data["blockchain_submitted_at"] = timezone.now().isoformat()
                production.extra_data["blockchain_verified"] = result.get("blockchain_verified", False)
                production.extra_data["blockchain_data_hash"] = data_hash
                production.save(update_fields=["extra_data"])

                explorer_url = getattr(settings, "POLYGON_EXPLORER_URL", "https://amoy.polygonscan.com")
                self.stdout.write(f"\n  Explorer: {explorer_url}/tx/{tx_hash}")
            else:
                self.stdout.write(self.style.ERROR("  Submission returned None"))

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"  Error: {e}"))
            import traceback

            traceback.print_exc()

        # Verify via transparency API
        self.stdout.write("\n--- Step 3: Verify via API ---")
        try:
            from history.transparency_views import _get_blockchain_verification_data

            verification = _get_blockchain_verification_data(production)
            self.stdout.write(f"  tx_hash: {verification.get('tx_hash', 'MISSING')}")
            self.stdout.write(f"  verified: {verification.get('verified')}")
            self.stdout.write(f"  explorer_url: {verification.get('explorer_url', 'MISSING')}")

            if verification.get("tx_hash"):
                self.stdout.write(self.style.SUCCESS("  API verification: PASS"))
            else:
                self.stdout.write(self.style.ERROR("  API verification: FAIL"))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"  API verification error: {e}"))

        # Show frontend URLs
        public_id = production.public_id if hasattr(production, "public_id") and production.public_id else production.id
        self.stdout.write("\n--- Frontend URLs ---")
        self.stdout.write(f"  QR Page: http://localhost:3000/production/{public_id}")
        self.stdout.write(f"  API: http://localhost:8000/api/history/transparency/{public_id}/")
        self.stdout.write(f"  Verify: http://localhost:8000/api/history/transparency/{public_id}/verify-blockchain/")

        self.stdout.write(self.style.SUCCESS("\n=== Done ===\n"))
