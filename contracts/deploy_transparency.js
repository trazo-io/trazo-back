const { ethers } = require("hardhat");
const fs = require("fs");
const path = require("path");

async function main() {
  console.log(
    "Deploying TransparencyVerification contract to Polygon...\n"
  );

  const TransparencyVerification = await ethers.getContractFactory(
    "TransparencyVerification"
  );

  console.log("Deploying contract...");
  const contract = await TransparencyVerification.deploy();
  await contract.waitForDeployment();

  const contractAddress = await contract.getAddress();
  const network = await ethers.provider.getNetwork();
  const tx = contract.deploymentTransaction();

  console.log("TransparencyVerification deployed to:", contractAddress);
  console.log("Network:", network.name, `(chainId: ${network.chainId})`);

  // Save contract details for backend
  const contractInfo = {
    contractName: "TransparencyVerification",
    address: contractAddress,
    network: network.name,
    chainId: Number(network.chainId),
    deployedAt: new Date().toISOString(),
    deployer: tx.from,
    transactionHash: tx.hash,
    abi: JSON.parse(TransparencyVerification.interface.formatJson()),
  };

  // Save to Django backend contracts directory
  const contractsDir = path.join(__dirname, "..", "carbon", "contracts");
  if (!fs.existsSync(contractsDir)) {
    fs.mkdirSync(contractsDir, { recursive: true });
  }

  fs.writeFileSync(
    path.join(contractsDir, "TransparencyVerification.json"),
    JSON.stringify(contractInfo, null, 2)
  );
  console.log(
    "Contract info saved to carbon/contracts/TransparencyVerification.json"
  );

  // Quick smoke test
  console.log("\nTesting contract...");
  try {
    const totalRecords = await contract.totalRecords();
    console.log("totalRecords:", totalRecords.toString());

    const hasRecord = await contract.hasRecord(1);
    console.log("hasRecord(1):", hasRecord);

    console.log("Contract deployed and tested successfully!");
  } catch (error) {
    console.error("Error testing contract:", error.message);
  }

  // Determine explorer URL based on network
  let explorerUrl = "https://polygonscan.com";
  if (Number(network.chainId) === 80002) {
    explorerUrl = "https://amoy.polygonscan.com";
  }

  console.log("\nNext steps:");
  console.log("1. Update CARBON_CONTRACT_ADDRESS in your Django settings:");
  console.log(`   CARBON_CONTRACT_ADDRESS = "${contractAddress}"`);
  console.log(`\n2. View on explorer:`);
  console.log(`   ${explorerUrl}/address/${contractAddress}`);
  console.log(`\n3. Verify on Polygonscan (optional):`);
  console.log(
    `   npx hardhat verify --network ${network.name === "matic" ? "polygon-mainnet" : "polygon-amoy"} ${contractAddress}`
  );
}

main()
  .then(() => process.exit(0))
  .catch((error) => {
    console.error("Deployment failed:", error);
    process.exit(1);
  });
