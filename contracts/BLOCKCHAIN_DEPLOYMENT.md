# Blockchain Deployment Guide

## Overview

Trazo uses the **CarbonVerification** smart contract on Polygon to create immutable records of agricultural carbon data. This document covers deployment across all environments.

## Architecture

```
Environment    Network           Chain ID   Explorer
-----------    -------           --------   --------
Development    Polygon Amoy      80002      amoy.polygonscan.com
Staging        Polygon Amoy      80002      amoy.polygonscan.com
Production     Polygon Mainnet   137        polygonscan.com
```

Each environment gets its own contract deployment and wallet. Never share contracts or keys across environments.

## Prerequisites

- Node.js >= 18
- Python with web3 installed (`poetry install` in trazo-back)
- Testnet MATIC for dev/staging (free from faucet)
- Real MATIC for production

## 1. Development Setup (Local)

### Generate a wallet

```bash
cd trazo-back
poetry run python -c "
from web3 import Web3
account = Web3().eth.account.create()
print(f'Address: {account.address}')
print(f'Private Key: {account.key.hex()}')
"
```

### Get testnet MATIC

Send testnet MATIC to the wallet address above using one of these faucets:

1. **Polygon official**: https://faucet.polygon.technology/ (select Amoy)
2. **Alchemy**: https://www.alchemy.com/faucets/polygon-amoy (requires free account)
3. **Google Cloud**: https://cloud.google.com/application/web3/faucet/ethereum/amoy

You need at least 0.1 MATIC. Deployment costs ~0.002 MATIC.

### Verify funding

```bash
poetry run python -c "
from web3 import Web3
w3 = Web3(Web3.HTTPProvider('https://rpc-amoy.polygon.technology/'))
balance = w3.eth.get_balance('YOUR_WALLET_ADDRESS')
print(f'Balance: {Web3.from_wei(balance, \"ether\")} MATIC')
"
```

### Compile and deploy

```bash
cd trazo-back/contracts
npm install
npx hardhat compile

# Create .env in contracts/ directory
cat > .env << EOF
BLOCKCHAIN_PRIVATE_KEY=your_private_key_here
POLYGON_AMOY_RPC_URL=https://rpc-amoy.polygon.technology/
EOF

# Deploy to Polygon Amoy
npm run deploy:amoy
```

The deploy script outputs the contract address and saves the ABI to `carbon/contracts/CarbonVerification.json`.

### Configure Django .env

Add to `trazo-back/.env`:

```
BLOCKCHAIN_ENABLED=True
POLYGON_RPC_URL=https://rpc-amoy.polygon.technology/
BLOCKCHAIN_PRIVATE_KEY=your_private_key_here
CARBON_CONTRACT_ADDRESS=0x_deployed_contract_address
BLOCKCHAIN_NETWORK_NAME=polygon_amoy
POLYGON_EXPLORER_URL=https://amoy.polygonscan.com
```

### Test the flow

```bash
# Quick test with mock blockchain data
poetry run python manage.py test_blockchain_flow

# Real blockchain submission
poetry run python manage.py submit_to_blockchain
poetry run python manage.py submit_to_blockchain --production-id 99
```

### Verify on Polygonscan

After submission, visit: `https://amoy.polygonscan.com/tx/YOUR_TX_HASH`

### Verify contract source (optional but recommended)

```bash
cd contracts
POLYGONSCAN_API_KEY=your_key npx hardhat verify --network polygon-amoy CONTRACT_ADDRESS
```

## 2. Staging Deployment

Staging uses the same Polygon Amoy testnet but with a separate wallet and contract.

### Deploy contract

Same process as development. Run from CI/CD or manually:

```bash
cd contracts
BLOCKCHAIN_PRIVATE_KEY=staging_key npm run deploy:amoy
```

### Configure AWS Secrets Manager

```bash
aws secretsmanager create-secret \
  --name trazo/staging/blockchain_private_key \
  --secret-string "staging_wallet_private_key" \
  --region us-east-2

aws secretsmanager create-secret \
  --name trazo/staging/carbon_contract_address \
  --secret-string "0x_staging_contract_address" \
  --region us-east-2
```

### ECS Task Definition environment variables

```
BLOCKCHAIN_ENABLED=True
POLYGON_RPC_URL=https://rpc-amoy.polygon.technology/
CARBON_CONTRACT_ADDRESS=arn:aws:secretsmanager:...:trazo/staging/carbon_contract_address
BLOCKCHAIN_PRIVATE_KEY=arn:aws:secretsmanager:...:trazo/staging/blockchain_private_key
BLOCKCHAIN_NETWORK_NAME=polygon_amoy
POLYGON_EXPLORER_URL=https://amoy.polygonscan.com
```

## 3. Production Deployment

Production uses Polygon Mainnet with real MATIC and requires multi-signature authorization.

### Pre-production checklist

- [ ] Contract audited (at minimum: Slither static analysis + manual review)
- [ ] Multi-sig wallet created via [Safe](https://app.safe.global/) (minimum 2-of-3 signers)
- [ ] Production RPC provider configured (Alchemy or Infura, NOT public RPC)
- [ ] Private key stored in AWS KMS (not env var)
- [ ] Gas price limits configured (`BLOCKCHAIN_MAX_GAS_PRICE`)
- [ ] Monitoring alerts set up for failed transactions
- [ ] Contract verified on Polygonscan

### Deploy contract

```bash
# Use a dedicated production RPC (Alchemy recommended)
POLYGON_MAINNET_RPC_URL=https://polygon-mainnet.g.alchemy.com/v2/YOUR_KEY \
BLOCKCHAIN_PRIVATE_KEY=deployer_key \
npm run deploy:mainnet
```

### Verify contract on Polygonscan

```bash
POLYGONSCAN_API_KEY=your_key npx hardhat verify --network polygon-mainnet CONTRACT_ADDRESS
```

### Transfer ownership to multi-sig

After deployment, transfer the contract's admin role to the Safe multi-sig wallet:

```javascript
// In Hardhat console
const contract = await ethers.getContractAt("CarbonVerification", "CONTRACT_ADDRESS");
const ADMIN_ROLE = await contract.DEFAULT_ADMIN_ROLE();
await contract.grantRole(ADMIN_ROLE, "SAFE_MULTISIG_ADDRESS");
await contract.renounceRole(ADMIN_ROLE, "DEPLOYER_ADDRESS");
```

### Configure AWS KMS for private key

```bash
# Create KMS key for blockchain operations
aws kms create-key \
  --description "Trazo production blockchain signing key" \
  --key-usage SIGN_VERIFY \
  --region us-east-2

# Store the signing wallet private key encrypted via KMS
aws secretsmanager create-secret \
  --name trazo/production/blockchain_private_key \
  --secret-string "production_wallet_private_key" \
  --kms-key-id "your-kms-key-id" \
  --region us-east-2
```

### Production environment variables

```
BLOCKCHAIN_ENABLED=True
ENVIRONMENT=production
POLYGON_RPC_URL=https://polygon-mainnet.g.alchemy.com/v2/YOUR_KEY
CARBON_CONTRACT_ADDRESS=0x_production_contract_address
BLOCKCHAIN_PRIVATE_KEY=via_aws_kms
BLOCKCHAIN_NETWORK_NAME=polygon_mainnet
POLYGON_EXPLORER_URL=https://polygonscan.com
BLOCKCHAIN_MAX_GAS_PRICE=100000000000
FORCE_BLOCKCHAIN_VERIFICATION=True
```

## Monthly Batch Task

The Celery task `batch_submit_monthly_summaries` runs on the 1st of each month at 2:00 AM UTC. It:

1. Queries companies with `blockchain_subscription_status=True`
2. Collects CarbonEntry records from the previous month
3. Includes finalization hashes from History records (event integrity chain)
4. Hashes all data with keccak256 (Solidity-compatible)
5. Submits to the smart contract's `recordMonthlySummary()`
6. Stores the tx_hash back on History records for consumer verification

### Manual execution

```bash
# Via Django shell
poetry run python manage.py shell -c "
from carbon.tasks import batch_submit_monthly_summaries
result = batch_submit_monthly_summaries()
print(result)
"

# Or use the management command for a single production
poetry run python manage.py submit_to_blockchain --production-id 99
```

## Integrity Chain

The blockchain verification creates an integrity chain from individual farming events to the on-chain record:

```
Farming Events (planting, irrigation, harvest, etc.)
    |
    v
Finalization Hash (keccak256 of all serialized events)
    |  stored in History.extra_data["finalization_hash"]
    v
Monthly Batch Hash (keccak256 of carbon data + finalization hashes)
    |
    v
Blockchain Transaction (Polygon: recordMonthlySummary)
    |  tx_hash stored in History.extra_data["blockchain_tx_hash"]
    v
Consumer Verification (QR page shows "Blockchain Protected" + explorer link)
```

## Troubleshooting

### "Blockchain not enabled"
Set `BLOCKCHAIN_ENABLED=True` in `.env`

### "No contract address configured"
Deploy the contract and set `CARBON_CONTRACT_ADDRESS` in `.env`

### "Failed to connect to blockchain network"
Check `POLYGON_RPC_URL`. The public Amoy RPC may be rate-limited. Consider using Alchemy (free tier: 300M compute units/month).

### "Insufficient funds"
Wallet needs MATIC for gas. Dev/staging: use faucet. Production: fund from exchange.

### "Transaction reverted"
Check contract state. The wallet may not have the required role. Grant roles via:
```bash
poetry run python manage.py shell -c "
from carbon.services.blockchain import blockchain_service
# Check if wallet has RECORDER_ROLE
print(blockchain_service.contract.functions.hasRole(
    blockchain_service.contract.functions.RECORDER_ROLE().call(),
    blockchain_service.account.address
).call())
"
```

### Gas price too high
Polygon gas spikes occasionally. The `BLOCKCHAIN_MAX_GAS_PRICE` setting (default 100 gwei) prevents overpaying. Increase if transactions fail during congestion.

## Cost Estimates

| Operation | Gas Used | Cost (Amoy) | Cost (Mainnet @ 50 gwei) |
|-----------|----------|-------------|--------------------------|
| Deploy contract | ~2,500,000 | Free (testnet) | ~0.125 MATIC (~$0.06) |
| recordMonthlySummary | ~180,000 | Free (testnet) | ~0.009 MATIC (~$0.004) |
| registerProducer | ~80,000 | Free (testnet) | ~0.004 MATIC (~$0.002) |

At current Polygon prices (~$0.50/MATIC), monthly batch submissions for 100 productions would cost approximately $0.40/month.
