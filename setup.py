from pathlib import Path

from setuptools import setup


Path(".local/metadata").mkdir(parents=True, exist_ok=True)
setup(options={
    "build": {"build_base": ".local/build/python"},
    "egg_info": {"egg_base": ".local/metadata"},
    "bdist": {"dist_dir": ".local/dist"},
    "sdist": {"dist_dir": ".local/dist"},
})
