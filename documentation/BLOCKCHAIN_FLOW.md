# Blockchain Verification Flow in Trazo

> **Audience**: Software engineers who may not have blockchain experience.
> Each section explains the *what*, *why*, and *where in the code*, with blockchain-specific
> jargon defined inline so you never need to look things up elsewhere.

---

## Blockchain Concepts You Need to Know

Before diving into the flow, here are the blockchain terms you'll encounter. Each is explained in plain engineering terms.

### Smart Contract

A **smart contract** is a program that lives on a blockchain. Once deployed, nobody can change its code — it runs exactly as written. Think of it like a microservice that's been made immutable. You call its functions by sending **transactions**.

Trazo's smart contract is written in **Solidity** (the language for Ethereum-compatible blockchains) and deployed on Polygon. It has functions like `registerProducer()` and `recordMonthlySummary()`.

### Transaction (tx)

A **transaction** is a request to execute a function on a smart contract. It costs money (gas fees) and, once confirmed, becomes a permanent record on the blockchain. Every transaction gets a unique **transaction hash** (tx_hash) — a hex string like `0x0787f7e6...` — which acts as its receipt.

### Gas and Gwei

Every transaction requires **gas** — a unit of computational work. More complex operations need more gas. You pay for gas using the blockchain's native currency (MATIC/POL on Polygon).

**Gas price** is measured in **gwei** (1 gwei = 0.000000001 MATIC). It's like a bid: higher gas price = faster processing. On Polygon:

| Gas Price | Speed | Cost per tx (typical) |
|-----------|-------|-----------------------|
| 25 gwei | Slow (may take minutes) | ~$0.0004 |
| 30 gwei | Normal (~2-5 seconds) | ~$0.0005 |
| 85 gwei | Fast (~1-2 seconds) | ~$0.001 |

**Gas limit** is the maximum gas you're willing to spend. If a function needs 80,000 gas and you set a limit of 300,000, you only pay for the 80,000 actually used. Setting the limit too low causes the transaction to fail.

**Key point for Trazo**: On Polygon, transactions cost fractions of a cent — roughly **$0.001 per production**. At 100 productions/year, that's ~$0.10/year total. Blockchain verification is essentially free.

### Nonce

A **nonce** is a sequential counter for your wallet. Your first transaction is nonce 0, second is nonce 1, etc. The blockchain uses this to prevent replay attacks and ensure transactions are processed in order. If a transaction gets stuck, you can replace it by submitting a new one with the same nonce but higher gas price.

### Keccak256 (Hashing)

**Keccak256** is a cryptographic hash function — the same one Ethereum uses internally. It takes any input (a string, a file, a JSON blob) and produces a fixed-length 64-character hex string.

```
Input: "Hello World"  → keccak256 → "592fa743889fc7f..."
Input: "Hello World!" → keccak256 → "a1b4cf09e2d8f7a..."  (completely different!)
```

Key properties:
- **Deterministic**: Same input always produces the same output
- **One-way**: You cannot reverse-engineer the input from the hash
- **Avalanche effect**: Changing one character completely changes the output

This is the foundation of Trazo's tamper detection. We hash all production events at finalization, store that hash, and later re-hash to check if anything changed.

### Polygon

**Polygon** is a blockchain network that's:
- **Cheap**: Transactions cost fractions of a cent (vs Ethereum at $5-50)
- **Fast**: Transactions confirm in ~2 seconds
- **EVM-Compatible**: Uses the same smart contract language as Ethereum
- **Production-ready**: Used by major companies (Reddit, Starbucks, Aave)

Trazo uses **Polygon Amoy** (testnet) for development and testing. In production, it uses **Polygon Mainnet**. The code is identical — only the RPC URL, contract address, and wallet change.

### Wallet

A **wallet** is a cryptographic key pair (private key + public address). Trazo's backend has a wallet that signs and sends transactions. The private key must be kept secret (it controls the funds), while the public address is visible to everyone.

- **Trazo's wallet address**: `0xAA03419dA4A695E728131506504Cb1bfB50A1256` (testnet)
- **Private key**: Stored securely via AWS Secrets Manager (never in code)

### Block Explorer (Polygonscan)

**Polygonscan** is a public website where anyone can look up transactions, addresses, and smart contracts on Polygon. It's like a read-only database viewer for the blockchain. When a consumer clicks "View on Explorer", they see the raw, immutable transaction data — independent of Trazo's systems.

- Testnet: `amoy.polygonscan.com`
- Mainnet: `polygonscan.com`

### ABI (Application Binary Interface)

The **ABI** is a JSON file that describes a smart contract's functions — their names, parameters, and return types. Think of it as the contract's API specification. Without the ABI, your code wouldn't know how to encode function calls.

Trazo's ABI is stored at: `carbon/contracts/CarbonVerification.json`

---

## What Does Blockchain Do in Trazo?

When a farmer finishes a production (e.g., a batch of avocados from planting to harvest), Trazo takes a **digital fingerprint** of everything that was documented — every event, every measurement — and stores that fingerprint permanently on a public blockchain (Polygon). This means:

- **Nobody can tamper** with the production data after it's sealed
- **Consumers can verify** the data is authentic by checking the blockchain
- **It's public and permanent** — not controlled by Trazo or the farmer

Think of it like a notary stamp. The notary (blockchain) doesn't store the full document — it stores a **certified seal** that proves the document hasn't changed since it was stamped.

---

## The Complete Flow (Step by Step)

### Step 1: Company Purchases the Blockchain Add-On

The blockchain feature is a paid add-on in Trazo's subscription system.

**What happens:**
- The farmer's company purchases "Blockchain Verification" through Stripe (Trazo's payment processor)
- Stripe sends a notification (webhook) to Trazo's backend
- Trazo flips a flag on the company: `blockchain_subscription_status = True`

**Where in the code:**
- `subscriptions/views.py` — handles Stripe webhooks
- `company/models.py` — stores the `blockchain_subscription_status` flag

**Key point:** If a company hasn't purchased this add-on, none of their productions will ever be submitted to blockchain. Both the immediate task and the monthly batch simply skip them.

---

### Step 2: Farmer Documents a Production

This is normal Trazo usage — nothing blockchain-specific happens yet.

**What happens:**
- Farmer creates a production (e.g., "Avocado Batch #47")
- Over weeks/months, they log events: planting, irrigation, fertilization, harvest, etc.
- Each event may have photos, measurements, notes
- Each event generates a `CarbonEntry` with calculated CO2e emissions

**Where in the code:**
- `history/models.py` — `History` model (the production)
- `carbon/models.py` — `CarbonEntry` model (emissions per event)

---

### Step 3: Farmer Finalizes the Production (Data Sealing + Immediate Blockchain Submission)

This is the critical step where two things happen back-to-back:

#### 3a. Finalization Hash (Data Sealing)

1. Farmer clicks "Finish Production" in the app
2. Trazo collects **all events** for that production
3. Serializes them into a deterministic JSON format (sorted keys, consistent separators)
4. Computes a **keccak256 hash** of all that event data
5. This hash — the **finalization hash** — is stored on the production record

**The finalization hash is like a fingerprint.** If even one character of the event data changes afterward, recomputing the hash would produce a completely different result — making tampering detectable.

**What gets stored on the production:**
```
extra_data = {
    "finalization_hash": "a1b2c3d4e5f6...",      <- fingerprint of all events
    "finalization_timestamp": "2026-01-15T10:30:00Z",
    "finalization_event_count": 12                 <- how many events were sealed
}
```

**Where in the code:**
- `product/views.py` -> `_store_finalization_hash()` — computes and stores the hash
- `product/views.py` -> `finish_history()` — the action that triggers finalization

#### 3b. Immediate Blockchain Submission

Immediately after the finalization hash is stored, Trazo submits the production to blockchain — without waiting for the monthly batch.

**How it works:**

1. `finish_history()` calls `_trigger_blockchain_submission(history)`
2. This checks if the company has `blockchain_subscription_status = True`
3. If yes, it dispatches a Celery background task: `submit_production_to_blockchain.delay(history.id)`
4. The task is wrapped in `transaction.on_commit()` — a Django mechanism that ensures the Celery task only fires **after** the database transaction commits successfully

**Why `transaction.on_commit()`?** Without it, there's a race condition: the Celery task could start running before the finalization hash is saved to the database, and then it would try to submit incomplete data. `on_commit()` guarantees the hash is persisted first.

**The Celery task (`submit_production_to_blockchain`):**
- Loads the production and its company
- Calls `_submit_single_production_to_blockchain()` — the same function used by the monthly batch
- On success: stores the blockchain tx_hash, block number, and network on the production record
- On failure: the monthly batch will pick it up later (safety net)

**After successful submission, the production record is updated:**
```
extra_data = {
    "finalization_hash": "a1b2c3d4e5f6...",
    "finalization_timestamp": "2026-01-15T10:30:00Z",
    "finalization_event_count": 12,
    "blockchain_tx_hash": "0x0787f7e6...",            <- the transaction ID on Polygon
    "blockchain_block_number": 34417379,               <- which block it's in
    "blockchain_network": "polygon_amoy",
    "blockchain_submitted_at": "2026-02-24T19:46:14Z",
    "blockchain_verified": true,                       <- real transaction, not mock
    "blockchain_data_hash": "9d4ef6b25a..."            <- the hash sent to the smart contract
}
```

**Where in the code:**
- `product/views.py` -> `_trigger_blockchain_submission()` — dispatches the Celery task
- `carbon/tasks.py` -> `submit_production_to_blockchain()` — the immediate submission Celery task
- `carbon/tasks.py` -> `_submit_single_production_to_blockchain()` — shared submission logic

---

### Step 4: Monthly Batch (Safety Net)

The monthly batch is now a **reconciliation safety net**, not the primary submission path.

**Why it still exists:**
The immediate submission in Step 3b can fail for many reasons:
- Network timeout or Polygon RPC downtime
- Gas price spike making the transaction too expensive
- Celery worker being down at the moment
- Insufficient wallet balance

The monthly batch catches these failures.

**What happens:**
1. A scheduled Celery task runs on the 1st of each month at 2:00 AM UTC
2. It queries: *"Which companies have blockchain enabled?"*
3. For each company: *"Which productions are finalized but NOT yet on blockchain?"*
4. For each such production: calls `_submit_single_production_to_blockchain()` — the exact same function used by the immediate task

**The query logic is simple:**
```
Finalized (finish_date is set) + Not on blockchain (no tx_hash) = Submit
```

This means it doesn't matter *when* the production was finalized. A production finalized in January whose immediate submission failed will still get picked up by the February 1st batch. Nothing falls through the cracks.

**Where in the code:**
- `carbon/tasks.py` -> `batch_submit_monthly_summaries()` — the Celery beat task
- Uses the same `_submit_single_production_to_blockchain()` as the immediate task

**Cost comparison — immediate vs monthly:**

| Aspect | Immediate (Step 3b) | Monthly Batch (Step 4) |
|--------|---------------------|------------------------|
| Transactions per production | 1 | 1 |
| Cost per production (Polygon) | ~$0.001 | ~$0.001 |
| Consumer sees "Verified" | Seconds after finalization | Up to 30 days later |
| Failure handling | Monthly batch retries | Manual re-run or wait |

Both approaches run the same number of transactions. The monthly batch does NOT aggregate multiple productions into one transaction — it submits one tx per production. So the cost is identical. The only difference is **timing**: consumers see verification in seconds vs potentially weeks.

---

### Step 5: Smart Contract Stores the Record

This is what happens on the blockchain itself.

**What happens:**
1. Trazo's wallet sends a transaction to the `CarbonVerification` smart contract on Polygon
2. The contract first checks if the producer (company) is registered — if not, it registers them via `registerProducer()`
3. Then it calls `recordMonthlySummary()` which stores:
   - The **data hash** (keccak256 fingerprint of the production)
   - Producer and production IDs
   - Total emissions in grams of CO2e
   - Crop type
   - Timestamp
4. The contract verifies the hash hasn't been used before (prevents duplicate submissions)
5. It checks USDA compliance thresholds for the crop type
6. The record is now **permanent and immutable** — nobody can change or delete it

**What the contract stores per production:**
```
CarbonRecord {
    dataHash: bytes32        <- the production fingerprint
    producerId: uint256      <- which company (integer ID)
    productionId: uint256    <- which production (integer ID)
    totalEmissions: uint256  <- CO2e in grams
    totalOffsets: uint256    <- carbon offsets
    cropType: string         <- e.g., "avocado"
    timestamp: uint256       <- when recorded (Unix timestamp)
    usdaCompliant: bool      <- passes USDA thresholds?
    creditsIssued: uint256   <- carbon credits awarded
}
```

**Note on types:** The smart contract uses `uint256` (unsigned 256-bit integer) for IDs and amounts. This means all values must be positive integers — CO2e is converted from kg to grams before submission.

**Where in the code:**
- `contracts/solidity/CarbonVerification.sol` — the Solidity smart contract
- `carbon/services/blockchain.py` -> `submit_monthly_summary()` — builds and sends the transaction
- Currently deployed at: `0xb546CbC8B4080C246Db923f0354532b31b250880` (Polygon Amoy testnet)

---

### Step 6: Consumer Scans QR Code (Four-State Display)

This is the consumer-facing part. The consumer page shows one of **four states** depending on where the production is in the blockchain flow:

#### State 1: Not Yet Verified (Gray Shield)
**When**: Production is still in progress (not finalized)
**What consumer sees**: "Not Yet Verified — Production in progress, verification available after completion"
**Why**: There's no finalization hash yet, so there's nothing to verify

#### State 2: Data Sealed (Blue Shield)
**When**: Production is finalized (has `finalization_hash`) but NOT yet on blockchain (no `tx_hash`)
**What consumer sees**: "Data Sealed — Data integrity verified, blockchain submission pending"
**Why**: This is the gap window between finalization and blockchain submission. Even though the data isn't on-chain yet, Layer 1 verification (event hash check) already works, so we can confirm the data hasn't been modified since sealing. Before this state was added, there was a misleading gap where finalized productions showed no blockchain info at all.

#### State 3: Blockchain Protected (Purple Shield)
**When**: Production is on blockchain AND integrity check passes
**What consumer sees**: "Blockchain Protected — Data integrity verified on blockchain" + "View on Explorer" link
**Why**: Full verification. The consumer can independently verify on Polygonscan.

#### State 4: Data Integrity Warning (Red Shield)
**When**: Production is on blockchain BUT integrity check FAILS (data_integrity = "tampered")
**What consumer sees**: "Data Integrity Warning — [detail message]"
**Why**: Something was modified after blockchain submission. This is the tamper detection alert.

**How the frontend determines which state to show:**

```
API returns blockchain_verification: { tx_hash, is_finalized, ... }

if (has tx_hash) {
    call verify-blockchain endpoint
    if (data_integrity === "intact") -> State 3 (Blockchain Protected)
    else -> State 4 (Data Integrity Warning)
} else if (is_finalized) {
    call verify-blockchain endpoint (Layer 1 still works)
    -> State 2 (Data Sealed)
} else {
    -> State 1 (Not Yet Verified)
}
```

**The `canVerifyIntegrity` flag:**
The frontend calls the verify-blockchain endpoint only when `canVerifyIntegrity` is true:
```typescript
const canVerifyIntegrity = !!(blockchainVerification?.tx_hash || blockchainVerification?.is_finalized);
```
This means Layer 1 verification runs even before blockchain submission, enabling the "Data Sealed" state.

**API response includes:**
```json
{
    "blockchain_verification": {
        "tx_hash": "0x0787f7e6...",
        "verified": true,
        "is_finalized": true,
        "block_number": 34417379,
        "network": "polygon_amoy",
        "explorer_url": "https://amoy.polygonscan.com/tx/0x0787f7e6...",
        "finalization_hash": "9f115bd8...",
        "finalization_event_count": 9
    }
}
```

**Where in the code:**
- `history/transparency_views.py` -> `_get_blockchain_verification_data()` — returns `is_finalized`, `tx_hash`, etc.
- `trazo-app/src/views/Scan/ProductDetail/ProductDetail.tsx` — four-state rendering logic
- `trazo-app/src/services/transparencyQrApi.ts` — `useVerifyBlockchainIntegrityQuery` RTK Query hook

---

### Step 7: Three-Layer Integrity Verification (Tamper Detection)

This is what makes the blockchain verification *real* — not just a badge, but an actual cryptographic proof that the data hasn't been modified.

**The problem it solves:** The blockchain stores a hash, but the production data lives in Trazo's database. What if someone modifies data after blockchain submission? Worse — what if a sophisticated attacker modifies data AND updates the stored hashes in the database to cover their tracks? Without proper verification, the blockchain hash is just decoration.

**Trazo solves this with three independent layers of verification:**

#### Layer 1 — Event Integrity (Fast, No Network Call)

Runs on every verify request. Zero cost, instant.

1. Takes the current events from the database
2. Re-computes the finalization hash using the exact same algorithm (keccak256) used at finalization time
3. Compares the re-computed hash against the stored `finalization_hash` in the database
4. **Match** -> events haven't changed since finalization
5. **Mismatch** -> something was modified after the production was sealed

**What it catches:** Accidental edits, signal-triggered recalculations, developer mistakes — any change to event data after finalization.

**Key improvement:** Layer 1 works immediately after finalization — even before blockchain submission. This is what enables the "Data Sealed" (blue) state. Previously, there was a gap where Layer 1 couldn't run because the code only triggered verification when a `tx_hash` existed.

**Limitation:** Both values (current data and stored hash) live in Trazo's database. A sophisticated attacker could modify the events AND update the stored `finalization_hash` to match. Layer 1 would pass. That's where Layer 2 comes in.

#### Layer 2 — On-Chain Verification (Reads the Immutable Blockchain)

Calls the smart contract directly. Free (read-only `view` call, no gas required).

1. Calls `getCarbonRecord(productionId)` on the Polygon smart contract
2. Reads back the `dataHash` (bytes32) — this is **immutable**, stored at submission time, impossible to change
3. Compares the on-chain `dataHash` against the `blockchain_data_hash` stored in the database
4. **Match** -> database record is authentic, hasn't been tampered with
5. **Mismatch** -> someone modified the database, but the blockchain still has the original

**What it catches:** The worst-case scenario — a sophisticated attacker who modifies production data AND updates all stored hashes in the database. They can change anything in PostgreSQL, but they **cannot** change what's on the Polygon blockchain. The on-chain hash will expose the tampering.

**Why this works:** To fool Layer 2, an attacker would need to either:
- Modify the Polygon blockchain (impossible — millions of validator nodes)
- Reverse a keccak256 hash (mathematically impossible)

Neither is feasible. This is the core value proposition of blockchain verification.

#### Layer 3 — Consumer-Verifiable (Full Independence)

The consumer doesn't need to trust Trazo at all.

1. Consumer taps "View on Explorer" -> opens Polygonscan (independent, public website)
2. Sees the raw transaction: block number, timestamp, input data
3. Can independently verify the on-chain hash against the production data
4. This is a **zero-trust** verification — the consumer relies only on the public blockchain, not on Trazo's systems

**Summary of the three layers:**

```
Layer 1 -- Event Integrity (automatic, every request):
  Re-hash current events -> compare to stored finalization_hash (in our DB)
  Catches: any event modification after finalization
  Trust: relies on our database for the stored hash
  Available: immediately at finalization (no blockchain needed)

Layer 2 -- On-Chain Verification (automatic, reads smart contract):
  Read dataHash from Polygon -> compare to stored blockchain_data_hash (in our DB)
  Catches: database tampering -- attacker changes stored hashes to cover tracks
  Trust: relies on Polygon blockchain (immutable, public)
  Available: only after blockchain submission

Layer 3 -- Consumer-Verifiable (manual, via block explorer):
  Consumer checks Polygonscan independently
  Catches: everything -- consumer trusts only the public blockchain
  Trust: zero-trust -- consumer verifies directly
  Available: only after blockchain submission
```

**All three layers must pass for "Blockchain Protected" status.** If any layer detects tampering, the consumer sees a red "Data Integrity Warning".

**How the layers build on each other:**

```
Events modified?                          -> Layer 1 catches it (fast, free)
Events modified + DB hash faked           -> Layer 2 catches it (reads immutable blockchain)
Everything in Trazo's systems faked       -> Layer 3 catches it (consumer checks Polygonscan directly)
```

**Attack scenarios:**

| Scenario | Layer 1 | Layer 2 | Layer 3 |
|----------|---------|---------|---------|
| Developer accidentally edits an event | Catches it | -- | -- |
| Django signal recalculates carbon data | Catches it | -- | -- |
| Attacker modifies events in database | Catches it | Catches it | Catches it |
| Attacker modifies events AND fakes finalization_hash | Passes (fooled) | Catches it | Catches it |
| Attacker modifies ALL stored hashes in Trazo's DB | Passes (fooled) | Catches it | Catches it |
| Attacker compromises Trazo's entire database | Passes (fooled) | Catches it | Catches it |

**API response from the verify endpoint (all layers pass):**

```json
{
    "status": "verified",
    "data_integrity": "intact",
    "data_integrity_detail": "Production data verified against immutable blockchain record.",
    "on_chain_verified": true,
    "on_chain_hash": "9d4ef6b25ac5...",
    "tx_hash": "0x0787f7e6...",
    "verified": true,
    "explorer_url": "https://amoy.polygonscan.com/tx/0x0787f7e6..."
}
```

If tampering is detected (any layer):

```json
{
    "status": "tampered",
    "data_integrity": "tampered",
    "data_integrity_detail": "Production data does NOT match the immutable blockchain record.",
    "on_chain_verified": false,
    "on_chain_hash": "9d4ef6b25ac5...",
    "tx_hash": "0x0787f7e6...",
    "explorer_url": "https://amoy.polygonscan.com/tx/0x0787f7e6..."
}
```

**Where in the code:**
- `history/transparency_views.py` -> `verify_blockchain()` — orchestrates all three layers
- `history/transparency_views.py` -> `_compute_finalization_hash()` — Layer 1: re-hashes current events
- `history/transparency_views.py` -> `_recompute_production_data_hash()` — Layer 2: rebuilds raw_data hash
- `carbon/services/blockchain.py` -> `read_on_chain_record()` — Layer 2: reads immutable hash from smart contract
- `trazo-app/.../ProductDetail.tsx` — Layer 3: renders explorer link for consumer verification

---

## Visual Flow Diagram

```
+-------------------------------+
|  1. COMPANY BUYS              |
|  BLOCKCHAIN ADD-ON            |
|  (Stripe purchase)            |
+----------|--------------------+
           | Sets blockchain_subscription_status = True
           v
+-------------------------------+
|  2. FARMER LOGS               |
|  PRODUCTION EVENTS            |
|  (Normal Trazo use)           |
+----------|--------------------+
           | Events + CarbonEntries created over time
           v
+-------------------------------+
|  3a. FARMER CLICKS            |
|  "FINISH PRODUCTION"          |
|                               |
|  -> Computes keccak256 hash   |
|     of ALL events             |
|  -> Stores as                 |
|     finalization_hash         |
+----------|--------------------+
           | Production is now sealed (Data Sealed state)
           | Layer 1 verification now works
           v
+-------------------------------+
|  3b. IMMEDIATE BLOCKCHAIN     |
|  SUBMISSION (Celery task)     |
|                               |
|  -> transaction.on_commit()   |
|     ensures DB is saved first |
|  -> Celery worker picks up    |
|     the task within seconds   |
|  -> Sends tx to Polygon       |
+----------|--------------------+
           | Success: tx_hash stored on production
           | Failure: monthly batch will retry
           v
+-------------------------------+
|  4. MONTHLY BATCH             |
|  (Safety Net)                 |
|                               |
|  -> Runs 1st of month 2AM    |
|  -> Finds finalized prods     |
|     WITHOUT tx_hash           |
|  -> Resubmits using same      |
|     _submit_single_...()      |
+----------|--------------------+
           | Catches any failures from Step 3b
           v
+-------------------------------+
|  5. SMART CONTRACT            |
|  STORES RECORD                |
|                               |
|  -> Immutable hash            |
|  -> Emissions data            |
|  -> USDA compliance           |
|  -> Permanent record          |
+----------|--------------------+
           | tx_hash stored back on production
           v
+-------------------------------+
|  6. CONSUMER SCANS            |
|  QR CODE                      |
|                               |
|  Four states:                 |
|  Gray  = Not Yet Verified     |
|  Blue  = Data Sealed          |
|  Purple = Blockchain Protected|
|  Red   = Integrity Warning    |
+----------|--------------------+
           | Consumer or app hits verify endpoint
           v
+--------------------------------------------------+
|  7. THREE-LAYER INTEGRITY VERIFICATION           |
|                                                  |
|  Layer 1 -- Event Integrity (fast, DB-only):     |
|    Re-hash current events -> compare to stored   |
|    finalization_hash                             |
|    Works: immediately after finalization          |
|    Catches: event modifications                  |
|                                                  |
|  Layer 2 -- On-Chain Verification (reads chain): |
|    Read dataHash from smart contract ->          |
|    compare to stored blockchain_data_hash        |
|    Works: after blockchain submission            |
|    Catches: DB tampering (attacker fakes hashes) |
|                                                  |
|  Layer 3 -- Consumer-Verifiable (Polygonscan):   |
|    Consumer clicks "View on Explorer" ->         |
|    independently verifies on-chain record        |
|    Works: after blockchain submission            |
|    Catches: everything (zero-trust)              |
|                                                  |
|  All pass -> "Blockchain Protected" (purple)     |
|  Any fail -> "Data Integrity Warning" (red)      |
+--------------------------------------------------+
```

---

## The Integrity Chain (How Hashes Connect)

One of the most important design decisions is how hashes chain together from events to blockchain:

```
1. Events (planting, irrigation, harvest, ...)
   |
   | keccak256(JSON of all events, sorted keys)
   v
2. finalization_hash (stored in production.extra_data)
   |
   | Included as a field in raw_data
   v
3. production_data_hash = keccak256(raw_data)
   |  raw_data includes: production_id, company_id, dates,
   |  carbon entries, AND the finalization_hash from step 2
   v
4. On-chain dataHash (stored immutably in smart contract)
```

This chain means the on-chain hash cryptographically covers:
- All carbon entry data (amounts, types, timestamps)
- The finalization hash, which itself covers all agricultural events
- Production metadata (dates, company, crop type)

If any event changes, the finalization hash changes, which changes the production data hash, which no longer matches the on-chain hash. Tampering is detected.

---

## Key Design Decisions Explained

### Why Immediate + Monthly (Belt and Suspenders)?

We could have used just one approach:
- **Immediate only**: Risk: if the Celery task fails, the production stays off-chain indefinitely
- **Monthly only**: Risk: consumers wait up to 30 days to see "Blockchain Protected"

By combining both:
1. 99% of productions get submitted within seconds (immediate)
2. The 1% that fail get caught within 30 days (monthly batch)
3. Both use the same `_submit_single_production_to_blockchain()` function — zero code duplication

### Why `transaction.on_commit()`?

```python
# In product/views.py -> _trigger_blockchain_submission()
transaction.on_commit(lambda: submit_production_to_blockchain.delay(history.id))
```

Without `on_commit()`, this race condition can happen:
1. `finish_history()` starts a database transaction
2. Celery task fires immediately
3. Celery worker tries to read `finalization_hash` from DB
4. But the DB transaction hasn't committed yet!
5. Celery reads `None` for the hash -> submission fails

`on_commit()` guarantees the Celery task only fires after the database transaction is successfully committed.

### Why Not Store Full Data On-Chain?

Storing full production data on blockchain would be:
- **Expensive**: Blockchain storage costs money per byte (storing 1KB costs ~$0.05 on Ethereum, ~$0.001 on Polygon)
- **Slow**: Large data takes longer to process
- **Unnecessary**: A hash proves integrity just as well

Instead, Trazo stores the **hash** (32 bytes, always the same size) on-chain and keeps the full data in its database. If anyone questions whether the data was changed, you can re-hash the current data and compare it to the on-chain hash. If they match, the data is authentic.

### Why Production-Level (Not Per-Event)?

Blockchain verification happens at the **production level**, not per-event. One production = one blockchain transaction, covering ALL events in that production:

- **Cost-effective**: 1 transaction vs 12+ transactions per production
- **Natural unit**: Consumers verify one product (they scan one QR code)
- **Complete coverage**: The finalization hash already covers all events cryptographically

---

## File Reference

| File | Role |
|------|------|
| `subscriptions/views.py` | Handles Stripe webhooks, activates blockchain flag |
| `company/models.py` | Stores `blockchain_subscription_status` on Company |
| `product/views.py` | Computes finalization hash (`_store_finalization_hash`), triggers immediate submission (`_trigger_blockchain_submission`) |
| `carbon/tasks.py` | Immediate task (`submit_production_to_blockchain`), monthly batch (`batch_submit_monthly_summaries`), shared logic (`_submit_single_production_to_blockchain`) |
| `carbon/services/blockchain.py` | Web3 integration: sends transactions (`submit_monthly_summary`), reads on-chain records (`read_on_chain_record`), hashing (`hash_carbon_data`) |
| `carbon/services/secure_key_management.py` | Secure private key retrieval (AWS Secrets Manager in production, env var in dev) |
| `contracts/solidity/CarbonVerification.sol` | Smart contract that stores records on Polygon |
| `carbon/contracts/CarbonVerification.json` | Contract ABI (interface definition) + deployment info |
| `history/transparency_views.py` | Three-layer verification (`verify_blockchain`, `_compute_finalization_hash`, `_recompute_production_data_hash`) |
| `trazo-app/.../ProductDetail.tsx` | Consumer QR page — four-state blockchain display with tamper warnings |
| `trazo-app/.../transparencyQrApi.ts` | RTK Query hook for `verify-blockchain` endpoint |
| `trazo-app/.../ConsumerEventCard.tsx` | Event cards with production-level blockchain link |
| `history/management/commands/submit_to_blockchain.py` | Manual command for one-off submissions |

---

## Environments

| Environment | Network | Explorer | Contract |
|-------------|---------|----------|----------|
| Development | Polygon Amoy (testnet) | amoy.polygonscan.com | `0xb546CbC8B4080C246Db923f0354532b31b250880` |
| Staging | Polygon Amoy (testnet) | amoy.polygonscan.com | TBD (separate deployment) |
| Production | Polygon Mainnet | polygonscan.com | TBD (separate deployment) |

Each environment has its own deployed contract and wallet. Testnet uses free MATIC from faucets; mainnet uses real POL/MATIC (~$0.001 per transaction).

**Environment variables for blockchain:**
```
BLOCKCHAIN_ENABLED=True
POLYGON_RPC_URL=https://rpc-amoy.polygon.technology/    # or mainnet RPC
CARBON_CONTRACT_ADDRESS=0xb546CbC8B4080C246Db923f0354532b31b250880
BLOCKCHAIN_PRIVATE_KEY=<wallet private key>
POLYGON_EXPLORER_URL=https://amoy.polygonscan.com       # or https://polygonscan.com
BLOCKCHAIN_NETWORK_NAME=polygon_amoy                     # or polygon_mainnet
```

---

## Timeline: What Consumers See and When

| Time | Production State | Consumer Sees | Verification Available |
|------|-----------------|---------------|----------------------|
| During farming | In progress, events being logged | Gray: "Not Yet Verified" | None |
| Farmer clicks "Finish" | Finalization hash computed | Blue: "Data Sealed" | Layer 1 (event integrity) |
| ~5 seconds later | Celery task submits to blockchain | Purple: "Blockchain Protected" | Layers 1 + 2 + 3 |
| If immediate fails | Finalized but no tx_hash | Blue: "Data Sealed" | Layer 1 only |
| Next month 1st | Batch picks up failed submissions | Purple: "Blockchain Protected" | Layers 1 + 2 + 3 |
| If data tampered | Integrity check fails | Red: "Data Integrity Warning" | All layers detect it |
