// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

import "@openzeppelin/contracts/token/ERC721/ERC721.sol";
import "@openzeppelin/contracts/token/ERC721/extensions/ERC721URIStorage.sol";
import "@openzeppelin/contracts/access/AccessControl.sol";
import "@openzeppelin/contracts/security/Pausable.sol";
import "@openzeppelin/contracts/security/ReentrancyGuard.sol";
import "@openzeppelin/contracts/utils/Counters.sol";
import "@openzeppelin/contracts/utils/cryptography/ECDSA.sol";

/**
 * @title MultiSigCarbonCreditToken
 * @dev Enhanced ERC721 NFT contract for Trazo's carbon credits with multi-signature security
 * Implements production-grade multi-signature requirements for high-value carbon credit operations
 */
contract MultiSigCarbonCreditToken is ERC721, ERC721URIStorage, AccessControl, Pausable, ReentrancyGuard {
    using Counters for Counters.Counter;
    using ECDSA for bytes32;

    bytes32 public constant MINTER_ROLE = keccak256("MINTER_ROLE");
    bytes32 public constant VERIFIER_ROLE = keccak256("VERIFIER_ROLE");
    bytes32 public constant BATCH_PROCESSOR_ROLE = keccak256("BATCH_PROCESSOR_ROLE");
    bytes32 public constant MULTISIG_SIGNER_ROLE = keccak256("MULTISIG_SIGNER_ROLE");
    bytes32 public constant AUDITOR_ROLE = keccak256("AUDITOR_ROLE");

    // Multi-signature configuration
    uint8 public requiredSignatures;
    mapping(address => bool) public isAuthorizedSigner;
    address[] public authorizedSigners;

    // Multi-sig thresholds
    uint256 public multisigCreditThreshold = 100000; // 100 credits in grams
    uint256 public multisigValueThreshold = 50000; // $50,000 USD equivalent
    uint256 public multisigBatchThreshold = 10; // 10 credits in single batch

    // Gas-optimized storage packing
    struct CarbonCredit {
        uint128 productionId;
        uint128 co2eAmount;
        uint64 issuanceDate;
        uint64 expirationDate;
        uint32 producerId;
        uint8 creditType;
        bool isRetired;
        bool usdaVerified;
        bool requiresMultisig;
        bytes32 approvalHash;
    }

    struct BatchMintData {
        address farmer;
        uint256 productionId;
        uint256 co2eAmount;
        string usdaVerificationHash;
        uint8 creditType;
        uint256 valueUsd;
    }

    struct MultiSigMintProposal {
        bytes32 proposalId;
        address proposer;
        bytes mintData;
        uint256 deadline;
        uint8 signaturesCount;
        bool executed;
        bool cancelled;
        mapping(address => bool) hasSigned;
        address[] signers;
        uint256 totalCredits;
        uint256 totalValue;
    }

    // Storage
    mapping(uint256 => CarbonCredit) public carbonCredits;
    mapping(uint256 => string) public usdaVerificationHashes;
    mapping(address => uint256[]) public farmerCredits;
    mapping(uint256 => uint256[]) public productionCredits;
    mapping(bytes32 => MultiSigMintProposal) public mintProposals;
    
    Counters.Counter private _tokenIdCounter;
    uint256 public proposalNonce;
    
    // Gas optimization: batch processing limits
    uint256 public constant MAX_BATCH_SIZE = 50;
    uint256 public constant CREDIT_VALIDITY_PERIOD = 365 days * 10; // 10 years
    
    // Statistics
    uint256 public totalCreditsIssued;
    uint256 public totalCreditsRetired;
    uint256 public totalCO2eTokenized;
    uint256 public totalValueUsd;

    // Events
    event CarbonCreditMinted(
        uint256 indexed tokenId,
        address indexed farmer,
        uint256 indexed productionId,
        uint256 co2eAmount,
        uint8 creditType,
        bool requiresMultisig
    );
    
    event CarbonCreditRetired(
        uint256 indexed tokenId,
        address indexed retiredBy,
        uint256 co2eAmount
    );
    
    event BatchMintCompleted(
        uint256 indexed batchId,
        uint256 creditsCount,
        uint256 totalCO2e,
        bool requiresMultisig
    );

    event USDAVerificationUpdated(
        uint256 indexed tokenId,
        bool verified,
        string verificationHash
    );

    event MultiSigMintProposalCreated(
        bytes32 indexed proposalId,
        address indexed proposer,
        uint256 totalCredits,
        uint256 totalValue,
        uint256 deadline
    );

    event MultiSigMintProposalSigned(
        bytes32 indexed proposalId,
        address indexed signer,
        uint8 signaturesCount
    );

    event MultiSigMintProposalExecuted(
        bytes32 indexed proposalId,
        uint256 creditsCount
    );

    event MultiSigSignerAdded(address indexed signer);
    event MultiSigSignerRemoved(address indexed signer);
    event MultiSigConfigUpdated(uint8 requiredSignatures);

    constructor(
        address[] memory _initialSigners,
        uint8 _requiredSignatures
    ) ERC721("Trazo Carbon Credits", "TCC") {
        require(_initialSigners.length >= _requiredSignatures, "Insufficient initial signers");
        require(_requiredSignatures >= 2, "Minimum 2 signatures required");

        _grantRole(DEFAULT_ADMIN_ROLE, msg.sender);
        _grantRole(MINTER_ROLE, msg.sender);
        _grantRole(VERIFIER_ROLE, msg.sender);
        _grantRole(BATCH_PROCESSOR_ROLE, msg.sender);
        _grantRole(AUDITOR_ROLE, msg.sender);

        // Initialize multi-sig configuration
        requiredSignatures = _requiredSignatures;

        for (uint i = 0; i < _initialSigners.length; i++) {
            require(_initialSigners[i] != address(0), "Invalid signer address");
            require(!isAuthorizedSigner[_initialSigners[i]], "Duplicate signer");
            
            isAuthorizedSigner[_initialSigners[i]] = true;
            authorizedSigners.push(_initialSigners[i]);
            _grantRole(MULTISIG_SIGNER_ROLE, _initialSigners[i]);
            
            emit MultiSigSignerAdded(_initialSigners[i]);
        }

        emit MultiSigConfigUpdated(requiredSignatures);
    }

    modifier onlyAuthorizedSigner() {
        require(isAuthorizedSigner[msg.sender], "Not an authorized signer");
        _;
    }

    /**
     * @dev Check if minting operation requires multi-signature approval
     */
    function requiresMultiSigApproval(
        uint256 co2eAmount,
        uint256 valueUsd,
        uint256 batchSize
    ) public view returns (bool) {
        return (
            co2eAmount >= multisigCreditThreshold ||
            valueUsd >= multisigValueThreshold ||
            batchSize >= multisigBatchThreshold
        );
    }

    /**
     * @dev Create multi-signature proposal for high-value minting
     */
    function createMultiSigMintProposal(
        BatchMintData[] calldata batchData,
        uint256 deadline
    ) external onlyRole(MINTER_ROLE) returns (bytes32) {
        require(batchData.length > 0 && batchData.length <= MAX_BATCH_SIZE, "Invalid batch size");
        require(deadline > block.timestamp, "Invalid deadline");
        require(deadline <= block.timestamp + 7 days, "Deadline too far");

        uint256 totalCredits = 0;
        uint256 totalValue = 0;

        // Calculate totals and validate batch
        for (uint256 i = 0; i < batchData.length; i++) {
            require(batchData[i].farmer != address(0), "Invalid farmer address");
            require(batchData[i].co2eAmount > 0, "Invalid CO2e amount");
            require(batchData[i].creditType <= 2, "Invalid credit type");
            
            totalCredits += batchData[i].co2eAmount;
            totalValue += batchData[i].valueUsd;
        }

        require(
            requiresMultiSigApproval(totalCredits, totalValue, batchData.length),
            "Multi-sig not required for this batch"
        );

        bytes32 proposalId = keccak256(abi.encodePacked(
            msg.sender,
            totalCredits,
            totalValue,
            block.timestamp,
            proposalNonce++
        ));

        require(mintProposals[proposalId].proposalId == 0, "Proposal already exists");

        MultiSigMintProposal storage proposal = mintProposals[proposalId];
        proposal.proposalId = proposalId;
        proposal.proposer = msg.sender;
        proposal.mintData = abi.encode(batchData);
        proposal.deadline = deadline;
        proposal.totalCredits = totalCredits;
        proposal.totalValue = totalValue;

        emit MultiSigMintProposalCreated(proposalId, msg.sender, totalCredits, totalValue, deadline);

        return proposalId;
    }

    /**
     * @dev Sign a multi-signature minting proposal
     */
    function signMintProposal(bytes32 proposalId) external onlyAuthorizedSigner {
        MultiSigMintProposal storage proposal = mintProposals[proposalId];
        
        require(proposal.proposalId != 0, "Proposal does not exist");
        require(!proposal.executed, "Proposal already executed");
        require(!proposal.cancelled, "Proposal cancelled");
        require(block.timestamp <= proposal.deadline, "Proposal expired");
        require(!proposal.hasSigned[msg.sender], "Already signed");

        proposal.hasSigned[msg.sender] = true;
        proposal.signers.push(msg.sender);
        proposal.signaturesCount++;

        emit MultiSigMintProposalSigned(proposalId, msg.sender, proposal.signaturesCount);

        // Auto-execute if enough signatures
        if (proposal.signaturesCount >= requiredSignatures) {
            _executeMintProposal(proposalId);
        }
    }

    /**
     * @dev Execute a multi-signature minting proposal
     */
    function executeMintProposal(bytes32 proposalId) external onlyAuthorizedSigner {
        MultiSigMintProposal storage proposal = mintProposals[proposalId];
        
        require(proposal.proposalId != 0, "Proposal does not exist");
        require(!proposal.executed, "Proposal already executed");
        require(!proposal.cancelled, "Proposal cancelled");
        require(proposal.signaturesCount >= requiredSignatures, "Insufficient signatures");
        require(block.timestamp <= proposal.deadline, "Proposal expired");

        _executeMintProposal(proposalId);
    }

    /**
     * @dev Internal function to execute minting proposal
     */
    function _executeMintProposal(bytes32 proposalId) internal {
        MultiSigMintProposal storage proposal = mintProposals[proposalId];
        proposal.executed = true;

        BatchMintData[] memory batchData = abi.decode(proposal.mintData, (BatchMintData[]));
        
        uint256[] memory tokenIds = new uint256[](batchData.length);
        uint256 batchTotalCO2e = 0;

        for (uint256 i = 0; i < batchData.length; i++) {
            BatchMintData memory data = batchData[i];
            
            uint256 tokenId = _tokenIdCounter.current();
            _tokenIdCounter.increment();

            // Gas-optimized storage with multi-sig flag
            carbonCredits[tokenId] = CarbonCredit({
                productionId: uint128(data.productionId),
                co2eAmount: uint128(data.co2eAmount),
                issuanceDate: uint64(block.timestamp),
                expirationDate: uint64(block.timestamp + CREDIT_VALIDITY_PERIOD),
                producerId: uint32(data.productionId),
                creditType: data.creditType,
                isRetired: false,
                usdaVerified: bytes(data.usdaVerificationHash).length > 0,
                requiresMultisig: true,
                approvalHash: proposalId
            });

            if (bytes(data.usdaVerificationHash).length > 0) {
                usdaVerificationHashes[tokenId] = data.usdaVerificationHash;
            }

            // Update mappings
            farmerCredits[data.farmer].push(tokenId);
            productionCredits[data.productionId].push(tokenId);

            // Mint token
            _safeMint(data.farmer, tokenId);

            tokenIds[i] = tokenId;
            batchTotalCO2e += data.co2eAmount;

            emit CarbonCreditMinted(tokenId, data.farmer, data.productionId, data.co2eAmount, data.creditType, true);
        }

        // Update statistics
        totalCreditsIssued += batchData.length;
        totalCO2eTokenized += batchTotalCO2e;
        totalValueUsd += proposal.totalValue;

        emit MultiSigMintProposalExecuted(proposalId, batchData.length);
        emit BatchMintCompleted(uint256(proposalId), batchData.length, batchTotalCO2e, true);
    }

    /**
     * @dev Standard single carbon credit minting (for low-value credits)
     */
    function mintCarbonCredit(
        address farmer,
        uint256 productionId,
        uint256 co2eAmount,
        string memory usdaVerificationHash,
        uint8 creditType,
        uint256 valueUsd
    ) external onlyRole(MINTER_ROLE) whenNotPaused returns (uint256) {
        require(farmer != address(0), "Invalid farmer address");
        require(co2eAmount > 0, "Invalid CO2e amount");
        require(creditType <= 2, "Invalid credit type");
        require(productionId > 0, "Invalid production ID");

        // Check if multi-sig is required
        if (requiresMultiSigApproval(co2eAmount, valueUsd, 1)) {
            revert("Multi-signature approval required for this credit value");
        }

        uint256 tokenId = _tokenIdCounter.current();
        _tokenIdCounter.increment();

        carbonCredits[tokenId] = CarbonCredit({
            productionId: uint128(productionId),
            co2eAmount: uint128(co2eAmount),
            issuanceDate: uint64(block.timestamp),
            expirationDate: uint64(block.timestamp + CREDIT_VALIDITY_PERIOD),
            producerId: uint32(productionId),
            creditType: creditType,
            isRetired: false,
            usdaVerified: bytes(usdaVerificationHash).length > 0,
            requiresMultisig: false,
            approvalHash: bytes32(0)
        });

        if (bytes(usdaVerificationHash).length > 0) {
            usdaVerificationHashes[tokenId] = usdaVerificationHash;
        }

        farmerCredits[farmer].push(tokenId);
        productionCredits[productionId].push(tokenId);

        totalCreditsIssued++;
        totalCO2eTokenized += co2eAmount;
        totalValueUsd += valueUsd;

        _safeMint(farmer, tokenId);

        emit CarbonCreditMinted(tokenId, farmer, productionId, co2eAmount, creditType, false);

        return tokenId;
    }

    /**
     * @dev Batch minting for low-value credits (no multi-sig required)
     */
    function batchMintCarbonCredits(
        BatchMintData[] calldata batchData
    ) external onlyRole(BATCH_PROCESSOR_ROLE) whenNotPaused returns (uint256[] memory) {
        require(batchData.length > 0 && batchData.length <= MAX_BATCH_SIZE, "Invalid batch size");

        uint256 totalCredits = 0;
        uint256 totalValue = 0;

        // Pre-validate batch doesn't require multi-sig
        for (uint256 i = 0; i < batchData.length; i++) {
            totalCredits += batchData[i].co2eAmount;
            totalValue += batchData[i].valueUsd;
        }

        if (requiresMultiSigApproval(totalCredits, totalValue, batchData.length)) {
            revert("Multi-signature approval required for this batch - use createMultiSigMintProposal");
        }

        uint256[] memory tokenIds = new uint256[](batchData.length);
        uint256 batchTotalCO2e = 0;

        for (uint256 i = 0; i < batchData.length; i++) {
            BatchMintData memory data = batchData[i];
            
            require(data.farmer != address(0), "Invalid farmer address");
            require(data.co2eAmount > 0, "Invalid CO2e amount");
            require(data.creditType <= 2, "Invalid credit type");

            uint256 tokenId = _tokenIdCounter.current();
            _tokenIdCounter.increment();

            carbonCredits[tokenId] = CarbonCredit({
                productionId: uint128(data.productionId),
                co2eAmount: uint128(data.co2eAmount),
                issuanceDate: uint64(block.timestamp),
                expirationDate: uint64(block.timestamp + CREDIT_VALIDITY_PERIOD),
                producerId: uint32(data.productionId),
                creditType: data.creditType,
                isRetired: false,
                usdaVerified: bytes(data.usdaVerificationHash).length > 0,
                requiresMultisig: false,
                approvalHash: bytes32(0)
            });

            if (bytes(data.usdaVerificationHash).length > 0) {
                usdaVerificationHashes[tokenId] = data.usdaVerificationHash;
            }

            farmerCredits[data.farmer].push(tokenId);
            productionCredits[data.productionId].push(tokenId);

            _safeMint(data.farmer, tokenId);

            tokenIds[i] = tokenId;
            batchTotalCO2e += data.co2eAmount;

            emit CarbonCreditMinted(tokenId, data.farmer, data.productionId, data.co2eAmount, data.creditType, false);
        }

        totalCreditsIssued += batchData.length;
        totalCO2eTokenized += batchTotalCO2e;
        totalValueUsd += totalValue;

        emit BatchMintCompleted(block.timestamp, batchData.length, batchTotalCO2e, false);

        return tokenIds;
    }

    /**
     * @dev Retire a carbon credit (permanently remove from circulation)
     */
    function retireCarbonCredit(uint256 tokenId) external whenNotPaused {
        require(_exists(tokenId), "Token does not exist");
        require(ownerOf(tokenId) == msg.sender, "Not token owner");
        require(!carbonCredits[tokenId].isRetired, "Credit already retired");

        CarbonCredit storage credit = carbonCredits[tokenId];
        credit.isRetired = true;

        totalCreditsRetired++;

        _burn(tokenId);

        emit CarbonCreditRetired(tokenId, msg.sender, credit.co2eAmount);
    }

    /**
     * @dev Add a new multi-sig signer
     */
    function addMultiSigSigner(address newSigner) external onlyRole(DEFAULT_ADMIN_ROLE) {
        require(newSigner != address(0), "Invalid signer address");
        require(!isAuthorizedSigner[newSigner], "Already a signer");

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
     * @dev Update multi-sig configuration
     */
    function updateMultiSigConfig(
        uint8 newRequiredSignatures,
        uint256 newCreditThreshold,
        uint256 newValueThreshold,
        uint256 newBatchThreshold
    ) external onlyRole(DEFAULT_ADMIN_ROLE) {
        require(newRequiredSignatures >= 2, "Minimum 2 signatures required");
        require(newRequiredSignatures <= authorizedSigners.length, "Cannot require more signatures than signers");

        requiredSignatures = newRequiredSignatures;
        multisigCreditThreshold = newCreditThreshold;
        multisigValueThreshold = newValueThreshold;
        multisigBatchThreshold = newBatchThreshold;

        emit MultiSigConfigUpdated(requiredSignatures);
    }

    /**
     * @dev Cancel a pending mint proposal
     */
    function cancelMintProposal(bytes32 proposalId) external {
        MultiSigMintProposal storage proposal = mintProposals[proposalId];
        
        require(proposal.proposalId != 0, "Proposal does not exist");
        require(!proposal.executed, "Proposal already executed");
        require(!proposal.cancelled, "Proposal already cancelled");
        require(
            msg.sender == proposal.proposer || hasRole(DEFAULT_ADMIN_ROLE, msg.sender),
            "Not authorized to cancel"
        );

        proposal.cancelled = true;
    }

    /**
     * @dev Get mint proposal details
     */
    function getMintProposal(bytes32 proposalId) external view returns (
        address proposer,
        uint256 deadline,
        uint8 signaturesCount,
        bool executed,
        bool cancelled,
        uint256 totalCredits,
        uint256 totalValue,
        address[] memory signers
    ) {
        MultiSigMintProposal storage proposal = mintProposals[proposalId];
        require(proposal.proposalId != 0, "Proposal does not exist");

        return (
            proposal.proposer,
            proposal.deadline,
            proposal.signaturesCount,
            proposal.executed,
            proposal.cancelled,
            proposal.totalCredits,
            proposal.totalValue,
            proposal.signers
        );
    }

    /**
     * @dev Get carbon credit details with multi-sig info
     */
    function getCarbonCredit(uint256 tokenId) external view returns (
        uint256 productionId,
        uint256 co2eAmount,
        uint256 issuanceDate,
        uint256 expirationDate,
        uint256 producerId,
        uint8 creditType,
        bool isRetired,
        bool usdaVerified,
        bool requiresMultisig,
        bytes32 approvalHash,
        string memory verificationHash
    ) {
        require(_exists(tokenId), "Token does not exist");
        
        CarbonCredit memory credit = carbonCredits[tokenId];
        
        return (
            credit.productionId,
            credit.co2eAmount,
            credit.issuanceDate,
            credit.expirationDate,
            credit.producerId,
            credit.creditType,
            credit.isRetired,
            credit.usdaVerified,
            credit.requiresMultisig,
            credit.approvalHash,
            usdaVerificationHashes[tokenId]
        );
    }

    /**
     * @dev Get authorized signers
     */
    function getAuthorizedSigners() external view returns (address[] memory) {
        return authorizedSigners;
    }

    /**
     * @dev Get contract statistics with multi-sig info
     */
    function getContractStats() external view returns (
        uint256 _totalCreditsIssued,
        uint256 _totalCreditsRetired,
        uint256 _totalCO2eTokenized,
        uint256 _totalValueUsd,
        uint256 _activeCredits,
        uint8 _requiredSignatures,
        uint256 _authorizedSignersCount
    ) {
        return (
            totalCreditsIssued,
            totalCreditsRetired,
            totalCO2eTokenized,
            totalValueUsd,
            totalCreditsIssued - totalCreditsRetired,
            requiredSignatures,
            authorizedSigners.length
        );
    }

    // Required overrides for multiple inheritance
    function _burn(uint256 tokenId) internal override(ERC721, ERC721URIStorage) {
        super._burn(tokenId);
    }

    function tokenURI(uint256 tokenId) public view override(ERC721, ERC721URIStorage) returns (string memory) {
        return super.tokenURI(tokenId);
    }

    function supportsInterface(bytes4 interfaceId) public view override(ERC721, ERC721URIStorage, AccessControl) returns (bool) {
        return super.supportsInterface(interfaceId);
    }

    // Emergency functions
    function pause() external onlyRole(DEFAULT_ADMIN_ROLE) {
        _pause();
    }

    function unpause() external onlyRole(DEFAULT_ADMIN_ROLE) {
        _unpause();
    }
}