# Container status

Read configured Compose project container state and host memory pressure.

Python 3.10+ standard library, Docker CLI access for live snapshots, Linux /proc/meminfo.

```sh
python3 status.py --project example --min-available-mb=1500 --max-swap-pct=75
```

The command runs bounded `docker ps`/`inspect` reads and reports JSON; it does not start containers or mount the daemon socket. Empty container inventory or unavailable memory cannot produce complete healthy evidence. A restart-policy container must be running, and any present Docker health check must be healthy. Thresholds are configurable, not a universal deployment policy. A running container without a health check does not prove application correctness. Test fixtures exercise evaluation; no live daemon was contacted.

Copy this complete folder with its ORIGIN.md and licence files. The consuming project's instructions, tools and permissions govern use.
