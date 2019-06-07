#!/usr/bin/python
# -*- coding: utf-8 -*-
#
#    BTC: 13MXa7EdMYaXaQK6cDHqd4dwr2stBK3ESE
#    LTC: LfxwJHNCjDh2qyJdfu22rBFi2Eu8BjQdxj
#
#    https://github.com/s4w3d0ff/donnie
#
#    Copyright (C) 2018  https://github.com/s4w3d0ff
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
from setuptools import setup

read_md = lambda f: open(f, 'r').read()

setup(name='donnie',
      version='0.0.2',
      description='Poloniex tradebot toolkit',
      long_description=read_md('README.md'),
      long_description_content_type='text/markdown',
      url='https://github.com/s4w3d0ff/donnie',
      author='s4w3d0ff',
      license='GPL v3',
      packages=['donnie'],
      setup_requires=['pandas', 'numpy', 'scipy'],
      install_requires=['pymongo', 'poloniexapi', 'finta'],
      zip_safe=False,
      keywords=['poloniex', 'poloniexapi', 'exchange',
                'api', 'tradebot', 'framework'],
      classifiers = [
            'Operating System :: MacOS :: MacOS X',
            'Operating System :: Microsoft :: Windows',
            'Operating System :: POSIX',
            'License :: OSI Approved :: GNU General Public License v3 (GPLv3)',
            'Programming Language :: Python :: 3'
            ]
      )
