// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

contract SpamOracle {
    address public updater;

    struct SpamMetrics {
        uint256 spamGasRatio;
        uint256 suggestedGasFloor;
        uint256 blockNumber;
        uint256 timestamp;
    }

    SpamMetrics public latest;
    SpamMetrics[100] private history;
    uint256 public historyCount;

    event SpamAlert(
        uint256 indexed blockNumber,
        uint256 spamGasRatio,
        uint256 suggestedGasFloor,
        bool highSpam
    );

    error NotUpdater();
    error StaleBlock(uint256 currentLatest, uint256 attemptedBlock);

    modifier onlyUpdater() {
        if (msg.sender != updater) revert NotUpdater();
        _;
    }

    constructor(address _updater) {
        updater = _updater;
    }

    function updateSpamMetrics(
        uint256 spamGasRatio,
        uint256 suggestedGasFloor,
        uint256 blockNumber
    ) external onlyUpdater {
        if (latest.blockNumber != 0 && blockNumber <= latest.blockNumber) {
            revert StaleBlock(latest.blockNumber, blockNumber);
        }

        latest = SpamMetrics({
            spamGasRatio: spamGasRatio,
            suggestedGasFloor: suggestedGasFloor,
            blockNumber: blockNumber,
            timestamp: block.timestamp
        });

        history[blockNumber % 100] = latest;
        if (historyCount < 100) {
            historyCount += 1;
        }

        emit SpamAlert(blockNumber, spamGasRatio, suggestedGasFloor, spamGasRatio >= 2000);
    }

    function setUpdater(address newUpdater) external onlyUpdater {
        updater = newUpdater;
    }

    function getLatestMetrics() external view returns (SpamMetrics memory) {
        return latest;
    }

    function getHistorySlot(uint256 slot) external view returns (SpamMetrics memory) {
        require(slot < 100, "slot out of range");
        return history[slot];
    }

    function isHighSpam() external view returns (bool) {
        return latest.spamGasRatio >= 2000;
    }

    function getRecommendedGasFloor() external view returns (uint256) {
        return latest.suggestedGasFloor;
    }
}
