<?php

declare(strict_types=1);

/**
 * Skips `migrate:fresh --seed` in PHPUnit while the test database is still what the last successful run built.
 *
 * RefreshDatabase runs migrate:fresh (and the seeder, with `$seed = true`) once per PHPUnit process; with ~100
 * migrations that is ~88 s per process before the first test. The tests themselves run in transactions that roll
 * back, so the database a finished run leaves behind is the database the next run would rebuild.
 *
 * Fingerprint = sha256 over database/migrations, database/seeders and database/factories (names and contents),
 * the extra paths (default config/permission.php; see install()) and the names in the database's `migrations` table. It is stored in the table `toolchain_test_db_fingerprint` of the
 * test database itself, so it follows the database: a per-worktree database (`.testing-database`) and each
 * `--parallel` worker database (`<name>_test_<token>`) has its own, and dropping a database drops its fingerprint.
 * Anything else (no table, other hash, migrations table differs from the files, any error) means: run the fresh
 * migration as usual. FORCE_FRESH_DB=1 forces it.
 *
 * Loading: do not `require_once` this file. Let Composer load it, in composer.json of the repo:
 *
 *     "autoload-dev": { "files": ["utils/shared/scripts/laravel/TestDatabaseFingerprint.php"] }
 *
 * vendor/autoload.php then defines the class under any phpunit.xml, including a CI one that replaces the bootstrap.
 * The file only declares the class; nothing happens until install() is called.
 *
 * Use from tests/bootstrap.php, after DB_DATABASE is final (after the .testing-database override):
 *
 *     \Toolchain\TestDatabaseFingerprint::install(dirname(__DIR__), extraPaths: ['config/permission.php', 'app/Enums']);
 *
 * If CI does not run tests/bootstrap.php, install() is never called there and CI migrates fresh, as before.
 *
 * Do not use it for tests that commit data outside a transaction (DatabaseMigrations, Dusk): they leave the
 * database dirty. Run those with FORCE_FRESH_DB=1.
 */

namespace Toolchain;

final class TestDatabaseFingerprint
{
    private const TABLE = 'toolchain_test_db_fingerprint';

    /** Seeder inputs outside database/ that always count; a repo adds its own through install(). */
    public const DEFAULT_EXTRA_PATHS = ['config/permission.php'];

    private static string $basePath = '';

    /**
     * Pure part: the hash for the given project folder and applied migration names.
     *
     * @param  list<string>  $appliedMigrations  names from the `migrations` table
     * @param  list<string>  $extraPaths  files or folders (relative to $basePath) that seeders read; a folder counts by its .php files
     */
    public static function compute(string $basePath, array $appliedMigrations, array $extraPaths = self::DEFAULT_EXTRA_PATHS): string
    {
        $parts = [];
        $extraPaths = array_values(array_unique($extraPaths));
        sort($extraPaths);
        foreach ($extraPaths as $extra) {
            $path = $basePath.'/'.ltrim($extra, '/');
            if (is_file($path)) {
                $parts[] = 'extra/'.$extra.':'.hash_file('sha256', $path);
            } elseif (is_dir($path)) {
                $files = self::phpFiles($path);
                sort($files);
                foreach ($files as $file) {
                    $parts[] = 'extra/'.$extra.'/'.substr($file, strlen($path) + 1).':'.hash_file('sha256', $file);
                }
                $parts[] = 'extra/'.$extra.':dir';
            } else {
                $parts[] = 'extra/'.$extra.':missing';
            }
        }
        foreach (['migrations', 'seeders', 'factories'] as $folder) {
            $directory = $basePath.'/database/'.$folder;
            $files = is_dir($directory) ? self::phpFiles($directory) : [];
            sort($files);
            foreach ($files as $file) {
                $parts[] = $folder.'/'.substr($file, strlen($directory) + 1).':'.hash_file('sha256', $file);
            }
        }
        sort($appliedMigrations);

        return hash('sha256', implode("\n", $parts)."\n--\n".implode("\n", $appliedMigrations));
    }

    /**
     * The migrations table must hold exactly the migration files: a half-migrated or older database never matches.
     *
     * @param  list<string>  $appliedMigrations
     */
    public static function migrationsMatchFiles(string $basePath, array $appliedMigrations): bool
    {
        $names = array_map(static fn (string $file): string => basename($file, '.php'), self::phpFiles($basePath.'/database/migrations'));
        sort($names);
        sort($appliedMigrations);

        return $names !== [] && $names === $appliedMigrations;
    }

    /**
     * Tells RefreshDatabase the database is already migrated and seeded when the stored fingerprint is current,
     * and records the fingerprint at shutdown after a run that migrated it.
     */
    /**
     * @param  list<string>  $extraPaths  files/folders besides database/ that the seeders read (defaults to DEFAULT_EXTRA_PATHS;
     *                                    pass the full list you want, e.g. ['config/permission.php', 'app/Enums'])
     */
    public static function install(string $basePath, array $extraPaths = self::DEFAULT_EXTRA_PATHS): void
    {
        self::$basePath = $basePath;
        if (self::env('FORCE_FRESH_DB') === '1' || ! class_exists(\Illuminate\Foundation\Testing\RefreshDatabaseState::class)) {
            return;
        }

        try {
            $pdo = self::connect();
            $applied = self::appliedMigrations($pdo);
            $current = self::compute($basePath, $applied, $extraPaths);
            $stored = self::stored($pdo);
        } catch (\Throwable) {
            $pdo = null;
            $current = $stored = null;
            $applied = [];
        }

        if ($pdo !== null && $stored !== null && $stored === $current && self::migrationsMatchFiles($basePath, $applied)) {
            \Illuminate\Foundation\Testing\RefreshDatabaseState::$migrated = true;

            return;
        }

        // Not current: this run migrates as usual. Record the result when it did (whatever the tests report).
        register_shutdown_function(static function () use ($basePath, $extraPaths): void {
            if (! \Illuminate\Foundation\Testing\RefreshDatabaseState::$migrated) {
                return;
            }
            try {
                $pdo = self::connect();
                $applied = self::appliedMigrations($pdo);
                if (! self::migrationsMatchFiles($basePath, $applied)) {
                    return;
                }
                $pdo->exec('CREATE TABLE IF NOT EXISTS '.self::TABLE.' (hash VARCHAR(64) NOT NULL)');
                $pdo->exec('DELETE FROM '.self::TABLE);
                $pdo->prepare('INSERT INTO '.self::TABLE.' (hash) VALUES (?)')->execute([self::compute($basePath, $applied, $extraPaths)]);
            } catch (\Throwable) {
                // No fingerprint stored: the next run migrates, which is only slower.
            }
        });
    }

    private static function connect(): \PDO
    {
        $keys = ['DB_URL', 'DATABASE_URL', 'DB_DATABASE', 'DB_HOST', 'DB_PORT', 'DB_SOCKET', 'DB_USERNAME', 'DB_PASSWORD'];
        $parameters = self::connectionParameters(array_combine($keys, array_map(self::env(...), $keys)), self::env('TEST_TOKEN'));

        return new \PDO($parameters['dsn'], $parameters['username'], $parameters['password'], [\PDO::ATTR_ERRMODE => \PDO::ERRMODE_EXCEPTION]);
    }

    /**
     * Pure part: DSN and credentials the way the app's mysql connection resolves them.
     *
     * A URL (DB_URL, or DATABASE_URL of older apps) overrides the separate keys, as in Laravel's config; a socket
     * (DB_SOCKET, or `?unix_socket=` in the URL) replaces host and port. $token is the paratest worker token:
     * Laravel appends _test_<token> to the database name.
     *
     * @param  array<string, string>  $env  DB_URL, DATABASE_URL, DB_DATABASE, DB_HOST, DB_PORT, DB_SOCKET, DB_USERNAME, DB_PASSWORD (missing = '')
     * @return array{dsn: string, username: string, password: string}
     */
    public static function connectionParameters(array $env, string $token = ''): array
    {
        $database = $env['DB_DATABASE'] ?? '';
        $host = ($env['DB_HOST'] ?? '') ?: '127.0.0.1';
        $port = ($env['DB_PORT'] ?? '') ?: '3306';
        $socket = $env['DB_SOCKET'] ?? '';
        $username = $env['DB_USERNAME'] ?? '';
        $password = $env['DB_PASSWORD'] ?? '';

        $url = ($env['DB_URL'] ?? '') ?: ($env['DATABASE_URL'] ?? '');
        $parts = $url !== '' ? parse_url($url) : false;
        if (is_array($parts)) {
            $host = $parts['host'] ?? $host;
            $port = isset($parts['port']) ? (string) $parts['port'] : $port;
            $username = isset($parts['user']) ? rawurldecode($parts['user']) : $username;
            $password = isset($parts['pass']) ? rawurldecode($parts['pass']) : $password;
            if (isset($parts['path']) && ltrim($parts['path'], '/') !== '') {
                $database = rawurldecode(ltrim($parts['path'], '/'));
            }
            parse_str($parts['query'] ?? '', $query);
            if (isset($query['unix_socket']) && is_string($query['unix_socket'])) {
                $socket = $query['unix_socket'];
            }
        }

        if ($token !== '') {
            $database .= '_test_'.$token;
        }
        $dsn = $socket !== ''
            ? sprintf('mysql:unix_socket=%s;dbname=%s', $socket, $database)
            : sprintf('mysql:host=%s;port=%s;dbname=%s', $host, $port, $database);

        return ['dsn' => $dsn, 'username' => $username, 'password' => $password];
    }

    /** Value from phpunit.xml / the shell (wins) or else .env; Laravel has not loaded .env yet in the bootstrap. */
    private static function env(string $name): string
    {
        static $dotenv = null;
        if ($dotenv === null) {
            $dotenv = [];
            $file = self::$basePath.'/.env';
            if (is_file($file) && class_exists(\Dotenv\Dotenv::class)) {
                $dotenv = \Dotenv\Dotenv::parse((string) file_get_contents($file));
            }
        }
        $value = $_ENV[$name] ?? $_SERVER[$name] ?? getenv($name);

        return (string) (($value !== false && $value !== null) ? $value : ($dotenv[$name] ?? ''));
    }

    /** @return list<string> */
    private static function appliedMigrations(\PDO $pdo): array
    {
        return array_map('strval', $pdo->query('SELECT migration FROM migrations')->fetchAll(\PDO::FETCH_COLUMN));
    }

    private static function stored(\PDO $pdo): ?string
    {
        $row = $pdo->query('SELECT hash FROM '.self::TABLE.' LIMIT 1')->fetchColumn();

        return is_string($row) ? $row : null;
    }

    /** @return list<string> */
    private static function phpFiles(string $directory): array
    {
        if (! is_dir($directory)) {
            return [];
        }
        $files = [];
        foreach (new \RecursiveIteratorIterator(new \RecursiveDirectoryIterator($directory, \FilesystemIterator::SKIP_DOTS)) as $file) {
            if ($file->isFile() && $file->getExtension() === 'php') {
                $files[] = $file->getPathname();
            }
        }

        return $files;
    }
}
