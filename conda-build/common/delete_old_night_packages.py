#!/usr/bin/env python3

# Copyright (c) Facebook, Inc. and its affiliates.
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

from __future__ import annotations

import argparse
import re
import subprocess
import sys

MAX_NUMBER_OF_VERSIONS = 1

parser = argparse.ArgumentParser(
    "A tool for removing conda nightly builds in chronical order to reduce conda repo storage usage"
)
parser.add_argument("--username", type=str, help="Username for the anaconda account.")
parser.add_argument("--password", type=str, help="Password for the anaconda account.")
parser.add_argument(
    "--nightly", help="Remove old conda nightly builds.", action="store_true"
)
args = parser.parse_args()


if not args.nightly:
    sys.exit()

login_result = subprocess.run(
    ["anaconda", "login", "--username", args.username, "--password", args.password],
    capture_output=True,
)
result = subprocess.run(
    ["anaconda", "show", "aihabitat-nightly/habitat-sim"],
    capture_output=True,
)
versions = re.findall(
    r"\d\.\d\.\d\.\d{4}\.\d\d\.\d\d", str(result.stdout) + str(result.stderr)
)
# Using len(versions) - MAX_NUMBER_OF_VERSIONS to support MAX_NUMBER_OF_VERSIONS == 0
remove_versions = versions[: len(versions) - MAX_NUMBER_OF_VERSIONS]
print(
    f"anaconda remove {' '.join(list(map(lambda x: f'aihabitat-nightly/habitat-sim/{x}', remove_versions)))}"
)
result_remove = subprocess.run(
    [
        "anaconda",
        "remove",
        "-f",
        *list(map(lambda x: f"aihabitat-nightly/habitat-sim/{x}", remove_versions)),
    ],
    capture_output=True,
)
