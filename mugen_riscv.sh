#!/usr/bin/bash

OET_PATH=$(
    cd "$(dirname "$0")" || exit 1
    pwd
)
export OET_PATH

python3 ${OET_PATH}/libs/locallibs/mugen_riscv.py "$@"
test $? -ne 0 && exit 1 || exit 0