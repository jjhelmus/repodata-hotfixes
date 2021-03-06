# -*- coding: utf-8 -*-
from __future__ import absolute_import, division, print_function, unicode_literals

from collections import defaultdict
import json
import os
from os.path import join, dirname, isfile, isdir
import sys
import fnmatch

import requests

CHANNEL_NAME = "pro"
CHANNEL_ALIAS = "https://repo.anaconda.com/pkgs"
SUBDIRS = (
    "noarch",
    "linux-32",
    "linux-64",
    "linux-aarch64",
    "linux-armv6l",
    "linux-armv7l",
    "linux-ppc64le",
    "osx-64",
    "win-32",
    "win-64",
)

REMOVALS = {
    "linux-64": (
        "r-nloptr-1.0.4-r3.2.2_1.tar.bz2",  # dependency on nlopt; only in conda-forge, and has problems of its own
    ),
    "osx-64": (),
    "win-32": (),
    "win-64": (),
    "any": {}
}

REVOKED = {}

EXTERNAL_DEPENDENCIES = {
    "blas": "global:blas",
    "bwidget": "global:bwidget",
    "bzip2": "global:bzip2",
    "cairo": "global:cairo",
    "cudatoolkit": "global:cudatoolkit",
    "curl": "global:curl",
    "cyrus-sasl": "global:cyrus-sasl",
    "expat": "global:expat",
    "fonts-anaconda": "global:fonts-anaconda",
    "fonts-continuum": "global:fonts-continuum",
    "freeglut": "global:freeglut",
    "freetype": "global:freetype",
    "gcc": "global:gcc",
    "gcc_linux-32": "global:gcc_linux-32",
    "gcc_linux-64": "global:gcc_linux-64",
    "geos": "global:geos",
    "gfortran_linux-32": "global:gfortran_linux-32",
    "gfortran_linux-64": "global:gfortran_linux-64",
    "glib": "global:glib",
    "gmp": "global:gmp",
    "gsl": "global:gsl",
    "gxx_linux-32": "global:gxx_linux-32",
    "gxx_linux-64": "global:gxx_linux-64",
    "icu": "global:icu",
    "ipython-notebook": "python:ipython-notebook",
    "jinja2": "python:jinja2",
    "jpeg": "global:jpeg",
    "jupyter": "python:jupyter",
    "krb5": "global:krb5",
    "libcurl": "global:libcurl",
    "libgcc": "global:libgcc",
    "libgcc-ng": "global:libgcc-ng",
    "libgdal": "global:libgdal",
    "libgfortran-ng": "global:libgfortran-ng",
    "libglu": "global:libglu",
    "libopenblas": "global:libopenblas",
    "libpng": "global:libpng",
    "libssh2": "global:libssh2",
    "libstdcxx-ng": "global:libstdcxx-ng",
    "libtiff": "global:libtiff",
    "libuuid": "global:libuuid",
    "libxgboost": "global:libxgboost",
    "libxml2": "global:libxml2",
    "libxslt": "global:libxslt",
    "make": "global:make",
    "mysql": "global:mysql",
    "ncurses": "global:ncurses",
    "notebook": "python:notebook",
    "openssl": "global:openssl",
    "pandoc": "global:pandoc",
    "pango": "global:pango",
    "pcre": "global:pcre",
    "proj4": "global:proj4",
    "python": "global:python",
    "qt": "global:qt",
    "readline": "global:readline",
    "singledispatch": "python:singledispatch",
    "six": "python:six",
    "tk": "global:tk",
    "tktable": "global:tktable",
    "udunits2": "global:udunits2",
    "unixodbc": "global:unixodbc",
    "xz": "global:xz",
    "zeromq": "global:zeromq",
    "zlib": "global:zlib",
}

NAMESPACE_IN_NAME_SET = {

}


NAMESPACE_OVERRIDES = {
    "r": "global",
    "r-tensorflow": "r",
}


def _patch_repodata(repodata, subdir):
    index = repodata["packages"]
    instructions = {
        "patch_instructions_version": 1,
        "packages": defaultdict(dict),
        "revoke": [],
        "remove": [],
    }

    instructions["remove"].extend(REMOVALS.get(subdir, ()))

    if subdir == "noarch":
        instructions["external_dependencies"] = EXTERNAL_DEPENDENCIES

    def rename_dependency(fn, record, old_name, new_name):
        depends = record["depends"]
        dep_idx = next(
            (q for q, dep in enumerate(depends) if dep.split(' ')[0] == old_name),
            None
        )
        if dep_idx:
            parts = depends[dep_idx].split(" ")
            remainder = (" " + " ".join(parts[1:])) if len(parts) > 1 else ""
            depends[dep_idx] = new_name + remainder
            instructions["packages"][fn]['depends'] = depends

    for fn, record in index.items():
        record_name = record["name"]
        if record_name in NAMESPACE_IN_NAME_SET and not record.get('namespace_in_name'):
            # set the namespace_in_name field
            instructions["packages"][fn]['namespace_in_name'] = True
        if NAMESPACE_OVERRIDES.get(record_name):
            # explicitly set namespace
            instructions["packages"][fn]['namespace'] = NAMESPACE_OVERRIDES[record_name]
        # ensure that all r/r-base/mro-base packages have the mutex
        if record_name == "r-base":
            if not any(dep.split()[0] == "_r_mutex" for dep in record['depends']):
                record['depends'].append("_r-mutex 1.* anacondar_1")
                instructions["packages"][fn]["depends"] = record['depends']
        elif record_name == "mro-base":
            if not any(dep.split()[0] == "_r_mutex" for dep in record['depends']):
                record['depends'].append("_r-mutex 1.* mro_2")
                instructions["packages"][fn]["depends"] = record['depends']
        # None of the 3.1.2 builds used r-base, and none of them have the mutex
        elif record_name == "r" and record['version'] == "3.1.2":
            # less than build 3 was an actual package; no r-base connection.  These need the mutex.
            if int(record["build_number"]) < 3:
                record['depends'].append("_r-mutex 1.* anacondar_1")
                instructions["packages"][fn]["depends"] = record['depends']
            else:
                # this dep was underspecified
                record['depends'].remove('r-base')
                record['depends'].append('r-base 3.1.2')
                instructions["packages"][fn]["depends"] = record['depends']

        if (any(fnmatch.fnmatch(fn, rev) for rev in REVOKED.get(subdir, [])) or
                 any(fnmatch.fnmatch(fn, rev) for rev in REVOKED.get("any", []))):
            instructions['revoke'].append(fn)
        if (any(fnmatch.fnmatch(fn, rev) for rev in REMOVALS.get(subdir, [])) or
                 any(fnmatch.fnmatch(fn, rev) for rev in REMOVALS.get("any", []))):
            instructions['remove'].append(fn)

    return instructions


def _extract_and_remove_vc_feature(record):
    features = record.get('features', '').split()
    vc_features = tuple(f for f in features if f.startswith('vc'))
    if not vc_features:
        return None
    non_vc_features = tuple(f for f in features if f not in vc_features)
    vc_version = int(vc_features[0][2:])  # throw away all but the first
    if non_vc_features:
        record['features'] = ' '.join(non_vc_features)
    else:
        del record['features']
    return vc_version


def main():

    base_dir = join(dirname(__file__), CHANNEL_NAME)

    # Step 1. Collect initial repodata for all subdirs.
    repodatas = {}
    for subdir in SUBDIRS:
        repodata_path = join(base_dir, subdir, 'repodata-clone.json')
        if isfile(repodata_path):
            with open(repodata_path) as fh:
                repodatas[subdir] = json.load(fh)
        else:
            repodata_url = "/".join((CHANNEL_ALIAS, CHANNEL_NAME, subdir, "repodata.json"))
            response = requests.get(repodata_url)
            response.raise_for_status()
            repodatas[subdir] = response.json()
            if not isdir(dirname(repodata_path)):
                os.makedirs(dirname(repodata_path))
            with open(repodata_path, 'w') as fh:
                json.dump(repodatas[subdir], fh, indent=2, sort_keys=True, separators=(',', ': '))


    # Step 2. Create all patch instructions.
    patch_instructions = {}
    for subdir in SUBDIRS:
        instructions = _patch_repodata(repodatas[subdir], subdir)
        patch_instructions_path = join(base_dir, subdir, "patch_instructions.json")
        with open(patch_instructions_path, 'w') as fh:
            json.dump(instructions, fh, indent=2, sort_keys=True, separators=(',', ': '))
        patch_instructions[subdir] = instructions


if __name__ == "__main__":
    sys.exit(main())
