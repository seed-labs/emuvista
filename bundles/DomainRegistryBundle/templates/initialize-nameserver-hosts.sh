#!/bin/sh
set -e
rm -f __MARKER__.ready __MARKER__.failed
trap 'touch __MARKER__.failed' EXIT
__EXPORTS__php8.5 __DIRECTORY__.php
touch __MARKER__.ready
trap - EXIT
