"""
Management command to test the full blockchain verification flow locally.

Exercises the entire chain:
1. Stores finalization hash on a production (simulates finish_history)
2. Simulates monthly batch storing blockchain result (simulates Celery task)
3. Verifies the transparency API returns blockchain data
4. Verifies the verify-blockchain endpoint works

Usage:
    poetry run python manage.py test_blockchain_flow
"""

import hashlib
import json

from django.core.management.base import BaseCommand
from django.test import RequestFactory
from django.utils import timezone

from history.models import Production


class Command(BaseCommand):
    help = "Test the full blockchain verification flow locally"

    def handle(self, *args, **options):
        self.stdout.write("\n=== Blockchain Verification Flow Test ===\n")

        # Step 1: Find a published production
        production = Production.objects.filter(published=True).first()
        if not production:
            self.stdout.write(self.style.ERROR("No published productions found. Run create_demo_user first."))
            return

        self.stdout.write(f"Using production: {production.name} (ID: {production.id})")

        # Step 2: Simulate finalization hash (what finish_history does)
        self.stdout.write("\n--- Step 1: Store finalization hash ---")
        events = production.get_events()
        event_data = json.dumps(events, sort_keys=True, default=str, separators=(",", ":"))
        finalization_hash = hashlib.sha256(event_data.encode()).hexdigest()

        if production.extra_data is None:
            production.extra_data = {}

        production.extra_data["finalization_hash"] = finalization_hash
        production.extra_data["finalization_timestamp"] = timezone.now().isoformat()
        production.extra_data["finalization_event_count"] = len(events)
        self.stdout.write(f"  Finalization hash: {finalization_hash[:20]}...")
        self.stdout.write(f"  Event count: {len(events)}")

        # Step 3: Simulate monthly batch storing blockchain result
        self.stdout.write("\n--- Step 2: Simulate blockchain submission ---")
        mock_tx_hash = "0x" + hashlib.sha256(f"mock_{production.id}_{finalization_hash}".encode()).hexdigest()

        production.extra_data["blockchain_tx_hash"] = mock_tx_hash
        production.extra_data["blockchain_block_number"] = 48123456
        production.extra_data["blockchain_network"] = "polygon_amoy"
        production.extra_data["blockchain_submitted_at"] = timezone.now().isoformat()
        production.extra_data["blockchain_verified"] = True
        production.extra_data["blockchain_transaction"] = mock_tx_hash
        production.save(update_fields=["extra_data"])
        self.stdout.write(f"  TX hash: {mock_tx_hash[:30]}...")
        self.stdout.write(f"  Block: 48123456")
        self.stdout.write(self.style.SUCCESS("  Saved to production extra_data"))

        # Step 4: Test the transparency API response
        self.stdout.write("\n--- Step 3: Test transparency API ---")
        from history.transparency_views import _get_blockchain_verification_data

        verification_data = _get_blockchain_verification_data(production)
        self.stdout.write(f"  tx_hash: {verification_data.get('tx_hash', 'MISSING')[:30]}...")
        self.stdout.write(f"  verified: {verification_data.get('verified')}")
        self.stdout.write(f"  finalization_hash: {verification_data.get('finalization_hash', 'MISSING')[:20]}...")
        self.stdout.write(f"  explorer_url: {verification_data.get('explorer_url', 'MISSING')[:50]}...")

        if verification_data.get("tx_hash") and verification_data.get("verified"):
            self.stdout.write(self.style.SUCCESS("  Transparency API: PASS"))
        else:
            self.stdout.write(self.style.ERROR("  Transparency API: FAIL"))

        # Step 5: Test the verify-blockchain endpoint
        self.stdout.write("\n--- Step 4: Test verify-blockchain endpoint ---")
        from history.transparency_views import verify_blockchain

        factory = RequestFactory()
        request = factory.get(f"/api/history/transparency/{production.id}/verify-blockchain/")
        # Simulate anonymous user
        from django.contrib.auth.models import AnonymousUser

        request.user = AnonymousUser()

        response = verify_blockchain(request, production_id=production.id)
        response_data = response.data

        self.stdout.write(f"  Status code: {response.status_code}")
        self.stdout.write(f"  Response status: {response_data.get('status')}")
        self.stdout.write(f"  TX hash: {response_data.get('tx_hash', 'N/A')[:30]}...")

        if response.status_code == 200 and response_data.get("status") in ("verified", "submitted"):
            self.stdout.write(self.style.SUCCESS("  Verify endpoint: PASS"))
        else:
            self.stdout.write(self.style.ERROR(f"  Verify endpoint: FAIL - {response_data}"))

        # Step 6: Show frontend test instructions
        self.stdout.write("\n--- Step 5: Frontend verification ---")
        self.stdout.write(f"  Open: http://localhost:3000/production/{production.id}")
        self.stdout.write("  Check:")
        self.stdout.write('    - "How This Food Was Grown" card shows "Blockchain Protected"')
        self.stdout.write('    - "View on Explorer" link is visible')
        self.stdout.write('    - Event cards show "BLOCKCHAIN SECURED" badge')
        self.stdout.write('    - Event details show "Blockchain Security" section')
        self.stdout.write(f"\n  API: http://localhost:8000/api/history/transparency/{production.id}/")
        self.stdout.write(
            f"  Verify: http://localhost:8000/api/history/transparency/{production.id}/verify-blockchain/"
        )

        self.stdout.write(self.style.SUCCESS("\n=== Flow test complete ===\n"))
