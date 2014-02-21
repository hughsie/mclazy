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

        if item.pkgname == item.name:
            print("  <project name=\"%s\">" % item.name)
        else:
            print("  <project name=\"%s\" pkgname=\"%s\">" % (item.name, item.pkgname))
        f = open('/home/hughsie/Work/Fedora/' + item.pkgname + '/' + item.pkgname + '.spec', 'r')
        found = []
        for l in f.readlines():
            if not l.startswith('BuildRequires'):
                continue
            l = l.replace('\n', '')
            l = l[14:].lstrip()

            for section in l.split(' '):
                # remove pkgconfig() wrapper
                if section.startswith('pkgconfig('):
                    section = section[10:-1]
                    for item2 in data.items:
                        if section == item2.pkgconfig:
                            found.append(item2.name)
                            break
                else:
                    section = section.replace('NetworkManager-glib', 'NetworkManager')
                    section = section.replace('ModemManager-glib', 'ModemManager')
                    section = section.replace('PackageKit-glib', 'PackageKit')
                    section = section.replace('libwayland-client-devel', 'wayland')
                    section = section.replace('cheese-libs-devel', 'cheese')
                    section = section.replace('vala-tools', 'vala')
                    section = section.replace('libchamplain-gtk', 'libchamplain')
                    section = section.replace('gnome-bluetooth-libs-devel', 'gnome-bluetooth')
                    section = section.replace('-devel', '')
                    for item2 in data.items:
                        if section == item2.pkgname:
                            found.append(item2.name)
                            break

        for key in sorted(list(set(found))):
            print "    <dep>%s</dep>" % key
        f.close()
        print("  </project>")

if __name__ == "__main__":
    main()
