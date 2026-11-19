<?php
declare(strict_types=1);

// Render only. No Composer/plugin/hook activation, downloads or project writes.
require __DIR__.'/Scanner/ProjectScanner.php';
require __DIR__.'/Project.php';
require __DIR__.'/Config/ConfigGenerator.php';

try {
    if ($argc !== 2 || in_array($argv[1], ['-h', '--help'], true)) {
        fwrite(STDERR, "Usage: php generate.php PROJECT_ROOT > configs.json\nRequires PHP 8.2+. Renders configuration; runs no quality tools.\n");
        exit($argc === 2 ? 0 : 2);
    }
    $root = realpath($argv[1]);
    if ($root === false || !is_dir($root)) {
        throw new RuntimeException('Invalid project root');
    }
    foreach (['composer.json', 'package.json', '.quality-tools.json'] as $name) {
        if (is_file($root.'/'.$name)) {
            $data = json_decode((string)file_get_contents($root.'/'.$name), true, 512, JSON_THROW_ON_ERROR);
            if (!is_array($data)) {
                throw new RuntimeException('Expected configuration object');
            }
        }
    }
    $project = \Gglerum\QualityTools\Project::load($root);
    $paths = [...$project->settings['paths']['source'], $project->settings['vendorDir'], $project->settings['reportsDir']];
    if ($project->settings['paths']['tests'] !== null) {
        $paths[] = $project->settings['paths']['tests'];
    }
    foreach ($paths as $path) {
        if (!is_string($path) || !preg_match('~\A[A-Za-z0-9_./-]+\z~', $path) || str_starts_with($path, '/') || in_array('..', explode('/', $path), true)) {
            throw new RuntimeException('Unsafe path in project settings');
        }
    }
    $files = (new \Gglerum\QualityTools\Config\ConfigGenerator($project))->files();
    echo json_encode(['detected' => $project->settings, 'files' => $files], JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES | JSON_THROW_ON_ERROR).PHP_EOL;
} catch (Throwable $e) {
    fwrite(STDERR, 'Configuration unavailable: '.get_class($e).PHP_EOL);
    exit(2);
}
