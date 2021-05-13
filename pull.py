#!/usr/bin/env python

# Inspired by https://github.com/jupyterhub/nbgitpuller

import os
import shutil
import subprocess
import logging
import argparse
import datetime


def execute_cmd(cmd):
    try:
        os.system(" ".join(cmd))
    except Exception as e:
        raise e


class GitSync(object):

    def __init__(self, git_url, branch_name, repo_dir):
        self.git_url = git_url
        self.branch_name = branch_name
        self.repo_dir = repo_dir

        logging.basicConfig(
            format='[%(asctime)s] %(levelname)s -- %(message)s',
            level=logging.DEBUG
        )

        self.sync()

    def restore_deleted_files(self):
        logging.info('Restoring locally deleted files...')
        deleted_files = subprocess.check_output([
            'git', 'ls-files', '--deleted', '-z'
        ], cwd=self.repo_dir).decode().strip().split('\0')
        for f in deleted_files:
            try:
                execute_cmd(['git', 'checkout', 'origin/{}'.format(self.branch_name), '--', f])
                logging.debug('Restored {}'.format(f))
            except Exception:
                logging.warning('{} may not longer exist upstream'.format(f))

    def move_files(self, files):
        for f in files:
            if os.path.exists(f):
                # if there's a file extension, put the timestamp before it
                ts = datetime.datetime.now().strftime('__%Y%m%d%H%M%S')
                path_head, path_tail = os.path.split(f)
                path_tail = ts.join(os.path.splitext(path_tail))
                new_file_name = os.path.join(path_head, path_tail)
                shutil.move(f, new_file_name)
                logging.info('Moved {} to {} to avoid conflict with upstream'.format(f, new_file_name))

    def find_untracked_local_files(self):
        proc = subprocess.Popen(
            ['git ls-files --others --exclude-standard'],
            stdout=subprocess.PIPE, shell=True
        )
        (output, err) = proc.communicate()
        return [f for f in output.decode("utf-8").split('\n') if len(f) > 0]

    def find_mofified_local_files(self):
        proc = subprocess.Popen(
            ['git ls-tree -r {} --name-only'.format(self.branch_name)],
            stdout=subprocess.PIPE, shell=True
        )
        (output, err) = proc.communicate()
        tracked_files = [f for f in output.decode("utf-8").split('\n') if len(f) > 0]

        modified = []
        for f in tracked_files:
            retcode = os.system('git diff --exit-code {}'.format(f))
            if retcode != 0:
                modified.append(f)

        return modified

    def find_upstream_updates(self, mode):
        logging.info('Get list of files that have been added or modified upstream...')

        def check_upstream(m):
            output = subprocess.check_output([
                'git', 'log', '..origin/{}'.format(self.branch_name),
                '--oneline', '--name-status'
            ], cwd=self.repo_dir).decode()
            files = []
            for line in output.split('\n'):
                if line.startswith(m):
                    f = os.path.relpath(line.split('\t', 1)[1], self.repo_dir)
                    logging.debug('New or modified upstream file: [{}] {}'.format(m, f))
                    files.append(f)

            return files

        if mode == 'A':
            return check_upstream('A')
        elif mode == 'M':
            return check_upstream('M')
        else:
            raise Exception('mode must be either A or M')

    def merge(self):
        logging.info('Merging {} into local clone...'.format(self.branch_name))
        execute_cmd([
            'git',
            '-c', 'user.email=archive@stsci.edu',
            '-c', 'user.name=git-sync',
            'merge',
            #'-Xours',
            '--no-edit',
            'origin/{}'.format(self.branch_name)
        ])

    def prepare_clone(self):
        new_upstream_files = self.find_upstream_updates('A')
        modified_upstream_files = self.find_upstream_updates('M')
        modified_local_files = self.find_mofified_local_files()
        untracked_local_files = self.find_untracked_local_files()

        # upstream files changed, local files have not changed
        # ACTUALLY, PROBABLY DO NOTHING HERE
        #files_to_move = [f for f in modified_upstream_files if f in unmodified_local_files]

        # move certain files to avoid conflicts with upstream
        # - both local and upstream files of the same name have been modified
        # - tracked local files have been modified, upstream files have not been modified
        # - untracked local files have been created, upstream files of the same names have also been created
        files_to_move = [f for f in modified_local_files if f in modified_upstream_files]
        files_to_move = [f for f in modified_local_files if f not in modified_upstream_files]
        files_to_move.extend([f for f in untracked_local_files if f in new_upstream_files])
        self.move_files(files_to_move)

        # local files have been removed, but still exist upstream
        self.restore_deleted_files()

    def update_remotes(self):
        logging.info('Fetching remotes from {}...'.format(self.git_url))
        execute_cmd(['git', 'fetch'])

    def init_repo(self):
        logging.info('Repo {} doesn\'t exist. Cloning...'.format(self.repo_dir))
        execute_cmd(['git', 'clone', '--branch', self.branch_name, self.git_url, self.repo_dir])
        logging.info('Repo {} initialized'.format(self.repo_dir))

    def sync(self):
        if not os.path.exists(self.repo_dir):
            self.init_repo()
        else:
            os.chdir(self.repo_dir)
            self.update_remotes()
            self.prepare_clone()
            self.merge()
        logging.info('Done.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Synchronizes a github repository with a local repository.'
    )
    parser.add_argument('git_url', help='Url of the repo to sync')
    parser.add_argument('branch_name', default='main', help='Branch of repo to sync', nargs='?')
    parser.add_argument('repo_dir', default='.', help='Path to clone repo under', nargs='?')
    args = parser.parse_args()

    GitSync(args.git_url, args.branch_name, args.repo_dir)
