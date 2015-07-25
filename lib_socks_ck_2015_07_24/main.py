# -*- mode: python; coding: utf-8 -*-
#
# Copyright (c) 2015 Andrej Antonov <polymorphm@gmail.com>
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.

assert str is not bytes

import argparse
import csv
import itertools
import asyncio
import datetime
import shlex
from . import sock_ck

DEFAULT_CHECK_URL = 'https://www.google.co.uk/'
DEFAULT_CHECK_ANSWER = 'Google'
DEFAULT_REQ_TIMEOUT = 20.0
DEFAULT_REQ_LENGTH = 10000000
DEFAULT_CONC = 20
DEFAULT_ERROR_DELAY = 0.1

def try_print(*args, **kwargs):
    try:
        print(*args, **kwargs)
    except OSError:
        pass

def timedelta_to_ms(td):
    assert isinstance(td, datetime.timedelta)
    
    return td.days * 1000000 * 3600 * 24 + td.seconds * 1000000 + td.microseconds

def main():
    parser = argparse.ArgumentParser(
        description='typical (simple, trivial) utility for socks-proxy checking',
    )
    
    parser.add_argument(
        '--source',
        metavar='SOURCE-PROXY-LIST-PATH',
        help='path to file (for read) with proxy list for cheking',
    )
    parser.add_argument(
        '--good',
        metavar='GOOD-RESULT-PROXY-LIST-PATH',
        help='path to file (for write) with good result',
    )
    parser.add_argument(
        '--good-csv',
        metavar='GOOD-RESULT-PROXY-LIST-CSV-PATH',
        help='path to file (for write) with good result in CSV format',
    )
    parser.add_argument(
        '--bad',
        metavar='BAD-RESULT-PROXY-LIST-PATH',
        help='path to file (for write) with bad result',
    )
    parser.add_argument(
        '--bad-csv',
        metavar='BAD-RESULT-PROXY-LIST-CSV-PATH',
        help='path to file (for write) with bad result in CSV format',
    )
    
    parser.add_argument(
        '--good-hook',
        metavar='GOOD-HOOK-SCRIPT',
        help='path to file, which will be executed each time when good result will be found',
    )
    
    parser.add_argument(
        '--check-url',
        metavar='CHECK-URL',
        help='url as checking sample. default is  {!r}'.format(DEFAULT_CHECK_URL),
    )
    parser.add_argument(
        '--check-answer',
        metavar='CHECK-ANSWER',
        help='content as checking sample. default is {!r}'.format(DEFAULT_CHECK_ANSWER),
    )
    parser.add_argument(
        '--req-timeout',
        metavar='REQUEST-TIMEOUT',
        type=float,
        help='timeout (seconds) of request. default is {!r}'.format(DEFAULT_REQ_TIMEOUT),
    )
    parser.add_argument(
        '--req-length',
        metavar='REQUEST-LENGTH',
        type=int,
        help='content length (bytes) of request. default is {!r}'.format(DEFAULT_REQ_LENGTH),
    )
    parser.add_argument(
        '--conc',
        metavar='CONCURRENCY',
        type=int,
        help='count of parallel tasks. default is {!r}'.format(DEFAULT_CONC),
    )
    parser.add_argument(
        '--error-delay',
        metavar='ERROR_DELAY',
        type=float,
        help='delay (seconds) after error in task. default is {!r}'.format(DEFAULT_ERROR_DELAY),
    )
    
    args = parser.parse_args()
    
    if args.check_url is not None:
        check_url = args.check_url
    else:
        check_url = DEFAULT_CHECK_URL
    
    if args.check_answer is not None:
        check_answer = args.check_answer
    else:
        check_answer = DEFAULT_CHECK_ANSWER
    
    if args.req_timeout is not None:
        req_timeout = args.req_timeout
    else:
        req_timeout = DEFAULT_REQ_TIMEOUT
    
    if args.req_length is not None:
        req_length = args.req_length
    else:
        req_length = DEFAULT_REQ_LENGTH
    
    if args.conc is not None:
        conc = args.conc
    else:
        conc = DEFAULT_CONC
    
    if args.error_delay is not None:
        error_delay = args.error_delay
    else:
        error_delay = DEFAULT_ERROR_DELAY
    
    if args.source is not None:
        source_fd = open(args.source, encoding='utf-8', errors='replace')
    else:
        source_fd = None
    
    if args.good_hook is not None:
        good_hook_cmd = args.good_hook
    else:
        good_hook_cmd = None
    
    if args.good is not None:
        good_fd = open(args.good, mode='w', encoding='utf-8', newline='\n')
    else:
        good_fd = None
    
    if args.good_csv is not None:
        good_csv_fd = open(args.good_csv, mode='w', encoding='utf-8', newline='')
        good_csv_writer = csv.writer(good_csv_fd)
    else:
        good_csv_fd = None
        good_csv_writer = None
    
    if args.bad is not None:
        bad_fd = open(args.bad, mode='w', encoding='utf-8', newline='\n')
    else:
        bad_fd = None
    
    if args.bad_csv is not None:
        bad_csv_fd = open(args.bad_csv, mode='w', encoding='utf-8', newline='')
        bad_csv_writer = csv.writer(bad_csv_fd)
    else:
        bad_csv_fd = None
        bad_csv_writer = None
    
    def source_iter_create():
        if source_fd is None:
            return
        
        source_iter = itertools.count(1)
        for raw_line in source_fd:
            source_line = raw_line.strip()
            
            if not source_line:
                continue
            
            line_split = source_line.rsplit(sep=':', maxsplit=1)
            
            if len(line_split) != 2:
                continue
            
            source_host = line_split[0]
            source_port_str = line_split[1]
            
            try:
                source_port = int(source_port_str)
            except ValueError:
                continue
            
            source_i = next(source_iter)
            
            yield source_i, source_line, source_host, source_port
    
    source_iter = source_iter_create()
    
    loop = asyncio.get_event_loop()
    hook_lock = asyncio.Lock(loop=loop)
    
    @asyncio.coroutine
    def begin_handler(loop, handler_data):
        try_print('thread {!r}, source {!r}, host {!r}, port {!r}: begin'.format(
            handler_data.thread_ctx.thread_i,
            handler_data.source_i,
            handler_data.source_host,
            handler_data.source_port,
        ))
    
    @asyncio.coroutine
    def done_handler(loop, handler_data):
        delta_ms = timedelta_to_ms(
            handler_data.bl_thread_ctx.done_time -
            handler_data.bl_thread_ctx.begin_time
            )
        
        try_print('thread {!r}, source {!r}, host {!r}, port {!r}: done'.format(
            handler_data.thread_ctx.thread_i,
            handler_data.source_i,
            handler_data.source_host,
            handler_data.source_port,
        ))
        
        if good_fd is not None:
            good_fd.write('{}\n'.format(handler_data.source_line))
            good_fd.flush()
        
        if good_csv_writer is not None:
            good_csv_writer.writerow((
                handler_data.source_host,
                handler_data.source_port,
                delta_ms,
            ))
        
        if good_hook_cmd is not None:
            cmd = '{} {} {} {}'.format(
                good_hook_cmd,
                shlex.quote(handler_data.source_host),
                shlex.quote(str(handler_data.source_port)),
                shlex.quote(str(delta_ms)),
            )
            
            with (yield from hook_lock):
                proc = yield from asyncio.create_subprocess_shell(cmd, loop=loop)
                
                yield from proc.wait()
    
    @asyncio.coroutine
    def error_handler(loop, handler_data):
        delta_ms = timedelta_to_ms(
            handler_data.bl_thread_ctx.error_time -
            handler_data.bl_thread_ctx.begin_time
            )
        
        try_print('thread {!r}, source {!r}, host {!r}, port {!r}: error: {!r} {}'.format(
            handler_data.thread_ctx.thread_i,
            handler_data.source_i,
            handler_data.source_host,
            handler_data.source_port,
            handler_data.bl_thread_ctx.error_type,
            handler_data.bl_thread_ctx.error_str,
        ))
        
        if bad_fd is not None:
            bad_fd.write('{}\n'.format(handler_data.source_line))
            bad_fd.flush()
        
        if bad_csv_writer is not None:
            bad_csv_writer.writerow((
                handler_data.source_host,
                handler_data.source_port,
                delta_ms,
                handler_data.bl_thread_ctx.error_type,
                handler_data.bl_thread_ctx.error_str,
            ))
    
    sock_ck_coro = sock_ck.sock_ck(
        loop,
        source_iter=source_iter,
        check_url=check_url,
        check_answer=check_answer,
        req_timeout=req_timeout,
        req_length=req_length,
        conc=conc,
        error_delay=error_delay,
        begin_handler=begin_handler,
        done_handler=done_handler,
        error_handler=error_handler,
    )
    
    loop.run_until_complete(sock_ck_coro)
    
    try_print('done!')
    
    loop.close()
    
    if source_fd is not None:
        source_fd.close()
    
    if good_fd is not None:
        good_fd.close()
    
    if bad_fd is not None:
        bad_fd.close()
