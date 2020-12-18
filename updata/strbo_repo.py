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

from pathlib import Path
import shlex
import subprocess

from .strbo_log import errormsg
from .strbo_version import VersionNumber


def _parse_shell_style_file(path):
    values = {}

    try:
        with path.open('r') as f:
            raw_content = f.read()
            if not raw_content:
                return values

            for line in shlex.split(raw_content):
                key, value = line.split('=', 1)
                if key:
                    values[key] = value
    except Exception as e:
        errormsg('Error reading file {}: {}'.format(path, e))
        values = None

    return values


def _parse_simple_assignments_file(path):
    values = {}

    try:
        with path.open('r') as f:
            for line in f:
                key, value = line.split('=', 1)
                if key:
                    values[key.strip()] = value.strip()
    except Exception as e:
        errormsg('Error reading file {}: {}'.format(path, e))
        values = None

    return values


class VersionInfo:
    def __init__(self, version_number, release_line, flavor,
                 time_stamp, commit_id):
        self._version_number = version_number
        self._release_line = release_line
        self._flavor = flavor
        self._time_stamp = time_stamp
        self._commit_id = commit_id

    def __str__(self):
        return 'Version "{}" Line "{}" Flavor "{}" Time "{}" Commit "{}"' \
               .format(self._version_number, self._release_line, self._flavor,
                       self._time_stamp, self._commit_id)

    def get_release_line(self):
        return self._release_line

    def get_flavor(self):
        return self._flavor

    def get_version_number(self):
        return self._version_number

    @staticmethod
    def from_strbo_release(values):
        return VersionInfo(VersionNumber.from_string(values['STRBO_VERSION']),
                           values['STRBO_RELEASE_LINE'],
                           values['STRBO_FLAVOR'],
                           values['STRBO_DATETIME'],
                           values['STRBO_GIT_COMMIT'])

    @staticmethod
    def from_os_release(values):
        return VersionInfo(VersionNumber.from_string(values['VERSION_ID']),
                           'V1', None,
                           values['BUILD_ID'], values['BUILD_GIT_COMMIT'])


class MainSystem:
    def __init__(self, etc_path='/etc'):
        self._etc_path = Path(etc_path)

    def get_system_version(self):
        sr = self._etc_path / 'strbo-release'

        try:
            values = _parse_shell_style_file(sr)
            if values is not None:
                return VersionInfo.from_strbo_release(values)
        except Exception as e:
            errormsg('Failed obtaining main system version from {}: {}'
                     .format(sr, e))
            return None

        sr = self._etc_path / 'os-release'

        try:
            values = _parse_simple_assignments_file(sr)
            return None if values is None \
                   else VersionInfo.from_os_release(values)
        except Exception as e:
            errormsg('Failed obtaining main system version from {}: {}'
                     .format(sr, e))
            return None


def _run_command_failure(cmd, what, stderr, stdout, returncode):
    if what is None:
        what = ' '.join(cmd)

    errormsg('Command "{}" FAILED: {}'.format(what, stderr))
    errormsg('Failed command\'s stdout: {}'.format(stdout))

    raise RuntimeError(
            'Command "{}" returned non-zero exit status {}'
            .format(what, returncode))


def _run_command_3_5(cmd, what):
    proc = subprocess.run(cmd, capture_output=True)
    if proc.returncode == 0:
        return proc.stdout
    else:
        _run_command_failure(cmd, what, proc.stderr, proc.stdout, proc.returncode)


def _run_command_3_4(cmd, what):
    try:
        return subprocess.check_output(cmd, stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError as e:
        _run_command_failure(cmd, what, e.output, None, e.returncode)


def run_command(cmd, what=None):
    if 'run' in subprocess.__dict__:
        # Python 3.5 or later
        return _run_command_3_5(cmd, what)
    else:
        # Python 3.4 or earlier
        return _run_command_3_4(cmd, what)


class RecoverySystem:
    def __init__(self, system_mountpoint='/bootpartr',
                 data_mountpoint='/src', data_mountpoint_mounted=False):
        self.system_mountpoint = Path(system_mountpoint)
        self.data_mountpoint = Path(data_mountpoint)
        self.data_mountpoint_mounted = data_mountpoint_mounted
        self._is_sudo_required = True

    def get_system_version(self):
        sr = self.system_mountpoint / 'strbo-release'

        try:
            values = _parse_shell_style_file(sr)
            if values is not None:
                return VersionInfo.from_strbo_release(values)
        except Exception as e:
            errormsg('Failed obtaining recovery system version from {}: {}'
                     .format(sr, e))
            return None

        sr = self.system_mountpoint / 'os-release'

        try:
            values = _parse_simple_assignments_file(sr)
            if values is not None:
                return VersionInfo.from_os_release(values)
        except Exception as e:
            errormsg('Failed obtaining recovery system version from {}: {}'
                     .format(sr, e))
            return None

        return VersionInfo(None, 'V1', None, None, None)

    def get_data_version(self):
        sr = self.data_mountpoint / 'images/strbo-release'
        unmount_needed = False

        try:
            if not self.data_mountpoint_mounted:
                cmd = ['sudo'] if self._is_sudo_required else []
                cmd += ['/bin/mount', str(self.data_mountpoint)]
                run_command(cmd)
                unmount_needed = True

            values = _parse_shell_style_file(sr)
            return None if values is None \
                   else VersionInfo.from_strbo_release(values)
        except Exception as e:
            errormsg('Failed obtaining recovery data version from {}: {}'
                     .format(sr, e))
            return None
        finally:
            if unmount_needed:
                cmd = ['sudo'] if self._is_sudo_required else []
                cmd += ['/bin/umount', str(self.data_mountpoint)]
                run_command(cmd)
