# Ledger import

For a ledger CSV, require columns account,amount,currency. Reject duplicate account/currency rows. Validate the complete input before proposing any write; preserve the original on validation failure.
