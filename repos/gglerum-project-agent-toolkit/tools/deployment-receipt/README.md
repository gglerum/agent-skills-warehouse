# Deployment receipt

Validate exact-revision deployment and deployment-specific health evidence.

Python 3.10+ standard library; a trusted producer of deployment receipts.

```sh
python3 receipt.py deployment.json --sha FULL_40_CHARACTER_SHA --host staging.example.test
```

Receipt fields: `sha`, `host`, nonempty `deploy_id`, timezone-bearing `deployed_at`, and `health` containing `passed: true`, matching `deploy_id`, and timezone-bearing `checked_at` no earlier than deployment. Resolve the actual merged SHA first; do not substitute PR head or a later base HEAD. Exit 0 means fields match, 2 means unconfirmed. The validator cannot authenticate the producer or infer deployment from CI. No dirty application receipt writer was copied.

Copy this complete folder with its ORIGIN.md and licence files. The consuming project's instructions, tools and permissions govern use.
