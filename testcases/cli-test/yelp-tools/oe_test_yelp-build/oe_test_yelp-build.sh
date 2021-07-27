#!/usr/bin/bash

# Copyright (c) 2021. Huawei Technologies Co.,Ltd.ALL rights reserved.
# This program is licensed under Mulan PSL v2.
# You can use it according to the terms and conditions of the Mulan PSL v2.
#          http://license.coscl.org.cn/MulanPSL2
# THIS PROGRAM IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND,
# EITHER EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT,
# MERCHANTABILITY OR FIT FOR A PARTICULAR PURPOSE.
# See the Mulan PSL v2 for more details.
####################################
#@Author    	:   Jevons                      
#@Contact   	:   1557927445@qq.com                 
#@Date      	:   2021-06-21 20:31:43               
#@License   	:   Mulan PSL v2
#@Desc      	:   yelp build                  
#####################################

source ${OET_PATH}/libs/locallibs/common_lib.sh

function pre_test()
{
    LOG_INFO "Start to prepare the test environment."
    DNF_INSTALL "yelp-tools yelp"
    LOG_INFO "End to prepare the test environment."
}

function run_test()
{
    LOG_INFO "Start to run test."
    yelp-build html DocBook 
    CHECK_RESULT $? 0 0 "html failed"
    find . -type f -name "highlight.pack.js" 
    CHECK_RESULT $? 0 0  "find html failed"
    yelp-build cache Mallard
    CHECK_RESULT $? 0 0 "cache failed"
    find . -type f -name "index.cache"
    CHECK_RESULT $? 0 0 "find cache failed"
    yelp-build epub Mallard
    CHECK_RESULT $? 0 0 "epub failed"
    find . -type f -name "index.epub"
    CHECK_RESULT $? 0 0 "find epub failed"
    LOG_INFO "End to run test."
}

function post_test()
{
    LOG_INFO "Start to restore the test environment."
    rm -rf highlight.pack.js index.cache index.epub
    DNF_REMOVE
    LOG_INFO "End to restore the test environment."
}

main "$@"
