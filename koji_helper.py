#!/usr/bin/python
# Licensed under the GNU General Public License Version 2
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.

# Copyright (C) 2014
#    Richard Hughes <richard@hughsie.com>

import koji

from package import Package

class KojiHelper:
    def __init__(self):
        koji_instance = 'http://koji.fedoraproject.org/kojihub/'
        self.session = koji.ClientSession(koji_instance)

    def get_newest_build(self, branch, pkgname):
        builds = self.session.getLatestRPMS(branch, package=pkgname, arch='src')
        if len(builds[0]) == 0:
            return None
        latest = builds[0][0]
        pkg = Package()
        pkg.name = latest['name']
        pkg.version = latest['version']
        pkg.release = latest['release']
        return pkg
