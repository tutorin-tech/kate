"""The builds the Kate package."""

from setuptools import setup

try:
    import pypandoc
    long_description = pypandoc.convert('README.md', 'rst')
except ImportError:
    long_description = ('Kate is a web-based terminal emulator. Kate consists '
                        'of two parts: a client and a server. Note that the '
                        'package provides the server.')


setup(name='kate',
      version='0.4',
      description='Kate package',
      long_description=long_description,
      url='https://github.com/tutorin-tech/kate.git',
      maintainer='Evgeny Golyshev',
      maintainer_email='Evgeny Golyshev <eugulixes@gmail.com>',
      license='http://www.apache.org/licenses/LICENSE-2.0',
      scripts=['bin/server.py'],
      packages=['kate'],
      package_data={'kate': ['linux_console.json']},
      install_requires=[
          'PyYAML',
          'tornado',
      ])
