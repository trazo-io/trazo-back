#!/usr/bin/env python3
"""
Deployment script for Trazo multi-signature blockchain contracts.
Deploys and configures multi-signature contracts on Polygon network with comprehensive security.
"""

import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

# Add Django path
sys.path.append(str(Path(__file__).parent.parent))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.settings.prod")

import django

django.setup()

from django.conf import settings

from eth_account import Account
from solcx import compile_source, install_solc
from web3 import Web3

from carbon.services.polygon_security_manager import polygon_security_manager

# Import Trazo services
from carbon.services.secure_key_management import secure_key_manager

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


class MultiSigContractDeployer:
    """
    Comprehensive multi-signature contract deployment and configuration system.

    Features:
    - Secure contract compilation and deployment
    - Multi-signature wallet setup
    - Role-based access control configuration
    - Gas optimization for deployment
    - Comprehensive security validations
    - Deployment verification and testing
    """

    def __init__(self, network: str = "polygon_amoy"):
        self.network = network
        self.web3 = None
        self.account = None
        self.contracts_dir = Path(__file__).parent.parent / "contracts"

        # Deployment configuration
        self.deployment_config = {
            "polygon_amoy": {
                "rpc_url": settings.POLYGON_RPC_URL,
                "chain_id": 80002,
                "explorer_url": "https://amoy.polygonscan.com",
                "gas_price_gwei": 2,
                "max_gas_price_gwei": 50,
            },
            "polygon_mainnet": {
                "rpc_url": getattr(settings, "POLYGON_MAINNET_RPC_URL", ""),
                "chain_id": 137,
                "explorer_url": "https://polygonscan.com",
                "gas_price_gwei": 30,
                "max_gas_price_gwei": 200,
            },
        }

        # Multi-sig configuration
        self.multisig_config = {
            "required_signatures": getattr(settings, "BLOCKCHAIN_REQUIRED_SIGNATURES", 3),
            "max_signers": getattr(settings, "BLOCKCHAIN_MAX_SIGNERS", 7),
            "initial_signers": self._get_initial_signers(),
            "thresholds": {
                "carbon_amount_grams": 1000000,  # 1000 kg
                "credit_amount_grams": 100000,  # 100 kg
                "monetary_value_usd": 50000,  # $50k
                "batch_size": 10,
            },
        }

        self._initialize_web3()

    def _initialize_web3(self):
        """Initialize Web3 connection and account"""
        try:
            config = self.deployment_config[self.network]

            # Initialize Web3
            self.web3 = Web3(Web3.HTTPProvider(config["rpc_url"]))
            if not self.web3.is_connected():
                raise Exception(f"Failed to connect to {self.network}")

            logger.info(f"✅ Connected to {self.network}: {config['rpc_url']}")

            # Load deployment account
            private_key = secure_key_manager.get_blockchain_private_key()
            if not private_key:
                raise Exception("No deployment private key available")

            self.account = Account.from_key(private_key)
            logger.info(f"✅ Deployment account: {self.account.address}")

            # Check account balance
            balance = self.web3.eth.get_balance(self.account.address)
            balance_matic = Web3.from_wei(balance, "ether")
            logger.info(f"💰 Account balance: {balance_matic:.4f} MATIC")

            if balance_matic < 1.0:  # Minimum 1 MATIC for deployment
                logger.warning(f"⚠️  Low balance for deployment: {balance_matic:.4f} MATIC")

        except Exception as e:
            logger.error(f"Web3 initialization failed: {e}")
            raise

    def _get_initial_signers(self) -> List[str]:
        """Get initial multi-sig signers from secure storage"""
        try:
            signers_data = secure_key_manager.get_secret("trazo/blockchain/multisig_signers")

            if signers_data and isinstance(signers_data, dict):
                signers = signers_data.get("signers", [])
                return [signer["address"] for signer in signers if "address" in signer]

            # Development fallback
            logger.warning("Using development signers for deployment")
            return [
                "0x742d35Cc6634C0532925a3b8d1c8b2b8b1f6E8B4",  # Admin
                "0x8ba1f109551bD432803012645Hac136c02142AC8",  # Operator
                "0x5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAed",  # Auditor
            ]

        except Exception as e:
            logger.error(f"Failed to get initial signers: {e}")
            return []

    def compile_contracts(self) -> Dict[str, Any]:
        """Compile multi-signature contracts with optimization"""
        try:
            logger.info("🔨 Compiling multi-signature contracts...")

            # Install specific Solidity version
            solc_version = "0.8.19"
            install_solc(solc_version)

            contracts = {}

            # Compile MultiSigCarbonVerification
            carbon_contract_path = self.contracts_dir / "MultiSigCarbonVerification.sol"
            if carbon_contract_path.exists():
                with open(carbon_contract_path, "r") as f:
                    carbon_source = f.read()

                compiled_carbon = compile_source(
                    carbon_source,
                    output_values=["abi", "bin"],
                    solc_version=solc_version,
                    optimize=True,
                    optimize_runs=200,
                )

                contract_name = list(compiled_carbon.keys())[0]
                contracts["MultiSigCarbonVerification"] = compiled_carbon[contract_name]
                logger.info("✅ Compiled MultiSigCarbonVerification")

            # Compile MultiSigCarbonCreditToken
            token_contract_path = self.contracts_dir / "MultiSigCarbonCreditToken.sol"
            if token_contract_path.exists():
                with open(token_contract_path, "r") as f:
                    token_source = f.read()

                compiled_token = compile_source(
                    token_source,
                    output_values=["abi", "bin"],
                    solc_version=solc_version,
                    optimize=True,
                    optimize_runs=200,
                )

                contract_name = list(compiled_token.keys())[0]
                contracts["MultiSigCarbonCreditToken"] = compiled_token[contract_name]
                logger.info("✅ Compiled MultiSigCarbonCreditToken")

            return contracts

        except Exception as e:
            logger.error(f"Contract compilation failed: {e}")
            raise

    def deploy_multisig_carbon_verification(self, compiled_contracts: Dict[str, Any]) -> str:
        """Deploy MultiSigCarbonVerification contract"""
        try:
            logger.info("🚀 Deploying MultiSigCarbonVerification contract...")

            contract_data = compiled_contracts["MultiSigCarbonVerification"]

            # Get optimized gas parameters
            gas_params = polygon_security_manager.get_optimal_gas_params(
                transaction_type="contract_deploy", priority="high"
            )

            # Create contract instance
            contract = self.web3.eth.contract(abi=contract_data["abi"], bytecode=contract_data["bin"])

            # Prepare constructor arguments
            initial_signers = self.multisig_config["initial_signers"]
            required_signatures = self.multisig_config["required_signatures"]

            if len(initial_signers) < required_signatures:
                raise Exception(f"Insufficient initial signers: {len(initial_signers)} < {required_signatures}")

            # Build deployment transaction
            constructor_tx = contract.constructor(initial_signers, required_signatures).buildTransaction(
                {
                    "from": self.account.address,
                    "gas": gas_params["gasLimit"],
                    "maxFeePerGas": gas_params["maxFeePerGas"],
                    "maxPriorityFeePerGas": gas_params["maxPriorityFeePerGas"],
                    "nonce": self.web3.eth.get_transaction_count(self.account.address),
                    "chainId": self.deployment_config[self.network]["chain_id"],
                }
            )

            # Sign and send transaction
            signed_tx = self.web3.eth.account.sign_transaction(constructor_tx, self.account.private_key)
            tx_hash = self.web3.eth.send_raw_transaction(signed_tx.rawTransaction)

            logger.info(f"⏳ Transaction sent: {tx_hash.hex()}")

            # Wait for confirmation
            receipt = self.web3.eth.wait_for_transaction_receipt(tx_hash, timeout=300)

            if receipt["status"] != 1:
                raise Exception("Contract deployment failed")

            contract_address = receipt["contractAddress"]
            logger.info(f"✅ MultiSigCarbonVerification deployed: {contract_address}")
            logger.info(
                f"🔍 Explorer: {self.deployment_config[self.network]['explorer_url']}/address/{contract_address}"
            )

            # Save deployment info
            self._save_deployment_info(
                "MultiSigCarbonVerification",
                {
                    "address": contract_address,
                    "tx_hash": tx_hash.hex(),
                    "block_number": receipt["blockNumber"],
                    "gas_used": receipt["gasUsed"],
                    "abi": contract_data["abi"],
                },
            )

            return contract_address

        except Exception as e:
            logger.error(f"MultiSigCarbonVerification deployment failed: {e}")
            raise

    def deploy_multisig_carbon_credit_token(self, compiled_contracts: Dict[str, Any]) -> str:
        """Deploy MultiSigCarbonCreditToken contract"""
        try:
            logger.info("🚀 Deploying MultiSigCarbonCreditToken contract...")

            contract_data = compiled_contracts["MultiSigCarbonCreditToken"]

            # Get optimized gas parameters
            gas_params = polygon_security_manager.get_optimal_gas_params(
                transaction_type="contract_deploy", priority="high"
            )

            # Create contract instance
            contract = self.web3.eth.contract(abi=contract_data["abi"], bytecode=contract_data["bin"])

            # Prepare constructor arguments
            initial_signers = self.multisig_config["initial_signers"]
            required_signatures = self.multisig_config["required_signatures"]

            # Build deployment transaction
            constructor_tx = contract.constructor(initial_signers, required_signatures).buildTransaction(
                {
                    "from": self.account.address,
                    "gas": gas_params["gasLimit"],
                    "maxFeePerGas": gas_params["maxFeePerGas"],
                    "maxPriorityFeePerGas": gas_params["maxPriorityFeePerGas"],
                    "nonce": self.web3.eth.get_transaction_count(self.account.address),
                    "chainId": self.deployment_config[self.network]["chain_id"],
                }
            )

            # Sign and send transaction
            signed_tx = self.web3.eth.account.sign_transaction(constructor_tx, self.account.private_key)
            tx_hash = self.web3.eth.send_raw_transaction(signed_tx.rawTransaction)

            logger.info(f"⏳ Transaction sent: {tx_hash.hex()}")

            # Wait for confirmation
            receipt = self.web3.eth.wait_for_transaction_receipt(tx_hash, timeout=300)

            if receipt["status"] != 1:
                raise Exception("Contract deployment failed")

            contract_address = receipt["contractAddress"]
            logger.info(f"✅ MultiSigCarbonCreditToken deployed: {contract_address}")
            logger.info(
                f"🔍 Explorer: {self.deployment_config[self.network]['explorer_url']}/address/{contract_address}"
            )

            # Save deployment info
            self._save_deployment_info(
                "MultiSigCarbonCreditToken",
                {
                    "address": contract_address,
                    "tx_hash": tx_hash.hex(),
                    "block_number": receipt["blockNumber"],
                    "gas_used": receipt["gasUsed"],
                    "abi": contract_data["abi"],
                },
            )

            return contract_address

        except Exception as e:
            logger.error(f"MultiSigCarbonCreditToken deployment failed: {e}")
            raise

    def configure_contracts(self, carbon_address: str, token_address: str):
        """Configure deployed contracts with proper permissions and thresholds"""
        try:
            logger.info("⚙️  Configuring multi-signature contracts...")

            # Configure carbon verification contract
            self._configure_carbon_contract(carbon_address)

            # Configure token contract
            self._configure_token_contract(token_address)

            logger.info("✅ Contract configuration completed")

        except Exception as e:
            logger.error(f"Contract configuration failed: {e}")
            raise

    def _configure_carbon_contract(self, contract_address: str):
        """Configure MultiSigCarbonVerification contract"""
        try:
            logger.info(f"⚙️  Configuring carbon contract: {contract_address}")

            # Load contract ABI
            deployment_info = self._load_deployment_info("MultiSigCarbonVerification")
            contract = self.web3.eth.contract(address=contract_address, abi=deployment_info["abi"])

            # Configure thresholds if needed
            thresholds = self.multisig_config["thresholds"]

            # Create proposal to update thresholds
            config_data = self.web3.eth.abi.encode(
                ["uint8", "uint256[]"],
                [
                    self.multisig_config["required_signatures"],
                    [
                        thresholds["carbon_amount_grams"],
                        thresholds["credit_amount_grams"],
                        thresholds["monetary_value_usd"],
                    ],
                ],
            )

            logger.info("✅ Carbon contract configuration prepared")

        except Exception as e:
            logger.error(f"Carbon contract configuration failed: {e}")
            raise

    def _configure_token_contract(self, contract_address: str):
        """Configure MultiSigCarbonCreditToken contract"""
        try:
            logger.info(f"⚙️  Configuring token contract: {contract_address}")

            # Load contract ABI
            deployment_info = self._load_deployment_info("MultiSigCarbonCreditToken")
            contract = self.web3.eth.contract(address=contract_address, abi=deployment_info["abi"])

            # Configure multi-sig thresholds
            thresholds = self.multisig_config["thresholds"]

            # Get optimized gas parameters
            gas_params = polygon_security_manager.get_optimal_gas_params(transaction_type="complex", priority="normal")

            # Update multi-sig configuration
            update_tx = contract.functions.updateMultiSigConfig(
                self.multisig_config["required_signatures"],
                thresholds["credit_amount_grams"],
                thresholds["monetary_value_usd"],
                thresholds["batch_size"],
            ).buildTransaction(
                {
                    "from": self.account.address,
                    "gas": gas_params["gasLimit"],
                    "maxFeePerGas": gas_params["maxFeePerGas"],
                    "maxPriorityFeePerGas": gas_params["maxPriorityFeePerGas"],
                    "nonce": self.web3.eth.get_transaction_count(self.account.address),
                    "chainId": self.deployment_config[self.network]["chain_id"],
                }
            )

            # Sign and send
            signed_tx = self.web3.eth.account.sign_transaction(update_tx, self.account.private_key)
            tx_hash = self.web3.eth.send_raw_transaction(signed_tx.rawTransaction)

            # Wait for confirmation
            receipt = self.web3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)

            if receipt["status"] == 1:
                logger.info("✅ Token contract thresholds updated")
            else:
                logger.error("❌ Token contract configuration failed")

        except Exception as e:
            logger.error(f"Token contract configuration failed: {e}")
            # Don't raise - configuration can be done later

    def verify_deployment(self, carbon_address: str, token_address: str) -> bool:
        """Verify contract deployment and configuration"""
        try:
            logger.info("🔍 Verifying contract deployment...")

            # Verify carbon contract
            carbon_verified = self._verify_carbon_contract(carbon_address)

            # Verify token contract
            token_verified = self._verify_token_contract(token_address)

            if carbon_verified and token_verified:
                logger.info("✅ All contracts verified successfully")
                return True
            else:
                logger.error("❌ Contract verification failed")
                return False

        except Exception as e:
            logger.error(f"Contract verification failed: {e}")
            return False

    def _verify_carbon_contract(self, contract_address: str) -> bool:
        """Verify MultiSigCarbonVerification contract"""
        try:
            deployment_info = self._load_deployment_info("MultiSigCarbonVerification")
            contract = self.web3.eth.contract(address=contract_address, abi=deployment_info["abi"])

            # Check basic configuration
            required_sigs = contract.functions.requiredSignatures().call()
            signers = contract.functions.getAuthorizedSigners().call()

            logger.info(f"Carbon Contract - Required signatures: {required_sigs}")
            logger.info(f"Carbon Contract - Authorized signers: {len(signers)}")

            # Verify configuration
            if required_sigs != self.multisig_config["required_signatures"]:
                logger.error(f"Incorrect required signatures: {required_sigs}")
                return False

            if len(signers) < required_sigs:
                logger.error(f"Insufficient signers: {len(signers)} < {required_sigs}")
                return False

            return True

        except Exception as e:
            logger.error(f"Carbon contract verification failed: {e}")
            return False

    def _verify_token_contract(self, contract_address: str) -> bool:
        """Verify MultiSigCarbonCreditToken contract"""
        try:
            deployment_info = self._load_deployment_info("MultiSigCarbonCreditToken")
            contract = self.web3.eth.contract(address=contract_address, abi=deployment_info["abi"])

            # Check basic configuration
            required_sigs = contract.functions.requiredSignatures().call()
            signers = contract.functions.getAuthorizedSigners().call()

            logger.info(f"Token Contract - Required signatures: {required_sigs}")
            logger.info(f"Token Contract - Authorized signers: {len(signers)}")

            # Check contract name and symbol
            name = contract.functions.name().call()
            symbol = contract.functions.symbol().call()

            logger.info(f"Token Contract - Name: {name}, Symbol: {symbol}")

            # Verify configuration
            if required_sigs != self.multisig_config["required_signatures"]:
                logger.error(f"Incorrect required signatures: {required_sigs}")
                return False

            if len(signers) < required_sigs:
                logger.error(f"Insufficient signers: {len(signers)} < {required_sigs}")
                return False

            return True

        except Exception as e:
            logger.error(f"Token contract verification failed: {e}")
            return False

    def _save_deployment_info(self, contract_name: str, info: Dict[str, Any]):
        """Save contract deployment information"""
        try:
            deployment_data = {
                "network": self.network,
                "deployed_at": time.time(),
                "deployer": self.account.address,
                **info,
            }

            # Save to secure storage
            secret_key = f"trazo/contracts/{self.network}/{contract_name.lower()}"
            secure_key_manager.store_secret(
                secret_key, deployment_data, f"{contract_name} deployment info for {self.network}"
            )

            # Also save locally for immediate use
            local_file = self.contracts_dir / f"{contract_name}_{self.network}.json"
            with open(local_file, "w") as f:
                json.dump(deployment_data, f, indent=2)

            logger.info(f"💾 Saved deployment info: {secret_key}")

        except Exception as e:
            logger.error(f"Failed to save deployment info: {e}")

    def _load_deployment_info(self, contract_name: str) -> Dict[str, Any]:
        """Load contract deployment information"""
        try:
            # Try secure storage first
            secret_key = f"trazo/contracts/{self.network}/{contract_name.lower()}"
            deployment_data = secure_key_manager.get_secret(secret_key)

            if deployment_data:
                return deployment_data

            # Fallback to local file
            local_file = self.contracts_dir / f"{contract_name}_{self.network}.json"
            if local_file.exists():
                with open(local_file, "r") as f:
                    return json.load(f)

            raise Exception(f"No deployment info found for {contract_name}")

        except Exception as e:
            logger.error(f"Failed to load deployment info: {e}")
            raise

    def deploy_all(self) -> Dict[str, str]:
        """Deploy all multi-signature contracts"""
        try:
            logger.info("🚀 Starting multi-signature contract deployment...")

            # Step 1: Compile contracts
            compiled_contracts = self.compile_contracts()

            # Step 2: Deploy carbon verification contract
            carbon_address = self.deploy_multisig_carbon_verification(compiled_contracts)

            # Step 3: Deploy token contract
            token_address = self.deploy_multisig_carbon_credit_token(compiled_contracts)

            # Step 4: Configure contracts
            self.configure_contracts(carbon_address, token_address)

            # Step 5: Verify deployment
            if self.verify_deployment(carbon_address, token_address):
                logger.info("🎉 Multi-signature deployment completed successfully!")

                deployment_summary = {
                    "carbon_verification_address": carbon_address,
                    "carbon_credit_token_address": token_address,
                    "network": self.network,
                    "required_signatures": self.multisig_config["required_signatures"],
                    "authorized_signers_count": len(self.multisig_config["initial_signers"]),
                }

                # Save summary
                secure_key_manager.store_secret(
                    f"trazo/deployment/{self.network}/summary",
                    deployment_summary,
                    f"Deployment summary for {self.network}",
                )

                return deployment_summary
            else:
                raise Exception("Deployment verification failed")

        except Exception as e:
            logger.error(f"Multi-signature deployment failed: {e}")
            raise


def main():
    """Main deployment function"""
    import argparse

    parser = argparse.ArgumentParser(description="Deploy Trazo multi-signature contracts")
    parser.add_argument(
        "--network", choices=["polygon_amoy", "polygon_mainnet"], default="polygon_amoy", help="Network to deploy to"
    )
    parser.add_argument("--verify-only", action="store_true", help="Only verify existing deployment")

    args = parser.parse_args()

    try:
        deployer = MultiSigContractDeployer(args.network)

        if args.verify_only:
            # Load existing addresses and verify
            carbon_info = deployer._load_deployment_info("MultiSigCarbonVerification")
            token_info = deployer._load_deployment_info("MultiSigCarbonCreditToken")

            success = deployer.verify_deployment(carbon_info["address"], token_info["address"])

            if success:
                logger.info("✅ Verification completed successfully")
            else:
                logger.error("❌ Verification failed")
                sys.exit(1)
        else:
            # Full deployment
            deployment_summary = deployer.deploy_all()

            print("\n" + "=" * 60)
            print("🎉 DEPLOYMENT COMPLETED SUCCESSFULLY!")
            print("=" * 60)
            print(f"Network: {deployment_summary['network']}")
            print(f"Carbon Verification: {deployment_summary['carbon_verification_address']}")
            print(f"Carbon Credit Token: {deployment_summary['carbon_credit_token_address']}")
            print(f"Required Signatures: {deployment_summary['required_signatures']}")
            print(f"Authorized Signers: {deployment_summary['authorized_signers_count']}")
            print("=" * 60)

    except Exception as e:
        logger.error(f"Deployment failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
