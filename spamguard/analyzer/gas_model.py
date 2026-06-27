from dataclasses import dataclass


@dataclass
class CategoryLabsModel:
    d0: float = 1200.0
    beta: float = 6.0
    slot_cost: float = 20.0
    r0: float = 6000.0
    target_spam_ratio: float = 0.15
    baseline_floor_wei: int = 1_000_000
    max_iterations: int = 12

    def compute_optimal_gas_floor(self, current_spam_ratio: float, block_capacity: int) -> int:
        if current_spam_ratio <= self.target_spam_ratio:
            return self.baseline_floor_wei

        target_spam_count = max((self.target_spam_ratio * block_capacity) / self.slot_cost, 1.0)
        candidate_floor_gwei = max(self.baseline_floor_wei / 1e9, 0.001)

        for _ in range(self.max_iterations):
            demand_at_floor = max(0.0, self.d0 - (self.beta * candidate_floor_gwei))
            if demand_at_floor == 0:
                break

            next_floor_gwei = (self.r0 * demand_at_floor) / (self.d0 * self.slot_cost * (target_spam_count + 1.0))
            if abs(next_floor_gwei - candidate_floor_gwei) < 1e-6:
                candidate_floor_gwei = next_floor_gwei
                break
            candidate_floor_gwei = max(next_floor_gwei, 0.001)

        return max(int(candidate_floor_gwei * 1e9), self.baseline_floor_wei)

    def compute_expected_spam_equilibrium(self, gas_floor_wei: int) -> float:
        gas_floor_gwei = max(gas_floor_wei / 1e9, 0.001)
        demand_at_floor = max(0.0, self.d0 - (self.beta * gas_floor_gwei))
        return max(0.0, (self.r0 * demand_at_floor) / (self.d0 * self.slot_cost * gas_floor_gwei) - 1.0)

    def compute_plateau_threshold(self, gas_floor_wei: int) -> int:
        gas_floor_gwei = max(gas_floor_wei / 1e9, 0.001)
        demand_at_floor = max(0.0, self.d0 - (self.beta * gas_floor_gwei))
        spam_at_floor = max(0.0, (self.r0 * demand_at_floor) / (self.d0 * gas_floor_gwei) - self.slot_cost)
        return int(demand_at_floor + spam_at_floor)
