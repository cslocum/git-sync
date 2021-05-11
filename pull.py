#!/usr/bin/env python

import os
import subprocess
import logging
import time
import argparse
import datetime
#from traitlets import Integer, default
#from traitlets.config import Configurable
#from functools import partial


def execute_cmd(cmd, **kwargs):
    """
    Call given command, yielding output line by line
    """
    yield '$ {}\n'.format(' '.join(cmd))
    kwargs['stdout'] = subprocess.PIPE
    kwargs['stderr'] = subprocess.STDOUT

    proc = subprocess.Popen(cmd, **kwargs)

    # Capture output for logging.
    # Each line will be yielded as text.
    # This should behave the same as .readline(), but splits on `\r` OR `\n`,
    # not just `\n`.
    buf = []

    def flush():
        line = b''.join(buf).decode('utf8', 'replace')
        buf[:] = []
        return line

    c_last = ''
    try:
        for c in iter(partial(proc.stdout.read, 1), b''):
            if c_last == b'\r' and buf and c != b'\n':
                yield flush()
            buf.append(c)
            if c == b'\n':
                yield flush()
            c_last = c
    finally:
        ret = proc.wait()
        if ret != 0:
            raise subprocess.CalledProcessError(ret, cmd)


class GitSync(object):

    def __init__(self, git_url, branch_name, repo_dir):
        self.git_url = git_url
        self.branch_name = branch_name
        self.repo_dir = repo_dir

        self.sync()

    def find_upstream_updates(self, kind):
        logging.info('Get list of files that have been updated/added upstream...')
	cmd = [
            'git', 'log', '..origin/{}'.format(self.branch_name),
            '--oneline', '--name-status'
        ]
        logging.debug('Running: {}'.format(cmd.join(' '))
        output = subprocess.check_output(cmd, cwd=self.repo_dir).decode()
        files = []
        for line in output.split('\n'):
            if line.startswith(kind):
                files.append(os.path.join(self.repo_dir, line.split('\t', 1)[1]))
	logging.info('Modified files: {}'.format(files.join(' ')))

        return files

    def prepare_clone(self):
	# rename any user-created files that have the same names as newly
        # created upstream files
        new_upstream_files = self.find_upstream_updates('A')
        for f in new_upstream_files:
            if os.path.exists(f):
                # if there's a file extension, put the timestamp before it
                ts = datetime.datetime.now().strftime('__%Y%m%d%H%M%S')
                path_head, path_tail = os.path.split(f)
                path_tail = ts.join(os.path.splitext(path_tail))
                new_file_name = os.path.join(path_head, path_tail)
                os.rename(f, new_file_name)
                logging.info('Renamed {} to {} to avoid conflict with upstream'.format(f, new_file_name))

        # reset locally deleted files
        deleted_files = subprocess.check_output([
            'git', 'ls-files', '--deleted', '-z'
        ], cwd=self.repo_dir).decode().strip().split('\0')
	for filename in deleted_files:
            if filename:
                cmd = ['git', 'checkout', 'origin/{}'.format(self.branch_name), '--', filename]
                logging.debug('Running: {}'.format(cmd.join(' '))
                yield from execute_cmd(cmd, cwd=self.repo_dir)

        # find locally modified files and commit them
        local_changes = False
        try:
            subprocess.check_call(['git', 'diff-files', '--quiet'], cwd=self.repo_dir)
        except subprocess.CalledProcessError:
            local_changes = True
	if local_changes:
            yield from execute_cmd([
                'git',
                '-c', 'user.email=archive@stsci.edu',
                '-c', 'user.name=git-sync',
                'commit',
                '-am', 'Automatic commit by git-sync',
                '--allow-empty'
            ], cwd=self.repo_dir)

    def merge(self):
        yield from execute_cmd([
            'git',
            '-c', 'user.email=archive@stsci.edu',
            '-c', 'user.name=git-sync',
            'merge',
            '-Xours', 'origin/{}'.format(self.branch_name)
        ], cwd=self.repo_dir)

    def update_remotes(self):
        logging.info('Fetching removes from {}...'.format(self.repo_dir))
        yield from execute_cmd(['git', 'fetch'], cwd=self.repo_dir)
        logging.info('Done fetching remotes')	

    def init_repo(self):
        logging.info('Repo {} doesn\'t exist. Cloning...'.format(self.repo_dir))
        yield from execute_cmd(
            ['git', 'clone', '--branch', self.branch_name, 'self.git_url, self.repo_dir']
        )
        logging.info('Repo {} initialized'.format(self.repo_dir))

    def sync(self):
	"""
        Pull selected repo from a remote git repository,
        while preserving user changes
        """
        if not os.path.exists(self.repo_dir):
            yield from self.init_repo()
        else:
            self.update_remotes()
            self.prepare_clone()
            self.merge()


   # clone repo if doesn't exist
   # else
       # update_remotes
       # rename_local_untracked
       # reset_deleted_files
       # if repo_is_dirty
           # git commit with special user (auto commit)
    # git merge ... -Xours (favor upstream)




if __name__ == '__main__':
    logging.basicConfig(
        format='[%(asctime)s] %(levelname)s -- %(message)s',
        level=logging.DEBUG
    )

    parser = argparse.ArgumentParser(
        description='Synchronizes a github repository with a local repository.'
    )
    parser.add_argument('git_url', help='Url of the repo to sync')
    parser.add_argument('branch_name', default='main', help='Branch of repo to sync', nargs='?')
    parser.add_argument('repo_dir', default='.', help='Path to clone repo under', nargs='?')
    args = parser.parse_args()

    GitSync(git_url, branch_name, repo_dir).sync(args)
