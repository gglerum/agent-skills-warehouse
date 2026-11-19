# Throwaway container

Run one command in a disposable container as the host user, with the host's git identity, so commits and checks use the toolchain the project's hooks need.

Bash, Git and a container CLI (docker by default). Copy the entire folder. The script never builds, pulls or starts a service; the project supplies the image.

```sh
CONTAINER_IMAGE=my-dev-image bash run_in_container.sh git commit -m "message"
CONTAINER_IMAGE=my-dev-image bash run_in_container.sh npm test
CONTAINER_DRY_RUN=1 CONTAINER_IMAGE=my-dev-image bash run_in_container.sh ls   # print the command only
```

The repository is mounted at `/workspace` and runs as the host user and group, so files it writes belong to the user. Git author and committer come from the host `git config`. In a git worktree the shared git directory and the main checkout's `CONTAINER_SHARED_DIRS` (default `vendor node_modules`) are mounted too, which makes package-manager and linter caches visible without copies or symlinks. `CONTAINER_EXTRA_ARGS` adds ports, networks or environment values.

Safety: it mounts the working directory read-write and, in a worktree, the shared git directory read-write; treat commands as having the same power over the repository as the user. No credentials or environment variables are forwarded. Use `CONTAINER_DRY_RUN=1` to inspect the command, and test with a harmless command before wiring it into a skill or hook.

Copy this complete folder with its ORIGIN.md and licence files. The consuming project's instructions, tools and permissions govern use.
