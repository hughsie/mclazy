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

""" Parses the modules.xml file """

import rpm
import os
import subprocess

from xml.etree.ElementTree import ElementTree
from log import print_debug, print_info, print_fail

def run_command(cwd, argv, print_failures=True):
    print_debug("Running %s" % " ".join(argv))
    p = subprocess.Popen(argv, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    output, error = p.communicate()
    if p.returncode != 0 and print_failures:
        print(output)
        print(error)
    if p.returncode != 0:
        return False
    return True

class ModulesItem(object):
    """ Represents a project in the modules.xml file """
    def __init__(self):
        self.name = None
        self.pkgname = None
        self.pkgconfig = None
        self.pkg_cache = None
        self.fedora_branch = None   # f20, rawhide, f20-gnome-3-12
        self.dist = None            # f20, master,  f20
        self.release = None
        self.wait_repo = False
        self.disabled = False
        self.ftpadmin = True
        self.release_glob = {}
        self.deps = []
        self.depsolve_level = 0
        self.is_copr = False

        # add the default gnome release numbers
        self.release_glob['f18'] = "3.6.*"
        self.release_glob['f19'] = "3.8.*"
        self.release_glob['f20'] = "3.9.*,3.10.*,3.10"
        self.release_glob['f20-gnome-3-12'] = "3.11.*,3.12.*,3.12"
        self.release_glob['f20-gnome-3-14'] = "3.13.*,3.14.*,3.14"
        self.release_glob['rawhide'] = "*"

    def setup_pkgdir(self, cachedir, fedora_branch):

        self.spec_filename = "%s/%s/%s.spec" % (cachedir, self.pkgname, self.pkgname)
        self.fedora_branch = fedora_branch
        if self.fedora_branch == 'f20-gnome-3-12':
            self.is_copr = True
            # not strictly true, but we want this to be a higher version than
            # the rebuilt f20 packages without using an epoch
            self.dist = 'f21'
        elif self.fedora_branch == 'f20-gnome-3-14':
            self.is_copr = True
            self.dist = 'f21'
        elif self.fedora_branch == 'rawhide':
            self.dist = 'master'
        else:
            self.dist = fedora_branch

        # ensure package is checked out
        self.pkg_cache = os.path.join(cachedir, self.pkgname)
        if not os.path.isdir(self.pkg_cache):
            if not run_command(cachedir, ["fedpkg", "co", self.pkgname]):
                print_fail("Checkout %s" % self.pkgname)
                return False
            return True

        # clean
        if not run_command(self.pkg_cache, ['git', 'clean', '-dfx']):
            return False
        if not run_command(self.pkg_cache, ['git', 'reset', '--hard', 'HEAD']):
            return False

        # private COPR branch
        do_pull = True
        if self.is_copr:
            if not run_command(self.pkg_cache, ['git', 'checkout', fedora_branch], False):
                if not run_command(self.pkg_cache, ['git', 'checkout', 'f20']):
                    return False
                if not run_command(self.pkg_cache, ['git', 'checkout', '-b', fedora_branch]):
                    return False
                if not self.run_command(['git', 'push', '--set-upstream', 'origin', fedora_branch]):
                    return False
                do_pull = False

        # normal fedora branch e.g. f20, f19, rawhide etc.
        elif not run_command(self.pkg_cache, ['git', 'checkout', self.dist]):
            print_fail("Switch branch")
            return False

        # ensure package is updated
        if do_pull and not run_command(self.pkg_cache, ['git', 'pull']):
            print_fail("Update repo %s" % self.pkgname)
            return False

        return True

    def parse_spec(self):
        version = 0
        if not os.path.exists(self.spec_filename):
            print_fail("No spec file")
            return False

        # open spec file
        try:
            spec = rpm.spec(self.spec_filename)
            self.version = spec.sourceHeader["version"]
        except ValueError as e:
            print_fail("Can't parse spec file")
            return False
        return True

    def run_command(self, argv):
        return run_command(self.pkg_cache, argv)

    def check_patches(self):
        if self.is_copr:
            argv = ['fedpkg', "--dist=%s" % self.dist, 'prep']
        else:
            argv = ['fedpkg', 'prep']
        return run_command(self.pkg_cache, argv)

    def new_tarball(self, filename):
        return run_command(self.pkg_cache, ['fedpkg', "--dist=%s" % self.dist, 'new-sources', filename])

    def commit_and_push(self, commit_msg):

        # commit
        if not self.run_command(['git', 'commit', '-a', "--message=%s" % commit_msg]):
            return False

        # private branch
        if not self.run_command(['git', 'push']):
            return False
        return True

class ModulesXml(object):
    """ Parses the modules.xml file """

    def __init__(self, filename):
        self.items = []
        tree = ElementTree()
        tree.parse(filename)
        projects = list(tree.iter("project"))
        for project in projects:
            item = ModulesItem()
            item.disabled = False
            item.name = project.get('name')
            item.pkgname = project.get('pkgname')
            if not item.pkgname:
                item.pkgname = item.name
            item.pkgconfig = project.get('pkgconfig')
            if not item.pkgconfig:
                item.pkgconfig = item.name
            if project.get('wait_repo') == "1":
                item.wait_repo = True
            if project.get('ftpadmin') == "False":
                item.ftpadmin = False
            if project.get('disabled') == "True":
                item.disabled = True
            for data in project:
                if data.tag == 'dep':
                    item.deps.append(data.text)
                elif data.tag == 'release':
                    version = data.get('version')
                    item.release_glob[version] = data.text
            item.releases = []
            if project.get('releases'):
                for release in project.get('releases').split(','):
                    item.releases.append(release)
            else:
                item.releases.append('f19')
                item.releases.append('f20')
            item.branches = []
            if project.get('branches'):
                for branch in project.get('branches').split(','):
                    item.branches.append(branch)
            else:
                item.branches.append('3-12')
                item.branches.append('3-14')
            self.items.append(item)

    def depsolve(self):
        """ depsolves the list into the correct order """

        # check there are no recyprical deps
        for item in self.items:
            for dep in item.deps:
                item2 = self._get_item_by_name(dep)
                if not item2:
                    continue
                if item.pkgname in item2.deps:
                    print item.pkgname, "depends on", item2.pkgname
                    print item2.pkgname, "depends on", item.pkgname
                    return False

        # do the depsolve
        changes = True
        cnt = 0
        while changes:
            if cnt > 10000:
                print "Depsolve error"
                self.items = sorted(self.items, key=lambda item: item.depsolve_level)
                for item in self.items:
                    if item.name:
                        print item.name, item.depsolve_level
                    else:
                        print item.pkgname, item.depsolve_level
                    for dep in item.deps:
                        print "  ", dep, self._get_item_by_name(dep).depsolve_level
                return False
            changes = False
            for item in self.items:
                for dep in item.deps:
                    item_dep = self._get_item_by_name(dep)
                    if not item_dep:
                        print "failed to find dep", dep
                        return False
                    if item.depsolve_level <= item_dep.depsolve_level:
                        item.depsolve_level += 1
                        changes = True
                        cnt = cnt + 1
                        break
                if changes:
                    break
        # sort by depsolve key
        self.items = sorted(self.items, key=lambda item: item.depsolve_level)
        return True

    def _print(self):
        for item in self.items:
            print("%02i " % item.depsolve_level + ' ' * item.depsolve_level + item.pkgname)

    def _get_item_by_name(self, name):
        for item in self.items:
            if item.name == name:
                return item
        return None
