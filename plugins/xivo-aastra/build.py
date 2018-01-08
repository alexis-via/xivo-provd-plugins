# -*- coding: utf-8 -*-

# Copyright 2014-2017 The Wazo Authors  (see the AUTHORS file)
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>

# Depends on the following external programs:
#  -rsync

from subprocess import check_call


# target(<target_id>, <pg_id>)
# any error raised will be considered a build error
# Pre: pg_dir is initially empty
# Pre: current directory is the one of the bplugin
@target('3.3.1-SP4', 'xivo-aastra-3.3.1-SP4')
def build_3_3_1_sp4(path):
    check_call(['rsync', '-rlp', '--exclude', '.*',
                '--exclude', '/templates/68*.tpl',
                'common/', path])

    check_call(['rsync', '-rlp', '--exclude', '.*',
                '3.3.1-SP4/', path])


@target('4.1.0', 'xivo-aastra-4.1.0')
def build_4_1_0(path):
    check_call(['rsync', '-rlp', '--exclude', '.*',
                '--exclude', '/templates/67*',
                '--exclude', '/templates/9*',
                'common/', path])

    check_call(['rsync', '-rlp', '--exclude', '.*',
                '4.1.0/', path])

@target('4.3.0', 'xivo-aastra-4.3.0')
def build_4_3_0(path):
    check_call(['rsync', '-rlp', '--exclude', '.*',
                '--exclude', '/templates/67*',
                '--exclude', '/templates/9*',
                'common/', path])

    check_call(['rsync', '-rlp', '--exclude', '.*',
                '4.3.0/', path])


@target('2.6.0.2019', 'xivo-aastra-2.6.0.2019')
def build_2_6_0_2019(path):
    check_call(['rsync', '-rlp', '--exclude', '.*',
                '2.6.0.2019/', path])
