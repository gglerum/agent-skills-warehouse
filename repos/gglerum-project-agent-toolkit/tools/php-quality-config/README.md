# Php quality config

Detect PHP framework/layout and render reviewable quality configurations without installing or activating tooling.

PHP 8.2+ CLI. Copy the whole folder including namespace directories and MIT licence.

```sh
php generate.php /path/to/php-project > /tmp/php-configs.json
```

Output contains detected settings and file-name/content pairs for PHPStan, Psalm, Rector, Deptrac, CSpell, Gitleaks, Trivy, ZAP and Infection. Existing project files are not overwritten; review the rendered text and select what to install. No Composer plugin, downloads, hook, scanner or service is run. `.quality-tools.json` provides explicit overrides; lists replace rather than merge by index. Keep only intended overrides so new source folders remain detectable.

Generated tool APIs reflect source conventions and must be checked against installed versions, especially Laravel/Rector sets, vendor-dir overrides and DAST runtime requirements. The source package's unverified installer/DAST/deploy orchestration is not included. A rendered ZAP plan does not authorize scanning any target. Tests exercise configuration rendering with synthetic projects, not every external tool's runtime.

Copy this complete folder with its ORIGIN.md and licence files. The consuming project's instructions, tools and permissions govern use.
