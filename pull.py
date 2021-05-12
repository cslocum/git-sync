#!/usr/bin/env python

# Inspired by https://github.com/jupyterhub/nbgitpuller

import os
import shutil
import subprocess
import logging
import argparse
import datetime


def execute_cmd(cmd, **kwargs):
    try:
        cwd = kwargs.get("cwd")
        here = os.getcwd()
        if cwd:
            os.chdir(cwd)
        os.system(" ".join(cmd))
        os.chdir(here)
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

    def find_upstream_updates(self, kind):
        logging.info('Get list of files that have been updated/added upstream...')
        cmd = [
            'git', 'log', '..origin/{}'.format(self.branch_name),
            '--oneline', '--name-status'
        ]
        output = subprocess.check_output(cmd, cwd=self.repo_dir).decode()
        files = []
        for line in output.split('\n'):
            if line.startswith(kind):
                files.append(line.split('\t', 1)[1])
        
        return files

    def merge(self):
        logging.info('Merging {} into local clone...'.format(self.branch_name))
        execute_cmd([
            'git',
            '-c', 'user.email=archive@stsci.edu',
            '-c', 'user.name=git-sync',
            'merge',
            '-Xours',
            '--no-edit',
            'origin/{}'.format(self.branch_name)
        ], cwd=self.repo_dir)

    def prepare_clone(self):
    	# rename any user-created files that have the same names as newly
        # created upstream files
        logging.info('Backing up any conflicting user-created files...')
        new_upstream_files = self.find_upstream_updates('A')
        self.move_files(new_upstream_files)

        logging.info('Renaming modified local files...')
        proc = subprocess.Popen(
            ['git status | grep modified'],
            stdout=subprocess.PIPE, shell=True
        )
        (output, err) = proc.communicate()
        lines = output.decode("utf-8").split('\n')
        changed_files = [f.strip('\n').split()[-1] for f in lines if len(f) > 0]
        if len(changed_files) > 0:
            self.move_files(changed_files)

        logging.info('Retrieving locally deleted files...')
        deleted_files = subprocess.check_output([
            'git', 'ls-files', '--deleted', '-z'
        ], cwd=self.repo_dir).decode().strip().split('\0')
        for filename in deleted_files:
            if filename:
                execute_cmd(
                    ['git', 'checkout', 'origin/{}'.format(self.branch_name), '--', filename],
                    cwd=self.repo_dir
                )

    def update_remotes(self):
        logging.info('Fetching remotes from {}...'.format(self.git_url))
        execute_cmd(['git', 'fetch'], cwd=self.repo_dir)

    def init_repo(self):
        logging.info('Repo {} doesn\'t exist. Cloning...'.format(self.repo_dir))
        execute_cmd(['git', 'clone', '--branch', self.branch_name, self.git_url, self.repo_dir])
        logging.info('Repo {} initialized'.format(self.repo_dir))

    def sync(self):
        if not os.path.exists(self.repo_dir):
            self.init_repo()
        else:
            self.update_remotes()
            self.prepare_clone()
            self.merge()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Synchronizes a github repository with a local repository.'
    )
    parser.add_argument('git_url', help='Url of the repo to sync')
    parser.add_argument('branch_name', default='main', help='Branch of repo to sync', nargs='?')
    parser.add_argument('repo_dir', default='.', help='Path to clone repo under', nargs='?')
    args = parser.parse_args()

    GitSync(args.git_url, args.branch_name, args.repo_dir)
