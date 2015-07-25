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

import datetime
import asyncio
import threading
from urllib import request as url_request
from lib_socks_proxy_2013_10_03 import socks_proxy_context

class CheckAnswerError(Exception):
    pass

class HandlerData:
    pass

class SockCkThreadCtx:
    pass

class SockCkBlockingThreadCtx:
    pass

@asyncio.coroutine
def sock_ck_thread(loop, thread_ctx):
    for source_i, source_line, source_host, source_port in thread_ctx.source_iter:
        result_queue = asyncio.Queue(loop=loop)
        
        def blocking_thread():
            bl_thread_ctx = SockCkBlockingThreadCtx()
            bl_thread_ctx.error_type = None
            bl_thread_ctx.error_str = None
            
            try:
                opener = url_request.build_opener()
                
                bl_thread_ctx.begin_time = datetime.datetime.utcnow()
                
                with socks_proxy_context.socks_proxy_context(proxy_address=(source_host, source_port)):
                    res = opener.open(thread_ctx.check_url, timeout=thread_ctx.req_timeout)
                
                data = res.read(thread_ctx.req_length).decode(errors='replace')
                
                bl_thread_ctx.done_time = datetime.datetime.utcnow()
                
                if thread_ctx.check_answer not in data:
                    raise CheckAnswerError('check_answer not in data')
            except Exception as e:
                bl_thread_ctx.error_time = datetime.datetime.utcnow()
                
                bl_thread_ctx.error_type = type(e)
                bl_thread_ctx.error_str = str(e)
            
            loop.call_soon_threadsafe(result_queue.put_nowait, bl_thread_ctx)
        
        handler_data = HandlerData()
        handler_data.thread_ctx = thread_ctx
        handler_data.source_i = source_i
        handler_data.source_line = source_line
        handler_data.source_host = source_host
        handler_data.source_port = source_port
        
        if thread_ctx.begin_handler is not None:
            yield from thread_ctx.begin_handler(loop, handler_data)
        
        threading.Thread(target=blocking_thread, daemon=True).start()
        
        bl_thread_ctx = yield from result_queue.get()
        
        handler_data.bl_thread_ctx = bl_thread_ctx
        
        if bl_thread_ctx.error_type is None:
            if thread_ctx.done_handler is not None:
                yield from thread_ctx.done_handler(loop, handler_data)
        else:
            if thread_ctx.error_handler is not None:
                yield from thread_ctx.error_handler(loop, handler_data)
            
            assert isinstance(thread_ctx.error_delay, float)
            
            if thread_ctx.error_delay > 0:
                yield from asyncio.sleep(thread_ctx.error_delay, loop=loop)

@asyncio.coroutine
def sock_ck(
            loop,
            source_iter=None,
            check_url=None,
            check_answer=None,
            req_timeout=None,
            req_length=None,
            conc=None,
            error_delay=None,
            begin_handler=None,
            done_handler=None,
            error_handler=None,
        ):
    assert check_url is not None
    assert check_answer is not None
    assert req_timeout is not None
    assert req_length is not None
    assert conc is not None
    assert error_delay is not None
    
    thread_task_list = []
    for thread_i in range(conc):
        thread_ctx = SockCkThreadCtx()
        thread_ctx.thread_i = thread_i + 1
        thread_ctx.source_iter = source_iter
        thread_ctx.check_url = check_url
        thread_ctx.check_answer = check_answer
        thread_ctx.req_timeout = req_timeout
        thread_ctx.req_length = req_length
        thread_ctx.conc = conc
        thread_ctx.error_delay = error_delay
        thread_ctx.begin_handler = begin_handler
        thread_ctx.done_handler = done_handler
        thread_ctx.error_handler = error_handler
        
        thread_task = loop.create_task(sock_ck_thread(loop, thread_ctx))
        
        thread_task_list.append(thread_task)
    
    yield from asyncio.wait(thread_task_list, loop=loop)
