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

from strbo_log import log, errormsg
import strbo_repo
import strbo_version


def _handle_repo_changes(repo_url, current_flavor, target_flavor):
    step = {
        'action': 'manage-repos',
        'base_url': repo_url,
    }

    if target_flavor is None:
        return step, current_flavor, False

    if target_flavor == 'stable':
        target_flavor = ''

    if target_flavor == current_flavor:
        return step, current_flavor, False

    if current_flavor:
        step['disable_flavor'] = current_flavor

    if target_flavor:
        step['enable_flavor'] = target_flavor

    return step, target_flavor if target_flavor is not None else '', True


def _read_latest_txt_file(url, is_required):
    r = requests.get(url)

    if r.status_code == 200:
        try:
            return strbo_version.VersionNumber.from_string(r.text.strip())
        except Exception as e:
            errormsg('Failed parsing version number from latest.txt: {}'
                     .format(e))
            return None

    if r.status_code == 404:
        if is_required:
            errormsg('File latest.txt not found on server')
    else:
        errormsg('Failed downloading latest.txt: {}'.format(r.status_code))

    return None


def _handle_version_change(current_version, target_version,
                           force_version_check, repo_url, target_flavor):
    if not target_flavor:
        target_flavor = 'stable'

    if target_version is None:
        latest_version = \
            _read_latest_txt_file('{}/{}/versions/latest.txt'
                                  .format(repo_url, target_flavor), False)

        if not latest_version:
            # just want the latest version of target flavor: distro-sync
            log('Planning update to latest version of flavor {}'
                .format(target_flavor))
            return {'action': 'dnf-distro-sync'}

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
        'action': 'dnf-upgrade',
        'requested_version': str(target_version),
        'version_file_url': '{}/{}/versions/V{}.version'
                            .format(repo_url, target_flavor, target_version),
    }


def _compute_package_manager_strategy(strategy, args, main_version,
                                      target_release_line):
    repo_url = '{}/{}'.format(args.base_url, target_release_line)

    step, target_flavor, flavor_has_changed = \
        _handle_repo_changes(repo_url, main_version.get_flavor(),
                             args.target_flavor)
    if step:
        strategy.append(step)

    step = _handle_version_change(main_version.get_version_number(),
                                  args.target_version, flavor_has_changed,
                                  repo_url, target_flavor)
    if step:
        strategy.append(step)


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
                        args.machine_name), True)
    else:
        target_version = args.target_version

    if not target_version:
        raise RuntimeError('No target version specified')

    return target_version, target_flavor


def _read_recovery_compatibility_file(url):
    r = requests.get(url)

    if r.status_code == 200:
        return r.json()

    if r.status_code == 404:
        errormsg('File strbo-recovery-compatibility.json not found on server')
    else:
        errormsg('Failed downloading strbo-recovery-compatibility.json: {}'
                 .format(r.status_code))

    return None


def _determine_compatible_rsys(compat, version):
    revs = set()

    for rev in compat:
        for r in compat[rev]:
            vr = strbo_version.VersionRange.from_vrange(r)
            if vr.contains(version):
                revs.add(rev)

    return revs


def _ensure_recovery_system_compatibility(args, rsys_version,
                                          target_release_line, target_version,
                                          target_flavor):
    compat_url = \
        '{}/{}/recovery-system.{}/strbo-recovery-compatibility.json' \
        .format(args.base_url, target_release_line, args.machine_name)
    compat_json = _read_recovery_compatibility_file(compat_url)
    compat = compat_json['compatibility']

    required_revisions = _determine_compatible_rsys(compat, target_version)
    log('Requested upgrade to {}/{} requires one of rsys versions {}'
        .format(target_release_line, target_version, required_revisions))
    installed_revision = _determine_compatible_rsys(compat, rsys_version)

    if required_revisions.intersection(installed_revision):
        log('Installed recovery system {} is compatible with {}: not replacing'
            .format(rsys_version, target_version))
        return None

    log('Installed recovery system {} is incompatible with {}'
        .format(rsys_version, target_version))

    best = None
    for rev in reversed(compat_json['rank']):
        if rev in required_revisions:
            best = rev
            break

    if best is None:
        raise RuntimeError('No recovery system for {} found'
                           .format(target_version))

    log('Planning upgrade of recovery system to revision {}'.format(best))

    return {
        'action': 'run-installer',
        'requested_line': str(target_release_line),
        'requested_version': str(target_version),
        'requested_flavor': str(target_flavor),
        'installer_url': '{}/{}/recovery-system.{}/strbo-rsysimg-{}.bin'
                         .format(args.base_url, target_release_line,
                                 args.machine_name, best),
    }


def main():
    parser = argparse.ArgumentParser(
                description='Determine upgrade path from current state to '
                            'given version number')
    parser.add_argument('--base-url', '-u', metavar='URL', type=str,
                        required=True,
                        help='base URL of StrBo package repository')
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
    args = parser.parse_args()

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

        step = _ensure_recovery_system_compatibility(
                    args,
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

        if recovery_sys.get_data_version().get_version_number() != \
                target_version:
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

    print(json.dumps(strategy))


if __name__ == '__main__':
    main()
