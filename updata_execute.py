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
from pathlib import Path

from strbo_log import log, errormsg


class Data:
    def __init__(self, args):
        self.args = args
        self._rest_entry_point = None

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
    def write_var(var_name, value):
        if value is None:
            return False

        log_step(step, 'Set dnf variable {} = {}'.format(var_name, value))
        print(value, file=(d.args.dnf_vars_dir / var_name).open('w'))
        return True

    write_var('releasever', step.get('release_line'))
    write_var('strbo_update_baseurl', step.get('base_url', None))

    if write_var('strbo_flavor', step.get('enable_flavor', None)):
        write_var('strbo_flavor_enabled', 'true')
    else:
        flavor = step.get('disable_flavor', None)
        if flavor:
            write_var('strbo_flavor_enabled', 'false')


def do_dnf_install(step, d):
    log_step(step, 'Downloading manifest for version {}'
             .format(step['requested_version']))
    r = requests.get(step['version_file_url'])
    r.raise_for_status()

    log_step(step, 'Installing packages')
    cmd = ['dnf', 'install'] + \
          [line.split(' ', 1)[0] for line in r.text.split('\n') if line]
    subprocess.check_output(cmd, stderr=subprocess.STDOUT)


def do_dnf_distro_sync(step, d):
    log_step(step, 'Synchronizing with latest distro version')
    cmd = ['dnf', 'distro-sync']
    subprocess.check_output(cmd, stderr=subprocess.STDOUT)


def do_reboot_system(step, d):
    # it would be great if we could just use the REST API here, but it is
    # entirely possible for the REST API to be non-funcional at this point;
    # hence, we reboot by ourselves
    log_step(step, 'Requesting system reboot')
    cmd = ['systemctl', 'isolate', 'systemd-reboot.service']
    subprocess.check_output(cmd, stderr=subprocess.STDOUT)


def do_run_installer(step, d):
    log_step(step, 'Replacing recovery system -> {}'
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
    if v['number'] != step['requested_version'] or \
            v['release_line'] != step['requested_line'] or \
            v['flavor'] != step['requested_flavor']:
        raise RuntimeError(
                'Recovery system version is still wrong: '
                'line {} flavor {} version {}; giving up'
                .format(v['release_line'], v['flavor'], v['number']))


def do_recover_system(step, d):
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
    if v['number'] != step['requested_version'] or \
            v['release_line'] != step['requested_line'] or \
            v['flavor'] != step['requested_flavor']:
        raise RuntimeError('Recovery data version is still wrong: '
                           'line {} flavor {} version {}; giving up'
                           .format(v['release_line'], v['flavor'], v['number']))

    log_step(step, 'Request system reboot into recovery system')
    ep = d.get_rest_api_endpoint('recovery_data', 'reboot_system')
    params = {
        'request': 'Please kindly recover the system: I really know what I am doing',
        'keep_user_data': step['keep_user_data']
    }
    r = requests.post(ep, json=params)
    r.raise_for_status()


def main():
    parser = argparse.ArgumentParser(
                description='Execute previously computed update plan')
    parser.add_argument('--plan', '-p', metavar='FILE', type=Path,
                        required=True, help='file containing an update plan')
    parser.add_argument('--rest-api-url', '-u', metavar='URL', type=str,
                        default='http://localhost:8467/v1',
                        help='file containing an update plan')
    parser.add_argument('--dnf_vars-dir', '-v', metavar='PATH', type=Path,
                        default='/etc/dnf/vars',
                        help='path to dnf variable definitions')
    args = parser.parse_args()
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
            actions[a](step, data)
            log_step(step, 'Done')
        else:
            errormsg('Action "{}" unknown, skipping step'.format(a))


if __name__ == '__main__':
    main()
