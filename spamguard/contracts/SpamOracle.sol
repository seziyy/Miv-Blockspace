// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

contract SpamOracle {
    uint256 private constant HISTORY_SIZE = 50;

    address public owner;
    address public updater;
    uint256 public alertThreshold;
    bool public isCurrentlyHighSpam;

    struct SpamMetrics {
        uint128 spamGasRatio;
        uint128 suggestedGasFloor;
        uint256 blockNumber;
        uint256 timestamp;
    }

    SpamMetrics public latest;
    SpamMetrics[HISTORY_SIZE] private history;
    uint256 public historyHead;
    uint256 public historyCount;

    event SpamAlert(
        uint256 indexed blockNumber,
        uint256 spamGasRatio,
        uint256 suggestedGasFloor,
        bool highSpam
    );
    event HighSpamAlert(
        uint256 indexed blockNumber,
        uint256 spamGasRatio,
        uint256 threshold
    );

    error NotOwner();
    error NotUpdater();
    error StaleBlock(uint256 currentLatest, uint256 attemptedBlock);
    error ValueTooLarge();

    modifier onlyUpdater() {
        if (msg.sender != updater) revert NotUpdater();
        _;
    }

    modifier onlyOwner() {
        if (msg.sender != owner) revert NotOwner();
        _;
    }

    constructor(address _updater) {
        owner = msg.sender;
        updater = _updater;
        alertThreshold = 2000;
    }

    function updateSpamMetrics(
        uint256 spamGasRatio,
        uint256 suggestedGasFloor,
        uint256 blockNumber
    ) external onlyUpdater {
        _storeMetrics(spamGasRatio, suggestedGasFloor, blockNumber);
    }

    function updateMetrics(
        uint256 spamGasRatio,
        uint256 suggestedGasFloor,
        uint256 blockNumber
    ) external onlyUpdater {
        _storeMetrics(spamGasRatio, suggestedGasFloor, blockNumber);
    }

    function _storeMetrics(
        uint256 spamGasRatio,
        uint256 suggestedGasFloor,
        uint256 blockNumber
    ) internal {
        if (latest.blockNumber != 0 && blockNumber <= latest.blockNumber) {
            revert StaleBlock(latest.blockNumber, blockNumber);
        }
        if (spamGasRatio > type(uint128).max || suggestedGasFloor > type(uint128).max) {
            revert ValueTooLarge();
        }

        latest = SpamMetrics({
            spamGasRatio: uint128(spamGasRatio),
            suggestedGasFloor: uint128(suggestedGasFloor),
            blockNumber: blockNumber,
            timestamp: block.timestamp
        });

        history[historyHead] = latest;
        historyHead = (historyHead + 1) % HISTORY_SIZE;
        if (historyCount < HISTORY_SIZE) {
            historyCount += 1;
        }

        isCurrentlyHighSpam = spamGasRatio > alertThreshold;

        emit SpamAlert(blockNumber, spamGasRatio, suggestedGasFloor, isCurrentlyHighSpam);
        if (isCurrentlyHighSpam) {
            emit HighSpamAlert(blockNumber, spamGasRatio, alertThreshold);
        }
    }

    function setUpdater(address newUpdater) external onlyUpdater {
        updater = newUpdater;
    }

    function setAlertThreshold(uint256 bps) external onlyOwner {
        alertThreshold = bps;
    }

    function getLatestMetrics() external view returns (SpamMetrics memory) {
        return latest;
    }

    function getHistorySlot(uint256 slot) external view returns (SpamMetrics memory) {
        require(slot < HISTORY_SIZE, "slot out of range");
        return history[slot];
    }

    function getAverageSpamRatio(uint256 numBlocks) external view returns (uint256) {
        require(numBlocks > 0, "numBlocks must be > 0");
        require(numBlocks <= historyCount, "numBlocks exceeds history");
        require(numBlocks <= HISTORY_SIZE, "numBlocks exceeds max");

        uint256 total;
        for (uint256 i = 0; i < numBlocks; i++) {
            uint256 idx = _historyIndexFromMostRecent(i);
            total += history[idx].spamGasRatio;
        }
        return total / numBlocks;
    }

    function getHistoricalMetrics(uint256 count) external view returns (SpamMetrics[] memory) {
        require(count <= historyCount, "count exceeds history");
        require(count <= HISTORY_SIZE, "count exceeds max");

        SpamMetrics[] memory entries = new SpamMetrics[](count);
        for (uint256 i = 0; i < count; i++) {
            entries[i] = history[_historyIndexFromMostRecent(i)];
        }
        return entries;
    }

    function isHighSpam() external view returns (bool) {
        return isCurrentlyHighSpam;
    }

    function getRecommendedGasFloor() external view returns (uint256) {
        return latest.suggestedGasFloor;
    }

    function version() external pure returns (string memory) {
        return "1.0.0";
    }

    function _historyIndexFromMostRecent(uint256 offset) internal view returns (uint256) {
        return (historyHead + HISTORY_SIZE - 1 - offset) % HISTORY_SIZE;
    }
}
