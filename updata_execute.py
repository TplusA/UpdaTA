#! /usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (C) 2020, 2021, 2022, 2023  T+A elektroakustik GmbH & Co. KG
#
# This file is part of UpdaTA
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston,
# MA  02110-1301, USA.

import argparse
import json
import sys
import os
import pwd
from pathlib import Path
import requests
import pkg_resources

from updata.strbo_repo import run_command, DNFVariables
from updata.strbo_log import log, errormsg


class RebootFailedError(Exception):
    pass


class ExitForOfflineUpdate(Exception):
    pass


class Data:
    def __init__(self, args):
        self.args = args
        self._rest_entry_point = None
        self._is_sudo_required = True
        self._download_symlink = Path('/system-update')
        self.dnf_vars = DNFVariables(args.test_sysroot / 'etc/dnf/vars')

    def get_rest_api_endpoint(self, category, id):
        if self._rest_entry_point is None:
            r = requests.get(self.args.rest_api_url + '/')
            r.raise_for_status()
            self._rest_entry_point = r.json()

        try:
            for ep in self._rest_entry_point['_links'][category]:
                if ep['name'] == id:
                    return self.args.rest_api_url + ep['href']
        except Exception as e:
            errormsg('Failed looking up API endpoint {} in {}: {}'
                     .format(id, category, e))
            return None

        errormsg('API endpoint {} in {} not found'.format(id, category))
        return None

    def in_offline_mode(self):
        return self._download_symlink.exists()

    def get_offline_mode_symlink(self):
        return self._download_symlink


def log_step(step, msg):
    log('{}: {}'.format(step['action'], msg))


def do_manage_repos(step, d):
    if d.args.reboot_only:
        return

    if d.in_offline_mode():
        return

    def log_write(var_name, value):
        log_step(step, 'Set dnf variable {} = {}'.format(var_name, value))

    d.dnf_vars.write_var('strbo_release_line', step.get('release_line'),
                         log_write)
    d.dnf_vars.write_var('strbo_update_baseurl', step.get('base_url', None),
                         log_write)
    d.dnf_vars.write_var('strbo_base_enabled', '1', log_write)

    if d.dnf_vars.write_var('strbo_flavor', step.get('enable_flavor', None),
                            log_write):
        d.dnf_vars.write_var('strbo_flavor_enabled', '1', log_write)
    else:
        flavor = step.get('disable_flavor', None)
        if flavor:
            d.dnf_vars.write_var('strbo_flavor_enabled', '0', log_write)


def download_all_packages(step, symlink, updata_work_dir, dnf_work_dir,
                          is_sudo_required):
    log_step(step, 'Cleaning up dnf state')
    cmd = ['sudo'] if is_sudo_required else []
    cmd += ['dnf', 'clean', 'packages', '--assumeyes']
    run_command(cmd, 'dnf prepare', True)

    tempfiles = dnf_work_dir.resolve() / 'tempfiles.json'
    if is_sudo_required:
        cmd = ['sudo', '/bin/rm', '-f', str(tempfiles)]
        run_command(cmd, 'dnf delete tempfiles.json', True)
    else:
        tempfiles.unlink(missing_ok=True)

    log_step(step, 'Downloading manifest for version {}'
             .format(step['requested_version']))
    r = requests.get(step['version_file_url'])
    r.raise_for_status()
    r = [line.split(None, 1)[0] for line in r.text.split('\n') if line]

    with (updata_work_dir / 'manifest.txt').open('w') as mf:
        for line in r:
            print(line, file=mf)

    log_step(step, 'Downloading up to {} packages'.format(len(r)))

    if r:
        cmd = ['sudo'] if is_sudo_required else []
        cmd += ['dnf', 'install', '--assumeyes', '--downloadonly'] + r
        run_command(cmd, 'dnf download', True)

    log_step(step, 'Entering update mode')

    if is_sudo_required:
        cmd = ['sudo', 'ln', '-s', str(dnf_work_dir.resolve()), str(symlink)]
        run_command(cmd, 'dnf download done', True)
    else:
        symlink.symlink_to(dnf_work_dir, True)

    try:
        tempfiles = symlink / 'tempfiles.json'
        count = len(json.load(tempfiles.open()))
        log_step(step, 'Can install {} downloaded packages'.format(count))
    except Exception as e:
        log_step(step, 'NO packages downloaded: {}'.format(e))


def offline_update(step, symlink, updata_work_dir, is_sudo_required):
    try:
        tempfiles = symlink / 'tempfiles.json'
        r = list(json.load(tempfiles.open()))
    except Exception as e:
        errormsg('Failed to read dnf package list: {}'.format(e))
        r = None

    if is_sudo_required:
        cmd = ['sudo', 'rm', str(symlink)]
        run_command(cmd, 'dnf begin offline update', True)
    else:
        symlink.unlink()

    log_step(step, 'Installing {} packages'.format(0 if r is None else len(r)))

    if r:
        cmd = ['sudo'] if is_sudo_required else []
        cmd += ['dnf', 'install', '--assumeyes', '--allowerasing',
                '--setopt', 'keepcache=True'] + r
        run_command(cmd, 'dnf install', True)

    log_step(step, "Running ldconfig after installing packages")
    cmd = ['sudo'] if is_sudo_required else []
    cmd += ['ldconfig']
    run_command(cmd, "ldconfig after install", True)

    try:
        manifest = updata_work_dir / 'manifest.txt'
        r = set([line.strip() for line in manifest.open().readlines()])
    except Exception as e:
        errormsg('Failed to read manifest: {}'.format(e))
        r = set()

    residual = []

    cmd = ['sudo'] if is_sudo_required else []
    cmd += ['dnf', 'list', '--installed']

    for line in run_command(cmd, 'dnf list', True).decode().split('\n'):
        try:
            p, ver, rest = line.split(None, 2)
        except ValueError:
            continue

        name, arch = p.rsplit('.', 1)
        ver = ver.split(':', 1)
        ver = ver[0] if len(ver) == 1 else ver[1]

        package = '{}-{}.{}'.format(name, ver, arch)
        if r and package not in r:
            residual.append(package)

    log_step(step, 'Removing {} residual packages'.format(len(residual)))

    if residual:
        cmd = ['sudo'] if is_sudo_required else []
        cmd += ['dnf', 'remove', '--assumeyes', '--allowerasing'] + residual
        run_command(cmd, 'dnf remove', True)

    log_step(step, "Running ldconfig after removing packages")
    cmd = ['sudo'] if is_sudo_required else []
    cmd += ['ldconfig']
    run_command(cmd, "ldconfig after removal", True)

    log_step(step, 'Cleaning up downloaded packages')
    cmd = ['sudo'] if is_sudo_required else []
    cmd += ['dnf', 'clean', 'packages', '--assumeyes']
    run_command(cmd, 'dnf cleanup', True)

    manifest.unlink(missing_ok=True)


def do_dnf_install(step, d):
    if d.args.reboot_only:
        return

    if not d.in_offline_mode():
        download_all_packages(step, d.get_offline_mode_symlink(),
                              d.args.updata_work_dir, d.args.dnf_work_dir,
                              d._is_sudo_required)
        raise ExitForOfflineUpdate()
    else:
        offline_update(step, d.get_offline_mode_symlink(),
                       d.args.updata_work_dir, d._is_sudo_required)


def do_dnf_distro_sync(step, d):
    if d.args.reboot_only:
        return

    if d.in_offline_mode():
        return

    log_step(step, 'Synchronizing with latest distro version')
    cmd = ['sudo'] if d._is_sudo_required else []
    cmd += ['dnf', 'distro-sync', '--assumeyes']
    run_command(cmd, 'dnf distro-sync', True)


def do_reboot_system(step, d):
    if d.args.avoid_reboot:
        return

    # it would be great if we could just use the REST API here, but it is
    # entirely possible for the REST API to be non-funcional at this point;
    # hence, we reboot by ourselves
    log_step(step, 'Requesting system reboot')
    cmd = ['sudo'] if d._is_sudo_required else []
    cmd += ['systemctl', 'isolate', 'reboot.target']

    try:
        run_command(cmd)
    except RuntimeError as e:
        raise RebootFailedError(str(e))


def do_run_installer(step, d):
    if d.args.reboot_only:
        return

    if d.in_offline_mode():
        return

    log_step(step, 'Replacing recovery system for {}'
                   .format(step['requested_version']))
    ep = d.get_rest_api_endpoint('recovery_data', 'replace_system')
    r = requests.post(ep, data={'dataurl': step['installer_url']})
    r.raise_for_status()

    log_step(step, 'Verifying recovery system')
    ep = d.get_rest_api_endpoint('recovery_data', 'verify_system')
    r = requests.post(ep)
    r.raise_for_status()

    log_step(step, 'Checking recovery system version')
    ep = d.get_rest_api_endpoint('recovery_data', 'system_info')
    r = requests.get(ep)
    r.raise_for_status()

    sysinfo = r.json()

    if sysinfo['status']['state'] != 'valid':
        raise RuntimeError('Recovery system not valid: {}'
                           .format(sysinfo['status']['state']))

    v = sysinfo['version_info']
    log_step(step, 'Recovery system version line {} flavor {} version {}'
                   .format(v['release_line'], v['flavor'], v['number']))


def ensure_recovery_data(step, d):
    if d.args.reboot_only:
        return

    if 'recovery_data_url' in step:
        log_step(step, 'Replacing recovery data -> {}'
                       .format(step['requested_version']))
        ep = d.get_rest_api_endpoint('recovery_data', 'replace_data')
        r = requests.post(ep, data={'dataurl': step['recovery_data_url']})
        r.raise_for_status()
    else:
        log_step(step, 'Not replacing recovery data, should be {} already'
                       .format(step['requested_version']))

    log_step(step, 'Verifying recovery data')
    ep = d.get_rest_api_endpoint('recovery_data', 'verify_data')
    r = requests.post(ep)
    r.raise_for_status()

    log_step(step, 'Checking recovery data version')
    ep = d.get_rest_api_endpoint('recovery_data', 'data_info')
    r = requests.get(ep)
    r.raise_for_status()

    datainfo = r.json()

    if datainfo['status']['state'] != 'valid':
        raise RuntimeError('Recovery data not valid: {}'
                           .format(datainfo['status']['state']))

    v = datainfo['version_info']
    if v['number'].lstrip('V') != step['requested_version'].lstrip('V') or \
            v['release_line'] != step['requested_line'] or \
            v['flavor'] != step['requested_flavor']:
        raise RuntimeError(
                'Recovery data version is still wrong: '
                'line {} flavor {} version {}; giving up'
                .format(v['release_line'], v['flavor'], v['number']))


def reboot_into_recovery_system(step, d):
    if d.args.avoid_reboot:
        return

    log_step(step, 'Request system reboot into recovery system')
    ep = d.get_rest_api_endpoint('recovery_data', 'reboot_system')
    params = {
        'request': 'Please kindly recover the system: '
                   'I really know what I am doing',
        'keep_user_data': step['keep_user_data']
    }
    r = requests.post(ep, json=params)
    r.raise_for_status()


def do_recover_system(step, d):
    ensure_recovery_data(step, d)

    try:
        reboot_into_recovery_system(step, d)
    except requests.exceptions.HTTPError as e:
        raise RebootFailedError(str(e))


def run_as_user(name):
    try:
        pw = pwd.getpwnam(name)
        if os.geteuid() != pw.pw_uid or os.getegid() != pw.pw_gid:
            os.setgid(pw.pw_gid)
            os.setuid(pw.pw_uid)
            log('Running as user {}'.format(name))
    except PermissionError as e:
        errormsg('Failed to run as user "{}": {}'.format(name, e))
        raise
    except KeyError:
        errormsg('User "{}" does not exist'.format(name))
        raise


def main():
    log("updata_execute")

    parser = argparse.ArgumentParser(
                description='Execute previously computed update plan')
    parser.add_argument('--plan', '-p', metavar='FILE', type=Path,
                        required=True, help='file containing an update plan')
    parser.add_argument('--avoid-reboot', action='store_true',
                        help='do everything, but do not reboot the system')
    parser.add_argument('--reboot-only', action='store_true',
                        help='do nothing, but reboot the system if planned')
    parser.add_argument('--rest-api-url', '-u', metavar='URL', type=str,
                        default='http://localhost:8467/v1',
                        help='REST API base URL')
    parser.add_argument('--updata-work-dir', '-w', metavar='PATH', type=Path,
                        default='/var/local/data/system_update_data',
                        help='path to UpdaTA working directory')
    parser.add_argument('--dnf-work-dir', '-d', metavar='PATH', type=Path,
                        default='/var/local/data/dnf',
                        help='path to dnf working directory')
    parser.add_argument('--test-sysroot', metavar='PATH', type=Path,
                        default='/', help='test environment')
    parser.add_argument('--test-version', metavar='VERSION', type=str,
                        help='set package version for testing')
    args = parser.parse_args()

    if args.test_version is None:
        this_version = pkg_resources.require("UpdaTA")[0].version
    else:
        this_version = args.test_version

    test_mode = 'test_sysroot' in args or 'test_version' in args
    log("This is version {}{}"
        .format(this_version, ' --- TEST MODE' if test_mode else ''))

    run_as_user('updata')

    data = Data(args)
    plan = json.load(args.plan.open('r'))

    for step in plan:
        if 'action' not in step:
            raise RuntimeError('Invalid plan: {}'.format(args.plan.name))

    actions = {
        'manage-repos': do_manage_repos,
        'dnf-install': do_dnf_install,
        'dnf-distro-sync': do_dnf_distro_sync,
        'reboot-system': do_reboot_system,
        'run-installer': do_run_installer,
        'recover-system': do_recover_system,
    }

    for step in plan:
        log('Step: {}'.format(json.dumps(step)))
        a = step['action']

        if a in actions:
            try:
                actions[a](step, data)
            except RebootFailedError as e:
                errormsg('Failed to reboot: {}'.format(e))
                sys.exit(10)
            except requests.exceptions.ConnectionError as e:
                errormsg('Failed connecting to server: {}'.format(e))
                sys.exit(20)
            except ExitForOfflineUpdate:
                do_reboot_system(step, data)
                sys.exit(0)

            log_step(step, 'Done')
        else:
            errormsg('Action "{}" unknown, skipping step'.format(a))


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        log("Unhandled exception: {}".format(e))
        raise
