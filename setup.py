#!/usr/bin/env python3

from setuptools import setup, find_packages

VERSION = '0.1.2'

long_description = \
'''SurfCity is a Python client for Secure Scuttlebut. The default
terminal UI is using the colorful Urwid widgets. There is also a
pure TTY version. The Kivy version of the UI is included to show that
the internal APIs can also be used also with these widgets but is
functionally incomplete.'''

setup_info = dict(
    # Metadata
    name='surfcity',
    version=VERSION,
    author='cft',
    author_email='christian.tschudin@unibas.ch',
    url='https://github.com/cn-uofbasel/SurfCity',
    description='A family of Python clients for Secure Scuttlebutt',
    long_description=long_description,
    license='MIT',
    classifiers=[
        'Development Status :: 2 - Pre-Alpha',
        'Environment :: MacOS X',
        'Environment :: Win32 (MS Windows)',
        'Environment :: X11 Applications',
        'Intended Audience :: Developers',
        'Intended Audience :: Science/Research',
        'Intended Audience :: End Users/Desktop',
        'License :: OSI Approved :: MIT License',
        'Operating System :: MacOS :: MacOS X',
        'Operating System :: Microsoft :: Windows',
        'Operating System :: POSIX :: Linux',
        'Programming Language :: Python :: 3.7',
        'Topic :: Communications :: Chat'    ],

    # Package info
    packages = find_packages(),
    install_requires=['async-generator', 'asyncio', 'PyNaCl', 'urwid'],
    # kivy package not included because of size and incompletness:
    # install it manually if you want to see the kivy-based UI in action.


    zip_safe = True,
    entry_points = {
        'console_scripts': [
            'surfcity=surfcity.__main__:main',
        ],
    },

)

setup(**setup_info)

# eof
