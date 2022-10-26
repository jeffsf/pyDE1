#!/bin/sh

# Copyright © 2021-2022 Jeff Kletsky. All Rights Reserved.
#
# License for this software, part of the pyDE1 package, is granted under
# GNU General Public License v3.0 only
# SPDX-License-Identifier: GPL-3.0-only

>&2 echo "Creating source_data.py ($0)"

TARGET_FILE='src/pyDE1/source_data.py'

top_level=$(git rev-parse --show-toplevel)
git_dir=$(git rev-parse --absolute-git-dir)

hash=$(git show -s --pretty=format:'%h')
hash_full=$(git show -s --pretty=format:'%H')
subj=$(git show -s --pretty=format:'%s' | sed -e 's/"/\\"/g')
adate=$(git show -s --pretty=format:'%ad')
cdate=$(git show -s --pretty=format:'%cd')
names=$(git show -s --pretty=format:'%D' | sed -e 's/"/\\"/g')
# When used as a git hook, the status will probably always be "clean"
# status=$(git status --porcelain)
# if [ -z "$status" ] ; then
#   status='(clean)'

# TODO: double quotes in these strings would break things

git_data () {
    printf 'git_data = {\n'
    printf '    "hash": "%s",\n' "$hash"
    printf '    "subject": "%s",\n' "$subj"
    printf '    "ref_names": "%s",\n' "$names"
    printf '    "author_date": "%s",\n' "$adate"
    printf '    "commit_date": "%s",\n' "$cdate"
#    printf '    "status": "%s",\n' "$status",
    printf '}\n'
}

source_data () {
    printf 'source_data = {\n'
    printf '    "git": git_data,\n'
    printf '}\n'
}


printf '# DO NOT EDIT -- This file automatically generated -- DO NOT EDIT\n' > "$TARGET_FILE"
git_data >> "$TARGET_FILE"
source_data >> "$TARGET_FILE"
