#! /usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (C) 2020  T+A elektroakustik GmbH & Co. KG
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
import requests
import subprocess
import sys
import os
import pwd
from pathlib import Path

from updata.strbo_log import log, errormsg


class RebootFailedError(Exception):
    pass


class Data:
    def __init__(self, args):
        self.args = args
        self._rest_entry_point = None
        self._is_sudo_required = True

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


def log_step(step, msg):
    log('{}: {}'.format(step['action'], msg))


def do_manage_repos(step, d):
    if d.args.reboot_only:
        return

    def write_var(var_name, value):
        if value is None:
            return False

        log_step(step, 'Set dnf variable {} = {}'.format(var_name, value))
        print(value, file=(d.args.dnf_vars_dir / var_name).open('w'))
        return True

    write_var('strbo_release_line', step.get('release_line'))
    write_var('strbo_update_baseurl', step.get('base_url', None))

    if write_var('strbo_flavor', step.get('enable_flavor', None)):
        write_var('strbo_flavor_enabled', '1')
    else:
        flavor = step.get('disable_flavor', None)
        if flavor:
            write_var('strbo_flavor_enabled', '0')


def _run_command(cmd, what):
    proc = subprocess.run(cmd, capture_output=True)
    if proc.returncode == 0:
        return

    if what is None:
        what = ' '.join(cmd)

    errormsg('Command "{}" FAILED: {}'.format(what, proc.stderr))

    raise RuntimeError(
            'Command "{}" returned non-zero exit status {}'
            .format(what, proc.returncode))


def do_dnf_install(step, d):
    if d.args.reboot_only:
        return

    log_step(step, 'Downloading manifest for version {}'
             .format(step['requested_version']))
    r = requests.get(step['version_file_url'])
    r.raise_for_status()

    log_step(step, 'Installing packages')
    cmd = ['sudo'] if d._is_sudo_required else []
    cmd += ['dnf', 'install', '--assumeyes'] + \
           [line.split(' ', 1)[0] for line in r.text.split('\n') if line]
    _run_command(cmd, 'dnf install')


def do_dnf_distro_sync(step, d):
    if d.args.reboot_only:
        return

    log_step(step, 'Synchronizing with latest distro version')
    cmd = ['sudo'] if d._is_sudo_required else []
    cmd += ['dnf', 'distro-sync', '--assumeyes']
    _run_command(cmd)


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
        _run_command(cmd)
    except RuntimeError as e:
        raise RebootFailedError(str(e))


def do_run_installer(step, d):
    if d.args.reboot_only:
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
                        help='file containing an update plan')
    parser.add_argument('--dnf_vars-dir', '-v', metavar='PATH', type=Path,
                        default='/etc/dnf/vars',
                        help='path to dnf variable definitions')
    args = parser.parse_args()

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

            log_step(step, 'Done')
        else:
            errormsg('Action "{}" unknown, skipping step'.format(a))


if __name__ == '__main__':
    main()
