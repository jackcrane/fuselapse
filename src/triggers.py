class TriggerMatcher:
    def __init__(self, trigger_pairs, initial_states=None):
        self.trigger_pairs = {
            positive_idx: negative_idx
            for positive_idx, negative_idx in trigger_pairs
        }
        self.previous_states = list(initial_states or [])

    def sync_states(self, states):
        self.previous_states = list(states)

    def get_matches(self, previous_states, current_states, current_frame):
        matches = []

        for positive_idx, negative_idx in self.trigger_pairs.items():
            if (
                previous_states[positive_idx]
                and not current_states[positive_idx]
                and current_states[negative_idx]
            ):
                matches.append(current_frame)

        return matches

    def get_matching_frames(self, current_frame, current_states):
        matches = self.get_matches(
            self.previous_states,
            current_states,
            current_frame,
        )

        self.previous_states = list(current_states)
        return matches
