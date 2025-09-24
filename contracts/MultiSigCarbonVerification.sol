// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

import "@openzeppelin/contracts/access/AccessControl.sol";
import "@openzeppelin/contracts/security/Pausable.sol";
import "@openzeppelin/contracts/security/ReentrancyGuard.sol";
import "@openzeppelin/contracts/utils/cryptography/ECDSA.sol";
import "@openzeppelin/contracts/utils/cryptography/MessageHashUtils.sol";

/**
 * @title MultiSigCarbonVerification
 * @dev Enhanced carbon verification with multi-signature requirements for critical operations
 * Implements production-grade security patterns for Trazo's carbon transparency platform
 */
contract MultiSigCarbonVerification is AccessControl, Pausable, ReentrancyGuard {
    using ECDSA for bytes32;
    using MessageHashUtils for bytes32;

    bytes32 public constant VERIFIER_ROLE = keccak256("VERIFIER_ROLE");
    bytes32 public constant AUDITOR_ROLE = keccak256("AUDITOR_ROLE");
    bytes32 public constant MULTISIG_SIGNER_ROLE = keccak256("MULTISIG_SIGNER_ROLE");
    bytes32 public constant EMERGENCY_ROLE = keccak256("EMERGENCY_ROLE");

    // Multi-signature configuration
    uint8 public requiredSignatures;
    uint8 public maxSigners;
    mapping(address => bool) public isAuthorizedSigner;
    address[] public authorizedSigners;

    // USDA compliance thresholds (in grams CO2e per kg of product)
    uint256 public constant USDA_CITRUS_THRESHOLD = 2000;
    uint256 public constant USDA_ALMOND_THRESHOLD = 2100;
    uint256 public constant USDA_SOYBEAN_THRESHOLD = 400;
    uint256 public constant USDA_GENERAL_THRESHOLD = 1000;

    // Multi-sig thresholds for automatic requirements
    uint256 public multisigCarbonThreshold = 1000000; // 1000 kg CO2e in grams
    uint256 public multisigCreditsThreshold = 100000; // 100 credits in grams
    uint256 public multisigValueThreshold = 10000; // $10,000 USD

    struct CarbonRecord {
        bytes32 dataHash;
        uint256 producerId;
        uint256 productionId;
        uint256 totalEmissions;
        uint256 totalOffsets;
        int256 netFootprint;
        uint256 entryCount;
        string cropType;
        uint256 timestamp;
        bool usdaCompliant;
        bool creditsIssued;
        uint256 creditsAmount;
        bool requiresMultisig;
        bytes32 approvalHash;
    }

    struct Producer {
        address walletAddress;
        bool isActive;
        uint256 totalCredits;
        uint256 recordCount;
        uint256 joinDate;
        bool isVerified;
        uint8 riskLevel; // 0=low, 1=medium, 2=high
    }

    struct MultiSigProposal {
        bytes32 proposalId;
        address proposer;
        bytes32 operationHash;
        uint8 operationType; // 0=record, 1=credits, 2=emergency, 3=config
        bytes data;
        uint256 deadline;
        uint8 signaturesCount;
        bool executed;
        bool cancelled;
        mapping(address => bool) hasSigned;
        address[] signers;
    }

    // Storage
    mapping(uint256 => CarbonRecord) public carbonRecords;
    mapping(uint256 => Producer) public producers;
    mapping(uint256 => uint256[]) public producerRecords;
    mapping(bytes32 => bool) public usedHashes;
    mapping(bytes32 => MultiSigProposal) public proposals;
    
    uint256 public totalRecords;
    uint256 public totalCreditsIssued;
    uint256 public totalProducers;
    uint256 public proposalNonce;

    // Events
    event MonthlySummaryRecorded(
        uint256 indexed productionId,
        uint256 indexed producerId,
        bytes32 dataHash,
        int256 netFootprint,
        bool usdaCompliant,
        bool requiresMultisig
    );

    event ComplianceVerified(
        uint256 indexed productionId,
        bool compliant,
        string cropType,
        uint256 threshold
    );

    event CreditsIssued(
        uint256 indexed productionId,
        uint256 indexed producerId,
        uint256 creditsAmount
    );

    event ProducerRegistered(
        uint256 indexed producerId,
        address indexed walletAddress,
        uint8 riskLevel
    );

    event MultiSigProposalCreated(
        bytes32 indexed proposalId,
        address indexed proposer,
        uint8 operationType,
        uint256 deadline
    );

    event MultiSigProposalSigned(
        bytes32 indexed proposalId,
        address indexed signer,
        uint8 signaturesCount
    );

    event MultiSigProposalExecuted(
        bytes32 indexed proposalId,
        uint8 operationType
    );

    event MultiSigProposalCancelled(
        bytes32 indexed proposalId,
        address indexed canceller
    );

    event MultiSigSignerAdded(address indexed signer);
    event MultiSigSignerRemoved(address indexed signer);
    event MultiSigConfigUpdated(uint8 requiredSignatures, uint8 maxSigners);

    constructor(
        address[] memory _initialSigners,
        uint8 _requiredSignatures
    ) {
        require(_initialSigners.length >= _requiredSignatures, "Insufficient initial signers");
        require(_requiredSignatures >= 2, "Minimum 2 signatures required");
        require(_initialSigners.length <= 10, "Maximum 10 signers allowed");

        _grantRole(DEFAULT_ADMIN_ROLE, msg.sender);
        _grantRole(VERIFIER_ROLE, msg.sender);
        _grantRole(AUDITOR_ROLE, msg.sender);
        _grantRole(EMERGENCY_ROLE, msg.sender);

        // Initialize multi-sig configuration
        requiredSignatures = _requiredSignatures;
        maxSigners = uint8(_initialSigners.length);

        for (uint i = 0; i < _initialSigners.length; i++) {
            require(_initialSigners[i] != address(0), "Invalid signer address");
            require(!isAuthorizedSigner[_initialSigners[i]], "Duplicate signer");
            
            isAuthorizedSigner[_initialSigners[i]] = true;
            authorizedSigners.push(_initialSigners[i]);
            _grantRole(MULTISIG_SIGNER_ROLE, _initialSigners[i]);
            
            emit MultiSigSignerAdded(_initialSigners[i]);
        }

        emit MultiSigConfigUpdated(requiredSignatures, maxSigners);
    }

    modifier onlyAuthorizedSigner() {
        require(isAuthorizedSigner[msg.sender], "Not an authorized signer");
        _;
    }

    modifier onlyMultiSig() {
        require(hasRole(MULTISIG_SIGNER_ROLE, msg.sender), "Multi-sig authorization required");
        _;
    }

    /**
     * @dev Check if operation requires multi-signature approval
     */
    function requiresMultiSigApproval(
        uint8 operationType,
        uint256 carbonAmount,
        uint256 creditsAmount,
        uint256 valueUsd
    ) public view returns (bool) {
        // Always require multi-sig for emergency operations
        if (operationType == 2 || operationType == 3) {
            return true;
        }

        // Check thresholds for carbon records and credits
        if (operationType == 0 && carbonAmount >= multisigCarbonThreshold) {
            return true;
        }

        if (operationType == 1 && creditsAmount >= multisigCreditsThreshold) {
            return true;
        }

        // Check value threshold
        if (valueUsd >= multisigValueThreshold) {
            return true;
        }

        return false;
    }

    /**
     * @dev Create a multi-signature proposal for critical operations
     */
    function createMultiSigProposal(
        uint8 operationType,
        bytes calldata data,
        uint256 deadline
    ) external onlyRole(VERIFIER_ROLE) returns (bytes32) {
        require(deadline > block.timestamp, "Invalid deadline");
        require(deadline <= block.timestamp + 7 days, "Deadline too far");

        bytes32 proposalId = keccak256(abi.encodePacked(
            msg.sender,
            operationType,
            data,
            block.timestamp,
            proposalNonce++
        ));

        require(proposals[proposalId].proposalId == 0, "Proposal already exists");

        MultiSigProposal storage proposal = proposals[proposalId];
        proposal.proposalId = proposalId;
        proposal.proposer = msg.sender;
        proposal.operationType = operationType;
        proposal.data = data;
        proposal.deadline = deadline;
        proposal.operationHash = keccak256(data);

        emit MultiSigProposalCreated(proposalId, msg.sender, operationType, deadline);

        return proposalId;
    }

    /**
     * @dev Sign a multi-signature proposal
     */
    function signProposal(bytes32 proposalId) external onlyAuthorizedSigner {
        MultiSigProposal storage proposal = proposals[proposalId];
        
        require(proposal.proposalId != 0, "Proposal does not exist");
        require(!proposal.executed, "Proposal already executed");
        require(!proposal.cancelled, "Proposal cancelled");
        require(block.timestamp <= proposal.deadline, "Proposal expired");
        require(!proposal.hasSigned[msg.sender], "Already signed");

        proposal.hasSigned[msg.sender] = true;
        proposal.signers.push(msg.sender);
        proposal.signaturesCount++;

        emit MultiSigProposalSigned(proposalId, msg.sender, proposal.signaturesCount);

        // Auto-execute if enough signatures
        if (proposal.signaturesCount >= requiredSignatures) {
            _executeProposal(proposalId);
        }
    }

    /**
     * @dev Execute a multi-signature proposal with sufficient signatures
     */
    function executeProposal(bytes32 proposalId) external onlyAuthorizedSigner {
        MultiSigProposal storage proposal = proposals[proposalId];
        
        require(proposal.proposalId != 0, "Proposal does not exist");
        require(!proposal.executed, "Proposal already executed");
        require(!proposal.cancelled, "Proposal cancelled");
        require(proposal.signaturesCount >= requiredSignatures, "Insufficient signatures");
        require(block.timestamp <= proposal.deadline, "Proposal expired");

        _executeProposal(proposalId);
    }

    /**
     * @dev Internal function to execute proposal based on operation type
     */
    function _executeProposal(bytes32 proposalId) internal {
        MultiSigProposal storage proposal = proposals[proposalId];
        proposal.executed = true;

        if (proposal.operationType == 0) {
            // Carbon record operation
            _executeRecordOperation(proposal.data);
        } else if (proposal.operationType == 1) {
            // Credits issuance operation
            _executeCreditsOperation(proposal.data);
        } else if (proposal.operationType == 2) {
            // Emergency operation
            _executeEmergencyOperation(proposal.data);
        } else if (proposal.operationType == 3) {
            // Configuration update operation
            _executeConfigOperation(proposal.data);
        }

        emit MultiSigProposalExecuted(proposalId, proposal.operationType);
    }

    /**
     * @dev Execute carbon record operation
     */
    function _executeRecordOperation(bytes memory data) internal {
        (
            bytes32 dataHash,
            uint256 producerId,
            uint256 productionId,
            uint256 totalEmissions,
            uint256 totalOffsets,
            string memory cropType
        ) = abi.decode(data, (bytes32, uint256, uint256, uint256, uint256, string));

        _recordMonthlySummaryInternal(
            dataHash,
            producerId,
            productionId,
            totalEmissions,
            totalOffsets,
            cropType,
            true // requiresMultisig = true
        );
    }

    /**
     * @dev Execute credits issuance operation
     */
    function _executeCreditsOperation(bytes memory data) internal {
        (uint256 productionId, uint256 creditsAmount) = abi.decode(data, (uint256, uint256));
        _issueCreditsInternal(productionId, creditsAmount);
    }

    /**
     * @dev Execute emergency operation
     */
    function _executeEmergencyOperation(bytes memory data) internal {
        (uint8 emergencyType) = abi.decode(data, (uint8));
        
        if (emergencyType == 0) {
            // Emergency pause
            _pause();
        } else if (emergencyType == 1) {
            // Emergency unpause
            _unpause();
        }
    }

    /**
     * @dev Execute configuration update operation
     */
    function _executeConfigOperation(bytes memory data) internal {
        (uint8 newRequiredSignatures, uint256[] memory thresholds) = abi.decode(data, (uint8, uint256[]));
        
        require(newRequiredSignatures >= 2, "Minimum 2 signatures required");
        require(newRequiredSignatures <= authorizedSigners.length, "Cannot require more signatures than signers");
        
        requiredSignatures = newRequiredSignatures;
        
        if (thresholds.length >= 3) {
            multisigCarbonThreshold = thresholds[0];
            multisigCreditsThreshold = thresholds[1];
            multisigValueThreshold = thresholds[2];
        }

        emit MultiSigConfigUpdated(requiredSignatures, maxSigners);
    }

    /**
     * @dev Register a new producer with enhanced security
     */
    function registerProducer(
        uint256 producerId,
        address walletAddress,
        uint8 riskLevel
    ) external onlyRole(VERIFIER_ROLE) {
        require(producers[producerId].walletAddress == address(0), "Producer already registered");
        require(walletAddress != address(0), "Invalid wallet address");
        require(riskLevel <= 2, "Invalid risk level");

        producers[producerId] = Producer({
            walletAddress: walletAddress,
            isActive: true,
            totalCredits: 0,
            recordCount: 0,
            joinDate: block.timestamp,
            isVerified: riskLevel == 0, // Auto-verify low-risk producers
            riskLevel: riskLevel
        });

        totalProducers++;
        emit ProducerRegistered(producerId, walletAddress, riskLevel);
    }

    /**
     * @dev Record monthly carbon summary with automatic multi-sig detection
     */
    function recordMonthlySummary(
        bytes32 dataHash,
        uint256 producerId,
        uint256 productionId,
        uint256 totalEmissions,
        uint256 totalOffsets,
        string calldata cropType
    ) external onlyRole(VERIFIER_ROLE) whenNotPaused nonReentrant {
        uint256 totalCarbon = totalEmissions + totalOffsets;
        bool needsMultiSig = requiresMultiSigApproval(0, totalCarbon, 0, 0);

        if (needsMultiSig) {
            // Create multi-sig proposal
            bytes memory proposalData = abi.encode(
                dataHash,
                producerId,
                productionId,
                totalEmissions,
                totalOffsets,
                cropType
            );

            createMultiSigProposal(0, proposalData, block.timestamp + 24 hours);
            return;
        }

        _recordMonthlySummaryInternal(
            dataHash,
            producerId,
            productionId,
            totalEmissions,
            totalOffsets,
            cropType,
            false
        );
    }

    /**
     * @dev Internal function to record monthly summary
     */
    function _recordMonthlySummaryInternal(
        bytes32 dataHash,
        uint256 producerId,
        uint256 productionId,
        uint256 totalEmissions,
        uint256 totalOffsets,
        string memory cropType,
        bool requiresMultisig
    ) internal {
        require(!usedHashes[dataHash], "Data hash already used");
        require(producers[producerId].isActive, "Producer not active");
        require(bytes(cropType).length > 0, "Invalid crop type");
        require(carbonRecords[productionId].timestamp == 0, "Record already exists");

        int256 netFootprint = int256(totalEmissions) - int256(totalOffsets);
        bool usdaCompliant = _checkUsdaCompliance(cropType, uint256(netFootprint));

        carbonRecords[productionId] = CarbonRecord({
            dataHash: dataHash,
            producerId: producerId,
            productionId: productionId,
            totalEmissions: totalEmissions,
            totalOffsets: totalOffsets,
            netFootprint: netFootprint,
            entryCount: 0,
            cropType: cropType,
            timestamp: block.timestamp,
            usdaCompliant: usdaCompliant,
            creditsIssued: false,
            creditsAmount: 0,
            requiresMultisig: requiresMultisig,
            approvalHash: requiresMultisig ? keccak256(abi.encodePacked(msg.sender, block.timestamp)) : bytes32(0)
        });

        producerRecords[producerId].push(productionId);
        producers[producerId].recordCount++;
        usedHashes[dataHash] = true;
        totalRecords++;

        emit MonthlySummaryRecorded(productionId, producerId, dataHash, netFootprint, usdaCompliant, requiresMultisig);
        emit ComplianceVerified(productionId, usdaCompliant, cropType, _getThresholdForCrop(cropType));

        if (netFootprint < 0 && usdaCompliant && !requiresMultisig) {
            _issueCreditsInternal(productionId, uint256(-netFootprint));
        }
    }

    /**
     * @dev Issue carbon credits with multi-sig protection
     */
    function issueCredits(
        uint256 productionId,
        uint256 creditsAmount
    ) external onlyRole(VERIFIER_ROLE) whenNotPaused {
        CarbonRecord storage record = carbonRecords[productionId];
        require(record.timestamp > 0, "Record does not exist");
        require(record.usdaCompliant, "Not USDA compliant");
        require(record.netFootprint < 0, "Not carbon negative");
        require(!record.creditsIssued, "Credits already issued");

        bool needsMultiSig = requiresMultiSigApproval(1, 0, creditsAmount, 0);

        if (needsMultiSig) {
            bytes memory proposalData = abi.encode(productionId, creditsAmount);
            createMultiSigProposal(1, proposalData, block.timestamp + 24 hours);
            return;
        }

        _issueCreditsInternal(productionId, creditsAmount);
    }

    /**
     * @dev Internal function to issue credits
     */
    function _issueCreditsInternal(uint256 productionId, uint256 creditsAmount) internal {
        CarbonRecord storage record = carbonRecords[productionId];
        Producer storage producer = producers[record.producerId];

        record.creditsIssued = true;
        record.creditsAmount = creditsAmount;
        producer.totalCredits += creditsAmount;
        totalCreditsIssued += creditsAmount;

        emit CreditsIssued(productionId, record.producerId, creditsAmount);
    }

    /**
     * @dev Add a new multi-sig signer
     */
    function addMultiSigSigner(address newSigner) external onlyRole(DEFAULT_ADMIN_ROLE) {
        require(newSigner != address(0), "Invalid signer address");
        require(!isAuthorizedSigner[newSigner], "Already a signer");
        require(authorizedSigners.length < maxSigners, "Maximum signers reached");

        isAuthorizedSigner[newSigner] = true;
        authorizedSigners.push(newSigner);
        _grantRole(MULTISIG_SIGNER_ROLE, newSigner);

        emit MultiSigSignerAdded(newSigner);
    }

    /**
     * @dev Remove a multi-sig signer
     */
    function removeMultiSigSigner(address signer) external onlyRole(DEFAULT_ADMIN_ROLE) {
        require(isAuthorizedSigner[signer], "Not a signer");
        require(authorizedSigners.length > requiredSignatures, "Cannot remove - would break multi-sig");

        isAuthorizedSigner[signer] = false;
        _revokeRole(MULTISIG_SIGNER_ROLE, signer);

        // Remove from array
        for (uint i = 0; i < authorizedSigners.length; i++) {
            if (authorizedSigners[i] == signer) {
                authorizedSigners[i] = authorizedSigners[authorizedSigners.length - 1];
                authorizedSigners.pop();
                break;
            }
        }

        emit MultiSigSignerRemoved(signer);
    }

    /**
     * @dev Cancel a pending proposal
     */
    function cancelProposal(bytes32 proposalId) external {
        MultiSigProposal storage proposal = proposals[proposalId];
        
        require(proposal.proposalId != 0, "Proposal does not exist");
        require(!proposal.executed, "Proposal already executed");
        require(!proposal.cancelled, "Proposal already cancelled");
        require(
            msg.sender == proposal.proposer || hasRole(DEFAULT_ADMIN_ROLE, msg.sender),
            "Not authorized to cancel"
        );

        proposal.cancelled = true;
        emit MultiSigProposalCancelled(proposalId, msg.sender);
    }

    /**
     * @dev Get proposal details
     */
    function getProposal(bytes32 proposalId) external view returns (
        address proposer,
        uint8 operationType,
        bytes memory data,
        uint256 deadline,
        uint8 signaturesCount,
        bool executed,
        bool cancelled,
        address[] memory signers
    ) {
        MultiSigProposal storage proposal = proposals[proposalId];
        require(proposal.proposalId != 0, "Proposal does not exist");

        return (
            proposal.proposer,
            proposal.operationType,
            proposal.data,
            proposal.deadline,
            proposal.signaturesCount,
            proposal.executed,
            proposal.cancelled,
            proposal.signers
        );
    }

    /**
     * @dev Get authorized signers
     */
    function getAuthorizedSigners() external view returns (address[] memory) {
        return authorizedSigners;
    }

    /**
     * @dev Emergency pause with multi-sig requirement
     */
    function emergencyPause() external onlyRole(EMERGENCY_ROLE) {
        bytes memory proposalData = abi.encode(uint8(0)); // 0 = pause
        createMultiSigProposal(2, proposalData, block.timestamp + 1 hours);
    }

    /**
     * @dev Emergency unpause with multi-sig requirement  
     */
    function emergencyUnpause() external onlyRole(EMERGENCY_ROLE) {
        bytes memory proposalData = abi.encode(uint8(1)); // 1 = unpause
        createMultiSigProposal(2, proposalData, block.timestamp + 1 hours);
    }

    // Include all the internal helper functions from the original contract
    function _checkUsdaCompliance(string memory cropType, uint256 netFootprint) internal pure returns (bool) {
        uint256 threshold = _getThresholdForCrop(cropType);
        return netFootprint <= threshold;
    }

    function _getThresholdForCrop(string memory cropType) internal pure returns (uint256) {
        bytes32 cropHash = keccak256(abi.encodePacked(cropType));
        
        if (cropHash == keccak256(abi.encodePacked("citrus")) || 
            cropHash == keccak256(abi.encodePacked("orange"))) {
            return USDA_CITRUS_THRESHOLD;
        } else if (cropHash == keccak256(abi.encodePacked("almond"))) {
            return USDA_ALMOND_THRESHOLD;
        } else if (cropHash == keccak256(abi.encodePacked("soybean"))) {
            return USDA_SOYBEAN_THRESHOLD;
        }
        
        return USDA_GENERAL_THRESHOLD;
    }

    // Standard getter functions
    function getCarbonRecord(uint256 productionId) external view returns (CarbonRecord memory) {
        require(carbonRecords[productionId].timestamp > 0, "Record does not exist");
        return carbonRecords[productionId];
    }

    function getProducer(uint256 producerId) external view returns (Producer memory) {
        return producers[producerId];
    }

    function getProducerRecords(uint256 producerId) external view returns (uint256[] memory) {
        return producerRecords[producerId];
    }

    function getContractStats() external view returns (
        uint256 _totalRecords,
        uint256 _totalCreditsIssued,
        uint256 _totalProducers,
        uint8 _requiredSignatures,
        uint256 _authorizedSignersCount
    ) {
        return (totalRecords, totalCreditsIssued, totalProducers, requiredSignatures, authorizedSigners.length);
    }

    function verifyDataIntegrity(
        uint256 productionId,
        string calldata originalData
    ) external view returns (bool) {
        CarbonRecord memory record = carbonRecords[productionId];
        require(record.timestamp > 0, "Record does not exist");
        
        bytes32 computedHash = keccak256(abi.encodePacked(originalData));
        return computedHash == record.dataHash;
    }
}