# Copyright (c) 2009-2022 Farsight Security, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from setuptools import setup


setup(
    name='sie-update',
    description="Manage network interfaces' access to SIE",
    version='0.5.0',
    author='Farsight Security, Inc.',
    author_email='software@farsightsecurity.com',
    url='https://github.com/farsightsec/sie-update',
    license='Apache License 2.0',
    packages=['sie_update'],
    entry_points={
          'console_scripts': [
              'sie-update = sie_update.sie_update:main'
          ]
    },
    install_requires=[
        'python-daemon',
    ],
)
