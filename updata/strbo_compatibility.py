#! /usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (C) 2022, 2023  T+A elektroakustik GmbH & Co. KG
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

import requests

from .strbo_log import log, errormsg
from .strbo_version import VersionRange


def read_recovery_compatibility_file(args, target_release_line):
    compat_url = \
        '{}/{}/recovery-system.{}/strbo-recovery-compatibility.json' \
        .format(args.base_url, target_release_line, args.machine_name)

    r = requests.get(compat_url)

    if r.status_code == 200:
        return r.json()

    if r.status_code == 404:
        errormsg('File strbo-recovery-compatibility.json not found on server')
    else:
        errormsg('Failed downloading strbo-recovery-compatibility.json: {}'
                 .format(r.status_code))

    return None


def _determine_compatible_rsys(compat, version):
    """Check if version is compatible.

    >>> _determine_compatible_rsys( \
            {"2-r0": ["1.999.*", "1.999.*.*", "2.*.*", "2.*.*.*"]}, \
            VersionNumber.from_string("2.1.0"))
    {'2-r0'}
    >>> _determine_compatible_rsys( \
            {"2-r0": ["1.999.*", "1.999.*.*", "2.*.*", "2.*.*.*"]}, \
            VersionNumber.from_string("2.1.0a"))
    {'2-r0'}
    >>> _determine_compatible_rsys( \
            {"2-r0": ["1.999.*", "1.999.*.*", "2.*.*", "2.*.*.*"]}, \
            VersionNumber.from_string("2.1.0z"))
    {'2-r0'}
    >>> _determine_compatible_rsys( \
            {"2-r0": ["1.999.*", "1.999.*.*", "2.*.*", "2.*.*.*"]}, \
            VersionNumber.from_string("2.0.88.99"))
    {'2-r0'}
    >>> _determine_compatible_rsys( \
            {"2-r0": ["1.999.*", "1.999.*.*", "2.*.*", "2.*.*.*"]}, \
            VersionNumber.from_string("1.999.1"))
    {'2-r0'}
    >>> _determine_compatible_rsys( \
            {"2-r0": ["1.999.*", "1.999.*.*", "2.*.*", "2.*.*.*"]}, \
            VersionNumber.from_string("1.99.1"))
    set()
    >>> _determine_compatible_rsys( \
            {"2-r0": ["1.999.*", "1.999.*.*", "2.*.*", "2.*.*.*"]}, \
            VersionNumber.from_string("3.0.0"))
    set()
    """
    revs = set()

    for rev in compat:
        for r in compat[rev]:
            vr = VersionRange.from_vrange(r)
            if vr.contains(version):
                revs.add(rev)

    return revs


def ensure_recovery_system_compatibility(compat_json, args, rsys_version,
                                         target_release_line, target_version,
                                         target_flavor):
    """Make sure the currently installed recovery system can be used with the
    target version, or trigger an update of the recovery system.

    The "compatibility" field tells which StrBo release versions are compatible
    with which recovery system in the keys ("3-r0"). A release may be
    compatible with multiple recovery systems, or with none of them. The "rank"
    field resolves ambiguities. This kind of compatibility determines whether
    or not the currently installed recovery system must be replaced to fulfill
    the requirements of the target release version, and by which.

    Since each major release has its own compatibility file, its contents are
    written from the point of view of a major release. It is always consulted
    when trying to install that release, and the versions listed in the
    "compatibility" field refer to the version currently running on the system
    that is supposed to be up-/downgraded.
    """
    if compat_json is None:
        raise RuntimeError('File strbo-recovery-compatibility.json missing')

    compat = compat_json['compatibility']

    required_revisions = _determine_compatible_rsys(compat, target_version)
    log('Requested upgrade to {}/{} requires one of rsys versions {}'
        .format(target_release_line, target_version, required_revisions))
    installed_revision = _determine_compatible_rsys(compat, rsys_version)

    if required_revisions.intersection(installed_revision):
        log('Installed recovery system {} is compatible with {}: {}'
            .format(rsys_version, target_version,
                    'update enforced' if args.force_rsys_update
                    else 'not replacing'))
        if not args.force_rsys_update:
            return None

    if not args.force_rsys_update:
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


def _run_tests():
    doctest.testmod()

    def no_logs(_):
        pass

    global log
    log = no_logs

    _test_simple_compatibilities()
    _test_extended_compatibilities()


def _test_simple_compatibilities():
    compat_v2_v3 = json.loads('{ \
            "compatibility": { \
                "3-r0": ["2.*.*", "2.*.*.*", "3.*.*", "3.*.*.*"] \
            }, \
            "rank": ["3-r0"] \
        }')

    compat_v3_only = json.loads('{ \
            "compatibility": { \
                "3-r0": ["3.*.*", "3.*.*.*"] \
            }, \
            "rank": ["3-r0"] \
        }')

    args = type('', (object,), {
        'force_rsys_update': False,
        'base_url': 'https://points.to.nowhere/updates',
        'machine_name': 'raspberrypi',
    })()

    # Coming from V2.9.1, want to go to compatible V3.0.0
    result = ensure_recovery_system_compatibility(
        compat_v2_v3, args, VersionNumber.from_string('2.9.1'),
        'V3', VersionNumber.from_string('3.0.0'), 'stable')
    assert result is None

    # Coming from V1.2.3, want to go to incompatible V3.0.0
    result = ensure_recovery_system_compatibility(
        compat_v2_v3, args, VersionNumber.from_string('1.2.3'),
        'V3', VersionNumber.from_string('3.0.0'), 'stable')
    assert result is not None
    assert result['requested_line'] == 'V3'
    assert result['requested_version'] == '3.0.0'
    assert result['requested_flavor'] == 'stable'
    assert result['installer_url'] == \
        'https://points.to.nowhere/updates/V3/recovery-system.raspberrypi/' \
        'strbo-rsysimg-3-r0.bin'

    # Coming from V2.9.1, want to go to incompatible V3.0.0
    result = ensure_recovery_system_compatibility(
        compat_v3_only, args, VersionNumber.from_string('2.9.1'),
        'V3', VersionNumber.from_string('3.0.0'), 'stable')
    assert result is not None
    assert result['requested_version'] == '3.0.0'
    assert result['requested_flavor'] == 'stable'


def _test_extended_compatibilities():
    compat = json.loads('{ \
            "compatibility": { \
                "3-r0": ["3.0.*", "3.0.*.*"], \
                "3-r1": ["3.0.*", "3.0.*.*"], \
                "3-r2": ["3.1.*", "3.1.*.*", "4.*.*", "4.*.*.*"] \
            }, \
            "rank": ["3-r0", "3-r1", "3-r2"] \
        }')

    args = type('', (object,), {
        'force_rsys_update': False,
        'base_url': 'https://points.to.nowhere/updates',
        'machine_name': 'raspberrypi',
    })()

    # Coming from V3.0.0, want to go to compatible V3.0.4
    result = ensure_recovery_system_compatibility(
        compat, args, VersionNumber.from_string('3.0.0'),
        'V3', VersionNumber.from_string('3.0.4'), 'stable')
    assert result is None

    # Coming from V2.7.4, want to go to incompatible V3.0.0
    result = ensure_recovery_system_compatibility(
        compat, args, VersionNumber.from_string('2.7.4'),
        'V3', VersionNumber.from_string('3.0.0'), 'stable')
    assert result is not None
    assert result['requested_version'] == '3.0.0'
    assert result['installer_url'] == \
        'https://points.to.nowhere/updates/V3/recovery-system.raspberrypi/' \
        'strbo-rsysimg-3-r1.bin'

    # Coming from V2.7.4, want to go to incompatible V3.1.0
    result = ensure_recovery_system_compatibility(
        compat, args, VersionNumber.from_string('2.7.4'),
        'V3', VersionNumber.from_string('3.1.0'), 'stable')
    assert result is not None
    assert result['requested_version'] == '3.1.0'
    assert result['installer_url'] == \
        'https://points.to.nowhere/updates/V3/recovery-system.raspberrypi/' \
        'strbo-rsysimg-3-r2.bin'

    # Coming from V4.0.9, want to go to compatible V3.1.3
    result = ensure_recovery_system_compatibility(
        compat, args, VersionNumber.from_string('4.0.9'),
        'V3', VersionNumber.from_string('3.1.3'), 'stable')
    assert result is None

    # Coming from V4.0.9, want to go to incompatible V3.0.2
    result = ensure_recovery_system_compatibility(
        compat, args, VersionNumber.from_string('4.0.9'),
        'V3', VersionNumber.from_string('3.0.2'), 'stable')
    assert result is not None
    assert result['requested_version'] == '3.0.2'
    assert result['installer_url'] == \
        'https://points.to.nowhere/updates/V3/recovery-system.raspberrypi/' \
        'strbo-rsysimg-3-r1.bin'


if __name__ == '__main__':
    import doctest
    import json
    from .strbo_version import VersionNumber
    _run_tests()
