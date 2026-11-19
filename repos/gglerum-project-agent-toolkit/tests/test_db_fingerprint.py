import json
import os
import subprocess
import tempfile
import unittest

SCRIPT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'tools', 'laravel-tests', 'TestDatabaseFingerprint.php'))


class TestDatabaseFingerprintTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, path, body='<?php // x'):
        full = os.path.join(self.base, path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, 'w', encoding='utf-8') as handle:
            handle.write(body)

    def php(self, method, applied):
        code = (
            "require $argv[1]; echo json_encode(\\Toolchain\\TestDatabaseFingerprint::{}($argv[2], json_decode($argv[3], true)));"
        ).format(method)
        result = subprocess.run(
            ['php', '-r', code, SCRIPT, self.base, json.dumps(applied)],
            capture_output=True, text=True, check=True,
        )
        return json.loads(result.stdout)

    def test_same_files_and_migrations_give_the_same_hash_in_any_order(self):
        self.write('database/migrations/2024_01_01_000000_a.php')
        self.write('database/migrations/2024_01_02_000000_b.php')
        first = self.php('compute', ['2024_01_01_000000_a', '2024_01_02_000000_b'])
        again = self.php('compute', ['2024_01_02_000000_b', '2024_01_01_000000_a'])

        self.assertEqual(first, again)

    def test_changed_migration_seeder_or_factory_changes_the_hash(self):
        self.write('database/migrations/2024_01_01_000000_a.php')
        self.write('database/seeders/DatabaseSeeder.php')
        self.write('database/factories/UserFactory.php')
        base = self.php('compute', ['2024_01_01_000000_a'])

        for path in ('database/migrations/2024_01_01_000000_a.php', 'database/seeders/DatabaseSeeder.php', 'database/factories/UserFactory.php'):
            self.write(path, '<?php // changed ' + path)
            changed = self.php('compute', ['2024_01_01_000000_a'])
            self.assertNotEqual(base, changed, path)
            self.write(path)
            self.assertEqual(base, self.php('compute', ['2024_01_01_000000_a']), path)

    def test_other_applied_migrations_change_the_hash(self):
        self.write('database/migrations/2024_01_01_000000_a.php')

        self.assertNotEqual(
            self.php('compute', ['2024_01_01_000000_a']),
            self.php('compute', ['2024_01_01_000000_a', 'old_removed_migration']),
        )

    def test_default_extra_path_config_permission_counts(self):
        self.write('database/migrations/2024_01_01_000000_a.php')
        without = self.php('compute', ['2024_01_01_000000_a'])
        self.write('config/permission.php', '<?php return [];')
        with_file = self.php('compute', ['2024_01_01_000000_a'])
        self.write('config/permission.php', '<?php return ["x"];')

        self.assertNotEqual(without, with_file)
        self.assertNotEqual(with_file, self.php('compute', ['2024_01_01_000000_a']))

    def test_configurable_extra_paths_file_and_folder(self):
        self.write('database/migrations/2024_01_01_000000_a.php')
        self.write('app/Enums/Role.php')
        self.write('other.txt', 'not php')
        applied = '["2024_01_01_000000_a"]'

        def compute(paths):
            code = "require $argv[1]; echo json_encode(\\Toolchain\\TestDatabaseFingerprint::compute($argv[2], json_decode($argv[3], true), json_decode($argv[4], true)));"
            out = subprocess.run(['php', '-r', code, SCRIPT, self.base, applied, json.dumps(paths)], capture_output=True, text=True, check=True)
            return json.loads(out.stdout)

        plain = compute([])
        with_folder = compute(['app/Enums'])
        self.assertNotEqual(plain, with_folder)
        self.assertEqual(with_folder, compute(['app/Enums', 'app/Enums']))
        self.write('app/Enums/Role.php', '<?php // changed')
        self.assertNotEqual(with_folder, compute(['app/Enums']))
        self.assertEqual(plain, compute([]))  # not listed: ignored
        self.assertNotEqual(compute([]), compute(['other.txt']))  # a listed file that is not .php still counts

    def connection(self, env, token=''):
        code = "require $argv[1]; echo json_encode(\\Toolchain\\TestDatabaseFingerprint::connectionParameters(json_decode($argv[2], true), $argv[3]));"
        out = subprocess.run(['php', '-r', code, SCRIPT, json.dumps(env), token], capture_output=True, text=True, check=True)
        return json.loads(out.stdout)

    def test_dsn_from_separate_keys_with_defaults_and_worker_token(self):
        self.assertEqual(
            {'dsn': 'mysql:host=127.0.0.1;port=3306;dbname=app', 'username': 'u', 'password': 'p'},
            self.connection({'DB_DATABASE': 'app', 'DB_USERNAME': 'u', 'DB_PASSWORD': 'p'}),
        )
        self.assertEqual('mysql:host=db;port=3307;dbname=app_test_2', self.connection({'DB_DATABASE': 'app', 'DB_HOST': 'db', 'DB_PORT': '3307'}, '2')['dsn'])

    def test_dsn_uses_the_socket_when_set(self):
        result = self.connection({'DB_DATABASE': 'app', 'DB_HOST': 'db', 'DB_SOCKET': '/run/mysqld/mysqld.sock'}, '1')

        self.assertEqual('mysql:unix_socket=/run/mysqld/mysqld.sock;dbname=app_test_1', result['dsn'])

    def test_url_overrides_the_separate_keys(self):
        result = self.connection({
            'DB_URL': 'mysql://us%40er:pa%2Fss@dbhost:3399/fromurl', 'DB_DATABASE': 'ignored', 'DB_HOST': 'ignored',
            'DB_USERNAME': 'ignored', 'DB_PASSWORD': 'ignored',
        })

        self.assertEqual({'dsn': 'mysql:host=dbhost;port=3399;dbname=fromurl', 'username': 'us@er', 'password': 'pa/ss'}, result)

    def test_url_socket_query_and_unparsable_url(self):
        self.assertEqual('mysql:unix_socket=/s.sock;dbname=d', self.connection({'DATABASE_URL': 'mysql://u:p@localhost/d?unix_socket=/s.sock'})['dsn'])
        self.assertEqual('mysql:host=h;port=3306;dbname=d', self.connection({'DB_URL': 'http:///', 'DB_DATABASE': 'd', 'DB_HOST': 'h'})['dsn'])

    def test_migrations_table_must_equal_the_files(self):
        self.write('database/migrations/2024_01_01_000000_a.php')
        self.write('database/migrations/2024_01_02_000000_b.php')

        self.assertTrue(self.php('migrationsMatchFiles', ['2024_01_02_000000_b', '2024_01_01_000000_a']))
        self.assertFalse(self.php('migrationsMatchFiles', ['2024_01_01_000000_a']))
        self.assertFalse(self.php('migrationsMatchFiles', ['2024_01_01_000000_a', '2024_01_02_000000_b', 'extra']))
        self.assertFalse(self.php('migrationsMatchFiles', []))

    def test_no_migration_files_never_matches(self):
        self.assertFalse(self.php('migrationsMatchFiles', []))

    def test_install_without_laravel_or_database_is_a_no_op(self):
        # No RefreshDatabaseState class (and no database): must neither throw nor output anything.
        result = subprocess.run(
            ['php', '-r', "require $argv[1]; \\Toolchain\\TestDatabaseFingerprint::install($argv[2]);", SCRIPT, self.base],
            capture_output=True, text=True,
        )

        self.assertEqual(0, result.returncode)
        self.assertEqual('', result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
