from dataclasses import dataclass, field
from statistics import median
from typing import List, Optional

from spam_detector import SpamResult


@dataclass
class CalibrationSnapshot:
    sample_size: int
    estimated_s: float
    median_spam_ratio: float
    mean_spam_ratio: float
    block_capacity: int


@dataclass
class CategoryLabsModel:
    d0: float = 1200.0
    beta: float = 6.0
    s: float = 20.0
    r0: float = 6000.0
    target_spam_ratio: float = 0.15
    baseline_floor_wei: int = 1_000_000
    default_block_capacity: int = 30_000_000
    calibration_history_size: int = 100
    spam_ratio_history: List[float] = field(default_factory=list)
    calibration_history: List[Optional[CalibrationSnapshot]] = field(init=False)
    calibration_index: int = field(default=0, init=False)
    calibration_count: int = field(default=0, init=False)
    calibrated_block_capacity: int = field(init=False)
    current_floor_wei: int = field(init=False)

    def __post_init__(self) -> None:
        self.calibration_history = [None] * self.calibration_history_size
        self.calibrated_block_capacity = self.default_block_capacity
        self.current_floor_wei = self.baseline_floor_wei

    @property
    def slot_cost(self) -> float:
        return self.s

    def calibrate(self, recent_blocks: List[SpamResult]) -> None:
        if not recent_blocks:
            return

        spam_gas_samples = [
            spam_tx.gas
            for block in recent_blocks
            for spam_tx in block.spam_txs
            if spam_tx.gas > 0
        ]
        if spam_gas_samples:
            self.s = float(median(spam_gas_samples))

        self.spam_ratio_history = [block.spam_ratio for block in recent_blocks[-100:]]
        capacities = [block.total_gas for block in recent_blocks if block.total_gas > 0]
        if capacities:
            self.calibrated_block_capacity = int(median(capacities))

        snapshot = CalibrationSnapshot(
            sample_size=len(recent_blocks),
            estimated_s=self.s,
            median_spam_ratio=float(median(self.spam_ratio_history)) if self.spam_ratio_history else 0.0,
            mean_spam_ratio=(sum(self.spam_ratio_history) / len(self.spam_ratio_history)) if self.spam_ratio_history else 0.0,
            block_capacity=self.calibrated_block_capacity,
        )
        self.calibration_history[self.calibration_index] = snapshot
        self.calibration_index = (self.calibration_index + 1) % self.calibration_history_size
        self.calibration_count = min(self.calibration_count + 1, self.calibration_history_size)

    def compute_equilibrium_spam(self, g_min_wei: int, b_max: int) -> float:
        gas_floor_gwei = max(g_min_wei / 1e9, self.baseline_floor_wei / 1e9)
        demand_at_floor = self._demand_at_floor(gas_floor_gwei)
        spam_tx_count = max((self.r0 * demand_at_floor) / (self.d0 * self.s * gas_floor_gwei) - 1.0, 0.0)
        spam_gas = spam_tx_count * self.s
        total_gas = min(float(max(b_max, 1)), demand_at_floor + spam_gas)
        return 0.0 if total_gas <= 0 else min(spam_gas / total_gas, 1.0)

    def suggest_gas_floor_to_hit_target(self, current_spam_ratio: float, target_ratio: float = 0.15) -> int:
        if current_spam_ratio <= target_ratio:
            self.current_floor_wei = self.baseline_floor_wei
            return self.baseline_floor_wei

        b_max = self.calibrated_block_capacity or self.default_block_capacity
        low = self.baseline_floor_wei
        high = max(low, 1_000_000_000)

        while self.compute_equilibrium_spam(high, b_max) > target_ratio and high < 10**18:
            high *= 2

        for _ in range(80):
            mid = (low + high) // 2
            predicted_ratio = self.compute_equilibrium_spam(mid, b_max)
            if predicted_ratio <= target_ratio:
                high = mid
            else:
                low = mid + 1

        self.current_floor_wei = max(high, self.baseline_floor_wei)
        return self.current_floor_wei

    def compute_mmus(self, b_max: int, delta_b: int = 1000) -> float:
        if delta_b <= 0:
            raise ValueError("delta_b must be positive")

        user_share_now = self._user_gas_at_capacity(b_max)
        user_share_next = self._user_gas_at_capacity(b_max + delta_b)
        marginal_user_gas = max(user_share_next - user_share_now, 0.0)
        return min(max(marginal_user_gas / delta_b, 0.0), 1.0)

    def compute_optimal_gas_floor(self, current_spam_ratio: float, block_capacity: int) -> int:
        self.calibrated_block_capacity = max(block_capacity, 1)
        return self.suggest_gas_floor_to_hit_target(current_spam_ratio, self.target_spam_ratio)

    def compute_expected_spam_equilibrium(self, gas_floor_wei: int) -> float:
        self.current_floor_wei = max(gas_floor_wei, self.baseline_floor_wei)
        return self.compute_equilibrium_spam(gas_floor_wei, self.calibrated_block_capacity)

    def compute_plateau_threshold(self, gas_floor_wei: int) -> int:
        gas_floor_gwei = max(gas_floor_wei / 1e9, self.baseline_floor_wei / 1e9)
        demand_at_floor = self._demand_at_floor(gas_floor_gwei)
        spam_tx_count = max((self.r0 * demand_at_floor) / (self.d0 * self.s * gas_floor_gwei) - 1.0, 0.0)
        return int(demand_at_floor + (spam_tx_count * self.s))

    def get_recent_calibrations(self) -> List[CalibrationSnapshot]:
        recent: List[CalibrationSnapshot] = []
        for offset in range(self.calibration_count):
            idx = (self.calibration_index - self.calibration_count + offset) % self.calibration_history_size
            snapshot = self.calibration_history[idx]
            if snapshot is not None:
                recent.append(snapshot)
        return recent

    def _demand_at_floor(self, gas_floor_gwei: float) -> float:
        return max(0.0, self.d0 - (self.beta * gas_floor_gwei))

    def _user_gas_at_capacity(self, b_max: int) -> float:
        if b_max <= 0:
            return 0.0

        equilibrium_ratio = self.compute_equilibrium_spam(self.current_floor_wei, b_max)
        spam_gas = equilibrium_ratio * b_max
        user_gas = max(b_max - spam_gas, 0.0)
        return min(user_gas, float(b_max))
