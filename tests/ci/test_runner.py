"""Runner checks that do not build or start Docker containers."""

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

import yaml

from runner import ExampleRunner


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        self.source = root / 'source'
        (self.source / 'docker_images').mkdir(parents=True)
        self.example = self.source / 'examples' / 'smoke'
        self.example.mkdir(parents=True)
        (self.example / 'main.py').write_text('print("compiled")\n')
        self.manifest = self.example / 'example.yaml'
        self.manifest.write_text(yaml.safe_dump({
            'id': 'smoke', 'script': 'main.py', 'compile': {'standard_args': False}}))
        self.runner = ExampleRunner(self.manifest, root / 'artifacts', 'emuvista-ci-unit')

    def result(self):
        return json.loads((self.runner.artifact_dir / 'result.json').read_text())

    def test_failed_compile_never_calls_docker_or_down(self):
        self.runner.compile = Mock(return_value=3)
        self.runner.build = Mock()
        self.runner.down = Mock()
        self.assertEqual(self.runner.smoke('up'), 1)
        self.runner.build.assert_not_called()
        self.runner.down.assert_not_called()
        self.assertEqual(self.result()['stages']['compile']['exit_code'], 3)

    def test_failed_up_always_cleans_its_project(self):
        self.runner.compile = Mock(return_value=0)
        self.runner.build = Mock(return_value=0)
        self.runner.up = Mock(side_effect=RuntimeError('initializer failed'))
        self.runner.down = Mock(return_value=0)
        self.assertEqual(self.runner.smoke('up'), 1)
        self.runner.down.assert_called_once()
        self.assertIn('initializer failed', self.result()['stages']['up']['error'])

    def test_cleanup_failure_fails_the_test(self):
        for stage in ('compile', 'build', 'up'):
            setattr(self.runner, stage, Mock(return_value=0))
        self.runner.down = Mock(return_value=1)
        self.assertEqual(self.runner.smoke('up'), 1)
        self.assertEqual(self.result()['stages']['down']['exit_code'], 1)

    def test_compile_only_does_not_use_docker(self):
        self.runner.down = Mock()
        self.assertEqual(self.runner.smoke('compile'), 0)
        self.runner.down.assert_not_called()
        self.assertEqual(set(self.result()['stages']), {'compile'})

    def test_command_timeout_keeps_partial_log(self):
        result = self.runner.run_command(
            'build-timeout', [sys.executable, '-u', '-c',
                              'import time; print("partial output"); time.sleep(10)'],
            cwd=self.example, timeout=0.2)
        self.assertEqual(result.returncode, 124)
        log = (self.runner.artifact_dir / 'logs/build-timeout.log').read_text()
        self.assertIn('partial output', log)
        self.assertIn('TIMEOUT', log)

    def test_capture_command_output_for_compose_json(self):
        result = self.runner.run_command('config', [sys.executable, '-c', 'print("{}")'],
                                         cwd=self.example)
        self.assertEqual(json.loads(result.stdout), {})

    def test_generated_bases_build_before_nodes(self):
        self.runner.configuration = Mock(return_value={'services': {
            'node': {'build': {'context': './node'}},
            'base': {'build': {'dockerfile': 'dummies/base'}},
            'upstream': {'image': 'example:1'},
        }})
        self.runner.compose = Mock(return_value=subprocess.CompletedProcess([], 0))
        self.assertEqual(self.runner.build(), 0)
        self.assertEqual([call.args for call in self.runner.compose.call_args_list],
                         [('build-base', 'build', 'base'), ('build-node', 'build', 'node')])

    def test_readiness_checks_all_nodes_and_one_shot_jobs(self):
        services = {
            'base': {'build': {'dockerfile': 'dummies/base'}},
            'app': {'depends_on': {'init': {'condition': 'service_completed_successfully'}}},
            'init': {},
        }
        rows = {'app': {'State': 'running', 'Health': 'healthy'},
                'init': {'State': 'exited', 'ExitCode': 0}}
        self.assertEqual(self.runner.pending(services, rows), [])
        self.assertTrue(self.runner.pending(services, {}))
        rows['app']['Health'] = 'unhealthy'
        self.assertTrue(self.runner.pending(services, rows))
        rows['init']['ExitCode'] = 1
        with self.assertRaisesRegex(RuntimeError, 'initialization failed'):
            self.runner.pending(services, rows)

    def test_long_lived_service_exiting_zero_is_a_failure(self):
        with self.assertRaisesRegex(RuntimeError, 'stopped unexpectedly'):
            self.runner.pending({'app': {}}, {'app': {'State': 'exited', 'ExitCode': 0}})

    def test_down_uses_only_its_project_and_removes_test_volumes(self):
        self.runner.compose = Mock(return_value=subprocess.CompletedProcess([], 0))
        self.runner.down()
        self.assertEqual(self.runner.docker_env()['COMPOSE_PROJECT_NAME'], 'emuvista-ci-unit')
        self.assertEqual(self.runner.compose.call_args.args,
                         ('down', 'down', '--volumes', '--remove-orphans', '--timeout', '20'))

    def test_snapshot_excludes_credentials(self):
        module_path = Path(__file__).resolve().parents[1] / 'run_examples.py'
        spec = importlib.util.spec_from_file_location('run_examples', module_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        (self.source / '.env').write_text('secret')
        (self.source / '.env.local').write_text('secret')
        (self.source / 'model_profiles.json').write_text('secret')
        (self.source / 'main.py').write_text('source')
        destination = Path(self.directory.name) / 'snapshot'
        with patch.object(module, 'ROOT', self.source), patch.object(
                module.subprocess, 'check_output', return_value=b'.env\0.env.local\0model_profiles.json\0main.py\0'):
            module.stage_source(destination)
        self.assertFalse((destination / '.env').exists())
        self.assertFalse((destination / '.env.local').exists())
        self.assertFalse((destination / 'model_profiles.json').exists())
        self.assertEqual((destination / 'main.py').read_text(), 'source')
        self.assertEqual((self.source / '.env').read_text(), 'secret')
        dummy = destination / 'experiments/E99_virtual_world_with_agents/.env'
        self.assertIn('ci-placeholder', dummy.read_text())


if __name__ == '__main__':
    unittest.main()
