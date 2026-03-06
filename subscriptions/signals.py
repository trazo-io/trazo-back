# Usage tracking (productions, storage) is computed dynamically in
# SubscriptionSerializer._compute_used_productions() and _compute_used_storage_gb().
# No signals are needed — the model fields used_productions and used_storage_gb
# are stale counters that are not used for enforcement.
