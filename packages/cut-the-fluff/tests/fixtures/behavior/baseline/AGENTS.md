# Fixture project

Run the local Python checks with python3 -B -m unittest discover -s checks -p "check_*.py". Do not use a service.

For a ledger CSV, require columns account,amount,currency. Reject duplicate account/currency rows. Validate the complete input before proposing any write; preserve the original on validation failure.

For a failed release, stop the rollout, identify the last signed release receipt, obtain approval for its exact recovery target, restore only after approval, then run the local health checks. Preserve incident evidence. Never disable signature checks.
