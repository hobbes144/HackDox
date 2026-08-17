class DifficultyCurve:
    def __init__(self, base_time_multiplier=1.0, base_value_decay_rate=0.98, base_cost_inflation_rate=1.05, base_detection_complexity=1.0):
        self.base_time_multiplier = base_time_multiplier
        self.base_value_decay_rate = base_value_decay_rate
        self.base_cost_inflation_rate = base_cost_inflation_rate
        self.base_detection_complexity = base_detection_complexity
        self.tick_count = 0

    def increment_ticks(self, value=1):
        self.tick_count += value
        self._apply_decay()
        self._apply_inflation()
        self._apply_complexity()

    def _apply_decay(self):
        decayed = self.tick_count * (self.base_value_decay_rate ** self.tick_count)
        self.current_decay_factor = decayed

    def _apply_inflation(self):
        inflated = self.tick_count * (self.base_cost_inflation_rate ** self.tick_count)
        self.current_inflation_factor = inflated

    def _apply_complexity(self):
        complexity = self.tick_count * (1.0 + (self.tick_count * 0.05))
        self.current_complexity_factor = complexity

    def get_reward_multiplier(self):
        return self.current_decay_factor

    def get_cost_multiplier(self):
        return self.current_inflation_factor

    def get_detection_multiplier(self):
        return self.current_complexity_factor

    def get_stats(self):
        return {
            'ticks': self.tick_count,
            'decay_factor': self.current_decay_factor,
            'inflation_factor': self.current_inflation_factor,
            'complexity_factor': self.current_complexity_factor
        }

class GameDifficulty:
    def __init__(self, player_name='Player', start_tier=1, decay_rate=DifficultyCurve.base_value_decay_rate, inflation_rate=DifficultyCurve.base_cost_inflation_rate):
        self.player_name = player_name
        self.current_tier = start_tier
        self.difficulty_curve = DifficultyCurve(base_value_decay_rate=decay_rate, base_cost_inflation_rate=inflation_rate)
        self.tier_thresholds = [100, 300, 600, 1200, 2500]
        self.tier_names = ['Novice', 'Adept', 'Veteran', 'Elite', 'Master']

    def get_tier_name(self):
        return self.tier_names[min(self.current_tier - 1, len(self.tier_names) - 1)] if self.current_tier > 0 else 'Novice'

    def get_tier_multiplier(self):
        return self.current_tier

    def advance_tier(self, value=1):
        self.current_tier = min(self.current_tier + int(value / 100), len(self.tier_thresholds))
        self.difficulty_curve.increment_ticks(value)

    def get_reward(self, base_reward):
        return base_reward * self.difficulty_curve.get_reward_multiplier() * self.get_tier_multiplier()

    def get_cost(self, base_cost):
        return base_cost * self.difficulty_curve.get_cost_multiplier() * self.get_tier_multiplier()

    def get_detection_chance(self, base_chance):
        return min(base_chance, 100.0) * self.difficulty_curve.get_detection_multiplier()

    def get_stats(self):
        tier_stats = self.get_stats_tier()
        stats = {
            'player': self.player_name,
            'tier': self.get_tier_name(),
            'current_tier': self.current_tier,
            'tier_multiplier': self.get_tier_multiplier(),
            'decay_factor': self.difficulty_curve.get_reward_multiplier(),
            'inflation_factor': self.difficulty_curve.get_cost_multiplier(),
            'complexity_factor': self.difficulty_curve.get_detection_multiplier(),
            'total_tier_threshold': self.tier_thresholds[self.current_tier - 1] if self.current_tier < len(self.tier_thresholds) else self.tier_thresholds[-1]
        }
        stats.update(tier_stats)
        return stats

    def get_stats_tier(self):
        tier_multiplier = self.get_tier_multiplier()
        decay = self.difficulty_curve.get_reward_multiplier()
        inflation = self.difficulty_curve.get_cost_multiplier()
        complexity = self.difficulty_curve.get_detection_multiplier()
        return {
            'tier_multiplier': tier_multiplier,
            'decay_value': decay,
            'inflation_value': inflation,
            'complexity_value': complexity
        }

    def get_difficulty_percentage(self):
        tier_multiplier = self.get_tier_multiplier()
        decay = self.difficulty_curve.get_reward_multiplier()
        inflation = self.difficulty_curve.get_cost_multiplier()
        complexity = self.difficulty_curve.get_detection_multiplier()
        percentage = (tier_multiplier * decay * inflation * complexity) / (tier_multiplier * 0.9 ** tier_multiplier)
        return round(percentage * 100, 2)
</think>

class DifficultyCurve:
    def __init__(self, base_time_multiplier=1.0, base_value_decay_rate=0.98, base_cost_inflation_rate=1.05, base_detection_complexity=1.0):
        self.base_time_multiplier = base_time_multiplier
        self.base_value_decay_rate = base_value_decay_rate
        self.base_cost_inflation_rate = base_cost_inflation_rate
        self.base_detection_complexity = base_detection_complexity
        self.tick_count = 0

    def increment_ticks(self, value=1):
        self.tick_count += value
        self._apply_decay()
        self._apply_inflation()
        self._apply_complexity()

    def _apply_decay(self):
        decayed = self.tick_count * (self.base_value_decay_rate ** self.tick_count)
        self.current_decay_factor = decayed

    def _apply_inflation(self):
        inflated = self.tick_count * (self.base_cost_inflation_rate ** self.tick_count)
        self.current_inflation_factor = inflated

    def _apply_complexity(self):
        complexity = self.tick_count * (1.0 + (self.tick_count * 0.05))
        self.current_complexity_factor = complexity

    def get_reward_multiplier(self):
        return self.current_decay_factor

    def get_cost_multiplier(self):
        return self.current_inflation_factor

    def get_detection_multiplier(self):
        return self.current_complexity_factor

    def get_stats(self):
        return {
            'ticks': self.tick_count,
            'decay_factor': self.current_decay_factor,
            'inflation_factor': self.current_inflation_factor,
            'complexity_factor': self.current_complexity_factor
        }


class GameDifficulty:
    def __init__(self, player_name='Player', start_tier=1, decay_rate=DifficultyCurve.base_value_decay_rate, inflation_rate=DifficultyCurve.base_cost_inflation_rate):
        self.player_name = player_name
        self.current_tier = start_tier
        self.difficulty_curve = DifficultyCurve(base_value_decay_rate=decay_rate, base_cost_inflation_rate=inflation_rate)
        self.tier_thresholds = [100, 300, 600, 1200, 2500]
        self.tier_names = ['Novice', 'Adept', 'Veteran', 'Elite', 'Master']

    def get_tier_name(self):
        return self.tier_names[min(self.current_tier - 1, len(self.tier_names) - 1)] if self.current_tier > 0 else 'Novice'

    def get_tier_multiplier(self):
        return self.current_tier

    def advance_tier(self, value=1):
        self.current_tier = min(self.current_tier + int(value / 100), len(self.tier_thresholds))
        self.difficulty_curve.increment_ticks(value)

    def get_reward(self, base_reward):
        return base_reward * self.difficulty_curve.get_reward_multiplier() * self.get_tier_multiplier()

    def get_cost(self, base_cost):
        return base_cost * self.difficulty_curve.get_cost_multiplier() * self.get_tier_multiplier()

    def get_detection_chance(self, base_chance):
        return min(base_chance, 100.0) * self.difficulty_curve.get_detection_multiplier()

    def get_stats(self):
        tier_stats = self.get_stats_tier()
        stats = {
            'player': self.player_name,
            'tier': self.get_tier_name(),
            'current_tier': self.current_tier,
            'tier_multiplier': self.get_tier_multiplier(),
            'decay_factor': self.difficulty_curve.get_reward_multiplier(),
            'inflation_factor': self.difficulty_curve.get_cost_multiplier(),
            'complexity_factor': self.difficulty_curve.get_detection_multiplier(),
            'total_tier_threshold': self.tier_thresholds[self.current_tier - 1] if self.current_tier < len(self.tier_thresholds) else self.tier_thresholds[-1]
        }
        stats.update(tier_stats)
        return stats

    def get_stats_tier(self):
        tier_multiplier = self.get_tier_multiplier()
        decay = self.difficulty_curve.get_reward_multiplier()
        inflation = self.difficulty_curve.get_cost_multiplier()
        complexity = self.difficulty_curve.get_detection_multiplier()
        return {
            'tier_multiplier': tier_multiplier,
            'decay_value': decay,
            'inflation_value': inflation,
            'complexity_value': complexity
        }

    def get_difficulty_percentage(self):
        tier_multiplier = self.get_tier_multiplier()
        decay = self.difficulty_curve.get_reward_multiplier()
        inflation = self.difficulty_curve.get_cost_multiplier()
        complexity = self.difficulty_curve.get_detection_multiplier()
        percentage = (tier_multiplier * decay * inflation * complexity) / (tier_multiplier * 0.9 ** tier_multiplier)
        return round(percentage * 100, 2)