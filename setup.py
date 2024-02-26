from setuptools import setup

from pathlib import Path
this_directory = Path(__file__).parent
long_description = (this_directory / 'README.md').read_text()

setup(
    name='anynotify',
    version='0.0.1',
    description='Backend-independent error notification library',
    long_description=long_description,
    long_description_content_type='text/markdown',
    url='https://github.com/atodekangae/anynotify',
    author='atodekangae',
    author_email='atodekangae@gmail.com',
    py_modules=['anynotify'],
    install_requires=[
        'requests>=2.26.0',
    ],
    extras_require={
        'dev': ['pytest>=6.0,<7.0', 'gevent>=24.2.1,<25.0.0', 'werkzeug>=3.0.1'],
    },
    classifiers=[
        'Environment :: Web Environment',
        'Intended Audience :: Developers',
        'Operating System :: OS Independent',
        'Programming Language :: Python',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.8',
        'Programming Language :: Python :: 3.9',
        'Programming Language :: Python :: 3.10',
        'Programming Language :: Python :: 3.11',
        'Programming Language :: Python :: 3.12',
        'Topic :: Software Development :: Libraries :: Python Modules'
    ],
    python_requires='>=3.8',
)
