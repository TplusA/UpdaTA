#! /usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (C) 2020, 2021, 2022  T+A elektroakustik GmbH & Co. KG
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
import os
import pwd
from pathlib import Path

from updata.strbo_log import log, errormsg
from updata import strbo_repo
from updata import strbo_version
from updata import strbo_compatibility


def _handle_repo_changes(base_url, release_line,
                         current_flavor, target_flavor, dnf_vars):
    step = {
        'action': 'manage-repos',
        'base_url': base_url,
        'release_line': release_line,
    }

    if target_flavor is None:
        target_flavor = current_flavor

    if target_flavor == 'stable':
        target_flavor = ''

    flavor_was_changed = target_flavor != current_flavor

    configured_flavor = dnf_vars.read_var('strbo_flavor')

    if configured_flavor and configured_flavor != target_flavor:
        step['disable_flavor'] = configured_flavor

    if target_flavor and configured_flavor != target_flavor:
        step['enable_flavor'] = target_flavor

    return step, target_flavor, flavor_was_changed


def _read_latest_txt_file(url, short_name):
    r = requests.get(url)

    if r.status_code == 200:
        try:
            return strbo_version.VersionNumber.from_string(r.text.strip())
        except Exception as e:
            errormsg('Failed parsing version number from {}: {}'
                     .format(short_name, e))
            return None

    if r.status_code == 404:
        errormsg('File {} not found on server'.format(short_name))
    else:
        errormsg('Failed downloading {}: {}'.format(short_name, r.status_code))

    return None


def _handle_version_change(current_version, target_version,
                           force_version_check, repo_url, target_flavor):
    if not target_flavor:
        target_flavor = 'stable'

    if target_version is None:
        latest_version = \
            _read_latest_txt_file('{}/{}/versions/latest.txt'
                                  .format(repo_url, target_flavor),
                                  'latest.txt (packages)')

        if not latest_version:
            return None

        # want preset latest version of chosen flavor
        target_version = latest_version
        target_version_pinned_on_server = True
    else:
        target_version_pinned_on_server = False

    if target_version == current_version and not force_version_check:
        # neither version number nor flavor changed: no update at all
        log('System update to {} avoided, version already installed'
            .format(target_version))
        return None

    # want specific version within same flavor or some version in newly
    # chosen flavor
    log('Planning update to {} version {}, flavor {}'
        .format('pinned' if target_version_pinned_on_server else 'requested',
                target_version, target_flavor))
    return {
        'action': 'dnf-install',
        'requested_version': str(target_version),
        'version_file_url': '{}/{}/versions/V{}.version'
                            .format(repo_url, target_flavor, target_version),
    }


def _compute_package_manager_strategy(strategy, args, main_version,
                                      target_release_line):
    step, target_flavor, flavor_has_changed = \
        _handle_repo_changes(args.base_url, target_release_line,
                             main_version.get_flavor(), args.target_flavor,
                             strbo_repo.DNFVariables(args.dnf_vars_dir))
    if step:
        strategy.append(step)

    step = _handle_version_change(
                main_version.get_version_number(),
                args.target_version, flavor_has_changed,
                '{}/{}'.format(args.base_url, target_release_line),
                target_flavor)
    if step:
        strategy.append(step)

    if strategy:
        log('Planning system reboot')
        strategy.append({'action': 'reboot-system'})


def _determine_recovery_target_version(args, default_flavor,
                                       target_release_line):
    target_flavor = \
        args.target_flavor if args.target_flavor is not None \
        else default_flavor
    if not target_flavor:
        target_flavor = 'stable'

    if args.target_version is None:
        target_version = \
            _read_latest_txt_file(
                '{}/{}/{}/recovery-data.{}/latest.txt'
                .format(args.base_url, target_release_line, target_flavor,
                        args.machine_name),
                'latest.txt (recovery data)')
    else:
        target_version = args.target_version

    if not target_version:
        raise RuntimeError('No target version specified')

    return target_version, target_flavor


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
                description='Determine upgrade path from current state to '
                            'given version number')
    parser.add_argument(
        '--output-file', '-o', metavar='FILE', type=argparse.FileType('w'),
        help='where to write the upgrade plan to (default: stdout)'
    )
    parser.add_argument(
        '--base-url', '-u', metavar='URL', type=str, required=True,
        help='base URL of StrBo package repository'
    )
    parser.add_argument(
        '--target-version', '-v', metavar='VERSION',
        type=strbo_version.VersionNumber.from_string,
        help='version number of the system the user wants to use; '
             'if none is specified, the latest available version is chosen'
    )
    parser.add_argument(
        '--target-release-line', '-r', metavar='NAME', type=str,
        help='release line the user wants to use; if none is specified, '
             'then the current release line is retained'
    )
    parser.add_argument(
        '--target-flavor', '-f', metavar='NAME', type=str,
        help='system flavor the user wants to use; if none is specified, '
             'then the current flavor is retained; pass an empty string or '
             'the string "stable" to disable any flavor and return to the '
             'base distribution'
    )
    parser.add_argument(
        '--force-image-files', '-i', action='store_true',
        help='update the system from image files through the recovery system, '
             'even if not strictly necessary'
    )
    parser.add_argument(
        '--force-rsys-update', '-s', action='store_true',
        help='if updating via image files, then update recovery system as '
             'well, even if not strictly necessary'
    )
    parser.add_argument(
        '--keep-user-data', '-k', action='store_true',
        help='avoid erasing of user data in case the upgrade is done through '
             ' the recovery system'
    )
    parser.add_argument(
        '--machine-name', '-m', metavar='NAME', type=str,
        default='raspberrypi',
        help='machine name of the Streaming Board (default: "raspberrypi"), '
             'required for updating via image files'
    )
    parser.add_argument('--dnf-vars-dir', metavar='PATH', type=Path,
                        default='/etc/dnf/vars',
                        help='path to dnf variable definitions')
    args = parser.parse_args()

    run_as_user('updata')

    main_sys = strbo_repo.MainSystem()
    main_version = main_sys.get_system_version()

    target_release_line = \
        args.target_release_line if args.target_release_line is not None \
        else main_version.get_release_line()

    strategy = []

    if target_release_line == main_version.get_release_line() and \
            not args.force_image_files:
        # we can use the package manager while within the same release line
        _compute_package_manager_strategy(strategy, args, main_version,
                                          target_release_line)
    else:
        # changing the release line always implies recovery
        target_version, target_flavor = \
            _determine_recovery_target_version(args, main_version.get_flavor(),
                                               target_release_line)

        recovery_sys = strbo_repo.RecoverySystem()

        compat_json = strbo_compatibility.read_recovery_compatibility_file(
            args, target_release_line)
        step = strbo_compatibility.ensure_recovery_system_compatibility(
            compat_json, args,
            recovery_sys.get_system_version().get_version_number(),
            target_release_line, target_version, target_flavor)
        if step:
            strategy.append(step)

        step = {
            'action': 'recover-system',
            'requested_line': str(target_release_line),
            'requested_version': str(target_version),
            'requested_flavor': str(target_flavor),
            'keep_user_data': args.keep_user_data,
        }

        dv = recovery_sys.get_data_version()

        if dv is None or dv.get_version_number() != target_version:
            log('Planning download of recovery images for version {}, '
                'flavor {}'.format(target_version, target_flavor))
            step['recovery_data_url'] = \
                '{}/{}/{}/recovery-data.{}/strbo-update-V{}.bin' \
                .format(args.base_url, target_release_line, target_flavor,
                        args.machine_name, target_version)
        else:
            log('Update of recovery images for version {} avoided, '
                'images already installed'.format(target_version))

        log('Planning recovery to version {}, flavor {}, {} user data'
            .format(target_version, target_flavor,
                    'keeping' if step['keep_user_data'] else 'erasing'))
        strategy.append(step)

    if args.output_file:
        args.output_file.write(json.dumps(strategy))
    else:
        print(json.dumps(strategy))


if __name__ == '__main__':
    main()
