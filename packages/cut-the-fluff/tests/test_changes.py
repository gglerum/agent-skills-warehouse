"""Exact approval and recovery tests; no real project writes or agent behavior trials."""
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import unittest
from unittest.mock import patch

from test_report import ReportTests, PACKAGE
from changes import run, sha, fingerprint, load, validate_journal


report_setup = ReportTests.setUp


class ChangeTests(unittest.TestCase):
    put = ReportTests.put
    args = ReportTests.args
    run_report = ReportTests.run_report
    decision = ReportTests.decision
    def setUp(self):
        report_setup(self)
        self.state = self.base / 'recovery'
        self.report_path = self.base / 'report.json'
        self.approval_path = self.base / 'approval.json'
        self.original = (self.project / 'CLAUDE.md').read_bytes()
        self.prepare()

    def prepare(self, multiple=False):
        review_path = self.decision(patch={'path':'CLAUDE.md', 'old':'Read [missing](missing.md).\n', 'new':''})
        if multiple:
            review = json.loads(Path(review_path).read_text())
            other = copy.deepcopy(review['decisions'][0])
            other.update(patch={'path':'guide.md','old':'Keep recovery instructions.','new':'Retain recovery instructions.'}, evidence_refs=['document:2','document:6'])
            review['decisions'].append(other)
            Path(review_path).write_text(json.dumps(review))
        self.result = self.run_report('--review',review_path,'--include-patches')
        self.report_path.write_text(json.dumps(self.result))
        self.approval = dict(schema_version='1.0', kind='change_approval', scope='project', project=str(self.project.resolve()),
                             report_sha256=sha(self.report_path.read_bytes()), selections=[{k:c[k] for k in ('finding_id','change_sha256')} for c in self.result['changes']])
        self.write_approval()

    def write_approval(self):
        self.approval_path.write_text(json.dumps(self.approval))

    def args_change(self, command='apply'):
        from test_inventory import mod
        argv=[command,'--project',str(self.project),'--state',str(self.state)]
        if command=='apply':
            argv += ['--report',str(self.report_path),'--approval',str(self.approval_path)]
        return mod.parser().parse_args(argv)

    def apply(self):
        return run(self.args_change())

    def rollback(self):
        return run(self.args_change('rollback'))

    def test_exact_once_manifest_and_rollback(self):
        os.chmod(self.project / 'CLAUDE.md',0o640)
        self.assertEqual('applied', self.apply()['status'])
        self.assertEqual(b'@guide.md\n', (self.project/'CLAUDE.md').read_bytes())
        self.assertEqual('already_applied', self.apply()['status'])
        journal,_=load(self.state/'manifest.json')
        from report import validate
        from test_inventory import SCHEMA
        validate(journal,SCHEMA['$defs']['change_manifest'],SCHEMA['$defs'])
        validate_journal(journal,self.project)
        self.assertEqual(0o700, self.state.stat().st_mode & 0o777)
        self.assertEqual(0o600, (self.state/'manifest.json').stat().st_mode & 0o777)
        self.assertEqual(1,self.rollback()['changed_files'])
        self.assertEqual(self.original,(self.project/'CLAUDE.md').read_bytes())
        self.assertEqual(0o640,(self.project/'CLAUDE.md').stat().st_mode & 0o777)
        self.assertEqual(0,self.rollback()['changed_files'])
        with self.assertRaises(ValueError): self.apply()

    def test_partial_approval_preserves_unselected_files(self):
        self.prepare(multiple=True)
        self.approval['selections']=self.approval['selections'][:1]
        self.write_approval()
        before=(self.project/'guide.md').read_bytes()
        self.apply()
        self.assertEqual(before,(self.project/'guide.md').read_bytes())

    def test_unapproved_mismatched_or_global_selection_refused(self):
        for field,value in [('selections',[]),('scope','global'),('report_sha256','wrong'),('project','/other')]:
            original=copy.deepcopy(self.approval)
            self.approval[field]=value; self.write_approval()
            with self.assertRaises(ValueError): self.apply()
            self.assertFalse(self.state.exists())
            self.approval=original
        self.approval['selections'][0]['change_sha256']='wrong'; self.write_approval()
        with self.assertRaises(ValueError): self.apply()
        self.assertEqual(self.original,(self.project/'CLAUDE.md').read_bytes())

    def test_report_bytes_and_change_integrity_bound(self):
        self.report_path.write_text(self.report_path.read_text()+'\n')
        with self.assertRaises(ValueError): self.apply()
        self.approval['report_sha256']=sha(self.report_path.read_bytes());self.write_approval()
        self.result['changes'][0]['new']='unapproved text'
        self.report_path.write_text(json.dumps(self.result))
        self.approval['report_sha256']=sha(self.report_path.read_bytes());self.write_approval()
        with self.assertRaises(ValueError): self.apply()

    def test_stale_second_file_preflights_before_any_write(self):
        self.prepare(multiple=True)
        self.put('guide.md','concurrent change\n')
        with self.assertRaises(ValueError): self.apply()
        self.assertEqual(self.original,(self.project/'CLAUDE.md').read_bytes())
        self.assertFalse(self.state.exists())

    def test_same_file_alternatives_and_duplicate_selection_refused(self):
        self.approval['selections'] *= 2; self.write_approval()
        with self.assertRaises(ValueError): self.apply()
        self.assertFalse(self.state.exists())

    def test_partial_failure_has_durable_backups_and_recovers(self):
        self.prepare(multiple=True)
        import changes
        actual=changes.replace
        calls=[]
        def fail_second(*args):
            calls.append(1)
            if len(calls)==2: raise OSError('injected failure')
            actual(*args)
        with patch('changes.replace',side_effect=fail_second), self.assertRaises(OSError): self.apply()
        self.assertNotEqual(self.original,(self.project/'CLAUDE.md').read_bytes())
        journal,_=load(self.state/'manifest.json')
        self.assertEqual('prepared',journal['status'])
        with self.assertRaises(ValueError): self.apply()
        self.assertEqual(1,self.rollback()['changed_files'])
        self.assertEqual(self.original,(self.project/'CLAUDE.md').read_bytes())

    def test_rollback_conflict_preflights_every_file(self):
        self.prepare(multiple=True);self.apply()
        changed=(self.project/'CLAUDE.md').read_bytes()
        self.put('guide.md','later work\n')
        with self.assertRaises(ValueError):self.rollback()
        self.assertEqual(changed,(self.project/'CLAUDE.md').read_bytes())
        self.assertEqual('later work\n',(self.project/'guide.md').read_text())
        with self.assertRaises(ValueError):self.apply()

    def test_filesystem_without_xattr_support_applies(self):
        # WSL drvfs/9p and FAT may raise ENOTSUP; such files cannot carry xattrs.
        import errno
        with patch('os.listxattr', side_effect=OSError(errno.ENOTSUP, 'Operation not supported')):
            self.assertEqual('applied', self.apply()['status'])
            self.assertEqual(1, self.rollback()['changed_files'])
        self.assertEqual(self.original, (self.project/'CLAUDE.md').read_bytes())
        # Other xattr errors still refuse, before any project write.
        self.state = self.base / 'recovery-2'
        with patch('os.listxattr', side_effect=OSError(13, 'Permission denied')):
            with self.assertRaises(OSError): self.apply()
        self.assertEqual(self.original, (self.project/'CLAUDE.md').read_bytes())

    def test_state_on_mode_ignoring_filesystem_refused_before_project_write(self):
        real_mkdir = Path.mkdir
        def drvfs_mkdir(path, mode=0o777, *args, **kwargs):
            real_mkdir(path, mode, *args, **kwargs)
            os.chmod(path, 0o777)  # what WSL /mnt/<drive> reports
        with patch.object(Path, 'mkdir', drvfs_mkdir):
            with self.assertRaisesRegex(ValueError, 'Linux filesystem'): self.apply()
        self.assertFalse(self.state.exists())
        self.assertEqual(self.original, (self.project/'CLAUDE.md').read_bytes())

    def test_metadata_change_and_corrupt_backups_refused(self):
        self.apply()
        os.chmod(self.project/'CLAUDE.md',0o600)
        with self.assertRaises(ValueError):self.rollback()
        os.chmod(self.project/'CLAUDE.md',0o644)
        j,_=load(self.state/'manifest.json');j['entries'][0]['before_base64']='YmFk'
        (self.state/'manifest.json').write_text(json.dumps(j))
        with self.assertRaises(ValueError):self.rollback()

    def test_links_special_files_reserved_and_state_boundaries(self):
        path=self.project/'CLAUDE.md'
        path.unlink();path.symlink_to(self.base/'outside')
        (self.base/'outside').write_bytes(self.original)
        with self.assertRaises(ValueError):self.apply()
        path.unlink();os.mkfifo(path)
        with self.assertRaises(ValueError):self.apply()
        path.unlink();path.write_bytes(self.original)
        os.link(path,self.project/'alias')
        with self.assertRaises(ValueError):self.apply()
        (self.project/'alias').unlink()
        self.state=self.project/'state'
        with self.assertRaises(ValueError):self.apply()

    def test_immediate_concurrent_edit_refused_with_backup(self):
        import changes
        actual=changes.replace
        def concurrent(root,entry,*args):
            self.put(entry['path'],'new user work')
            actual(root,entry,*args)
        with patch('changes.replace',side_effect=concurrent), self.assertRaises(ValueError):self.apply()
        self.assertEqual('new user work',(self.project/'CLAUDE.md').read_text())
        with self.assertRaises(ValueError):self.rollback()

    def test_exact_crlf_and_missing_newline(self):
        self.put('CLAUDE.md','before\r\nlast')
        # Construct proposal over exact decoded bytes, not universal-newline reads.
        from changes import proposal
        c=proposal('finding:1','CLAUDE.md','before\r\nlast','before','after')
        self.result['changes']=[c]
        self.report_path.write_text(json.dumps(self.result))
        self.approval.update(report_sha256=sha(self.report_path.read_bytes()),selections=[{k:c[k] for k in ('finding_id','change_sha256')}]);self.write_approval()
        self.apply();self.assertEqual(b'after\r\nlast',(self.project/'CLAUDE.md').read_bytes())
        self.rollback();self.assertEqual(b'before\r\nlast',(self.project/'CLAUDE.md').read_bytes())

    def test_relocated_cli_requires_approval_and_recovers(self):
        dest=self.base/'copied';shutil.copytree(PACKAGE,dest)
        command=[sys.executable,'-B','-I',str(dest/'inventory.py')]
        for argv in (['apply'],['apply','--project',str(self.project),'--state',str(self.state),'--report',str(self.report_path)]):
            r=subprocess.run(command+argv,cwd='/',capture_output=True,text=True,timeout=10)
            self.assertEqual(2,r.returncode);self.assertEqual('',r.stdout)
        args=['--project',str(self.project),'--state',str(self.state)]
        r=subprocess.run(command+['apply',*args,'--report',str(self.report_path),'--approval',str(self.approval_path)],cwd='/',capture_output=True,text=True,timeout=10)
        self.assertEqual(0,r.returncode,r.stderr)
        r=subprocess.run(command+['rollback',*args],cwd='/',capture_output=True,text=True,timeout=10)
        self.assertEqual(0,r.returncode,r.stderr)
        self.assertEqual(self.original,(self.project/'CLAUDE.md').read_bytes())


    def test_same_journal_lock_refuses_parallel_recovery(self):
        import fcntl
        self.apply()
        fd=os.open(self.state,os.O_RDONLY|os.O_DIRECTORY)
        try:
            fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
            with self.assertRaises(OSError):self.rollback()
        finally:
            os.close(fd)
        self.rollback()

    def test_interrupted_rollback_can_resume(self):
        self.prepare(multiple=True);self.apply()
        import changes
        actual=changes.replace
        calls=[]
        def fail_second(*args):
            calls.append(1)
            if len(calls)==2:raise OSError('interrupted rollback')
            actual(*args)
        with patch('changes.replace',side_effect=fail_second),self.assertRaises(OSError):self.rollback()
        self.assertEqual(1,self.rollback()['changed_files'])
        self.assertEqual(self.original,(self.project/'CLAUDE.md').read_bytes())

    def test_no_project_write_if_initial_manifest_fails(self):
        with patch('changes.save',side_effect=OSError('disk full')),self.assertRaises(OSError):self.apply()
        self.assertEqual(self.original,(self.project/'CLAUDE.md').read_bytes())

    def test_xattrs_refused_instead_of_dropped(self):
        path=self.project/'CLAUDE.md'
        try:os.setxattr(path,'user.cut_the_fluff_test',b'preserve')
        except OSError:self.skipTest('filesystem has no user xattrs')
        with self.assertRaises(ValueError):self.apply()
        self.assertEqual(b'preserve',os.getxattr(path,'user.cut_the_fluff_test'))

    def test_report_without_new_proposals_cannot_be_applied(self):
        del self.result['changes']
        self.report_path.write_text(json.dumps(self.result))
        self.approval['report_sha256']=sha(self.report_path.read_bytes());self.write_approval()
        with self.assertRaises(ValueError):self.apply()
        self.assertFalse(self.state.exists())

# Avoid rediscovering the imported report test class in this module.
del ReportTests
