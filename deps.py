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

""" Print dep information for a modules.xml file """

from modules import ModulesXml

def main():

    # parse the configuration file
    data = ModulesXml("./modules.xml")
    for item in data.items:

        if not item.name:
            print("  <project pkgname=\"%s\">" % item.pkgname)
        elif item.pkgname == item.name:
            print("  <project name=\"%s\">" % item.name)
        else:
            print("  <project name=\"%s\" pkgname=\"%s\">" % (item.name, item.pkgname))
        f = open('/home/hughsie/Work/Fedora/' + item.pkgname + '/' + item.pkgname + '.spec', 'r')
        found = []
        for l in f.readlines():
            l = l.replace('\n', '')
            l = l.replace('-devel', '')
            if not l.startswith('BuildRequires'):
                continue
            for item2 in data.items:
                if item2.pkgname == item.pkgname:
                    continue
                if l.find(item2.pkgname) > 0:
                    if item2.name:
                        found.append(item2.name)
                    elif item2.pkgname:
                        found.append(item2.pkgname)
        for key in sorted(list(set(found))):
            print "    <dep>%s</dep>" % key
        f.close()
        print("  </project>")

if __name__ == "__main__":
    main()
