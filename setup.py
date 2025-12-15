#!/usr/bin/env python3
from cartucho import __version__
from setuptools import setup


setup(
    name='cartucho',
    version=__version__,
    description="A tool to cache funcion and method results",
    long_description=open('README.md').read(),
    classifiers=[
        'Development Status :: 3 - Alpha',
        'Environment :: Console',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: GNU Lesser General Public License v3 (LGPLv3)',
        'Operating System :: OS Independent',
        'Programming Language :: Python :: 3.10',
        'Typing :: Typed'
    ],
    keywords='cache function method decorator',
    author='Pablo Muñoz',
    author_email='pablerass@gmail.com',
    url='https://github.com/pablerass/cartucho',
    license='LGPLv3',
    packages=['cartucho'],
    install_requires=[line for line in open('requirements.txt')],
    python_requires='>=3.10'
)