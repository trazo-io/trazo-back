// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

import "@openzeppelin/contracts/access/AccessControl.sol";
import "@openzeppelin/contracts/security/Pausable.sol";

/**
 * @title TransparencyVerification
 * @dev Minimal smart contract for Trazo's production data integrity verification.
 *
 * Purpose: Store a tamper-proof fingerprint (hash) of production data so consumers
 * can verify that the data hasn't been altered after submission.
 *
 * What this contract does:
 *   - Stores a keccak256 hash per production ID
 *   - Records when it was submitted (block timestamp)
 *   - Allows anyone to verify a hash matches what's on-chain
 *
 * What this contract does NOT do (by design):
 *   - Store carbon emissions, offsets, or crop data (redundant — verifiable from hash)
 *   - Register producers (tracked in Trazo's database)
 *   - Issue carbon credits (not part of Trazo's product)
 *   - Check USDA compliance (Trazo's own assessment, not independent verification)
 */
contract TransparencyVerification is AccessControl, Pausable {
    bytes32 public constant SUBMITTER_ROLE = keccak256("SUBMITTER_ROLE");

    struct Record {
        bytes32 dataHash;
        uint256 timestamp;
    }

    // productionId => Record
    mapping(uint256 => Record) public records;

    // Prevent the same hash from being submitted twice
    mapping(bytes32 => bool) public usedHashes;

    uint256 public totalRecords;

    event ProductionRecorded(
        uint256 indexed productionId,
        bytes32 dataHash,
        uint256 timestamp
    );

    constructor() {
        _grantRole(DEFAULT_ADMIN_ROLE, msg.sender);
        _grantRole(SUBMITTER_ROLE, msg.sender);
    }

    /**
     * @dev Record a production's data hash on-chain.
     * @param productionId The Trazo production ID
     * @param dataHash Keccak256 hash of the production data
     */
    function recordProduction(
        uint256 productionId,
        bytes32 dataHash
    ) external onlyRole(SUBMITTER_ROLE) whenNotPaused {
        require(records[productionId].timestamp == 0, "Production already recorded");
        require(!usedHashes[dataHash], "Hash already used");
        require(dataHash != bytes32(0), "Empty hash");

        records[productionId] = Record({
            dataHash: dataHash,
            timestamp: block.timestamp
        });

        usedHashes[dataHash] = true;
        totalRecords++;

        emit ProductionRecorded(productionId, dataHash, block.timestamp);
    }

    /**
     * @dev Get the stored record for a production.
     * @param productionId The Trazo production ID
     * @return dataHash The stored hash
     * @return timestamp When it was recorded (0 if not found)
     */
    function getRecord(uint256 productionId) external view returns (
        bytes32 dataHash,
        uint256 timestamp
    ) {
        Record memory r = records[productionId];
        return (r.dataHash, r.timestamp);
    }

    /**
     * @dev Verify that a hash matches what's stored on-chain for a production.
     * @param productionId The Trazo production ID
     * @param hash The hash to verify against
     * @return matches True if the hash matches the stored record
     */
    function verifyHash(
        uint256 productionId,
        bytes32 hash
    ) external view returns (bool matches) {
        Record memory r = records[productionId];
        require(r.timestamp > 0, "No record for this production");
        return r.dataHash == hash;
    }

    /**
     * @dev Check if a production has been recorded.
     * @param productionId The Trazo production ID
     * @return exists True if a record exists
     */
    function hasRecord(uint256 productionId) external view returns (bool exists) {
        return records[productionId].timestamp > 0;
    }

    // --- Admin functions ---

    function pause() external onlyRole(DEFAULT_ADMIN_ROLE) {
        _pause();
    }

    function unpause() external onlyRole(DEFAULT_ADMIN_ROLE) {
        _unpause();
    }
}
