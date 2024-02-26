import sys
import logging
import traceback
import time
import dataclasses
import pprint
import typing as T

logger = logging.getLogger(__name__)

DEBUG = 'DEBUG'
INFO = 'INFO'
WARNING = 'WARNING'
ERROR = 'ERROR'
CRITICAL = 'CRITICAL'

@dataclasses.dataclass
class Event:
    level: str
    message: str
    extra: dict
    exc_info: T.Optional[T.Tuple[T.Any, T.Any, T.Any]] = None

class RateLimiter:

    def __init__(self, last_n_seconds, max_requests: int, min_interval: int=0):
        self.history = []
        self.last_n_seconds = last_n_seconds
        self.max_requests = max_requests
        self.min_interval = min_interval

    def get_wait_duration(self, now=None) -> T.Optional[float]:
        now = now or time.monotonic()
        if len(self.history) == 0:
            return None
        self.trim_history(now)
        d0 = 0
        d1 = 0
        if self.history and now - self.history[-1] < self.min_interval:
            d0 = self.history[-1] + self.min_interval - now
        if len(self.history) >= self.max_requests:
            d1 = self.history[0] + self.last_n_seconds - now
        if d0 == 0 and d1 == 0:
            return None
        return max(d0, d1)

    def inc(self, now=None):
        now = now or time.monotonic()
        self.history.append(now)

    def trim_history(self, now=None):
        now = now or time.monotonic()
        delete_before = now - self.last_n_seconds
        while self.history and self.history[0] <= delete_before:
            self.history.pop(0)

HALT = object()

class LocalCtxMixIn:

    def __init__(self):
        self.contexts = []

    def push_context(self, ctx: dict):
        self.contexts.append(ctx)

    def pop_context(self):
        self.contexts.pop()

    def get_ctx(self):
        ctx = {}
        for c in self.contexts:
            ctx.update(c)
        return ctx


class BaseWorker:

    sleep_func = time.sleep

    def __init__(self, exception_handler=None):
        if exception_handler is None:
            exception_handler = lambda *_: None
        self.exception_handler = exception_handler

    def start(self):
        pass

    def submit(self, callback) -> bool:
        raise NotImplementedError

    def flush(self, timeout) -> bool:
        raise NotImplementedError

    @staticmethod
    def get_local_object():
        raise NotImplementedError

class SyncWorker(BaseWorker):

    def submit(self, callback) -> bool:
        try:
            callback()
        except Exception as e:
            self.exception_handler(e)
            return False
        return True

    def flush(self, timeout):
        return True

    @staticmethod
    def get_local_object():
        return LocalCtxMixIn()

class ThreadWorker(BaseWorker):

    def __init__(self, max_queue_size=0, *args, **kwargs):
        super().__init__(*args, **kwargs)
        import queue
        self.queue = queue.Queue(max_queue_size)
        self.started = False

    def start(self):
        import threading
        if self.started:
            raise RuntimeError()
        self.started = True
        self.thread = threading.Thread(target=self.target)
        self.thread.daemon = True
        self.thread.start()

    def target(self):
        while True:
            callback = self.queue.get()
            try:
                callback()
            except Exception as e:
                self.exception_handler(e)
            finally:
                self.queue.task_done()

    def submit(self, callback):
        import queue
        try:
            self.queue.put(callback, block=False)
        except queue.Full:
            return False
        return True

    @staticmethod
    def get_local_object():
        import threading
        class ThreadLocal(threading.local, LocalCtxMixIn):
            pass
        return ThreadLocal()

    def flush(self, timeout):
        if not self.queue.unfinished_tasks:
            return True
        deadline = time.monotonic() + timeout
        while self.queue.unfinished_tasks:
            if time.monotonic() > deadline:
                return False
            time.sleep(0.1)
        return True

GEVENT_ALREADY_IMPORTED = 'gevent' in sys.modules
try:
    import gevent
except:
    gevent = None

if gevent is not None:
    import gevent.queue

    class GeventWorker(BaseWorker):

        sleep_func = gevent.sleep

        def __init__(self, max_queue_size=None, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.queue = gevent.queue.JoinableQueue(max_queue_size)
            self.started = False

        @staticmethod
        def get_local_object():
            from gevent.local import local
            class GreenletLocal(local, LocalCtxMixIn):
                pass
            return GreenletLocal()

        def start(self):
            if self.started:
                raise RuntimeError()
            self.started = True
            self.greenlet = gevent.spawn(self.target)

        def submit(self, callback):
            try:
                self.queue.put(callback, block=False)
            except gevent.queue.Full:
                return False
            return True

        def target(self):
            while True:
                callback = self.queue.get()
                try:
                    callback()
                except Exception as e:
                    self.exception_handler(e)
                finally:
                    self.queue.task_done()

        def flush(self, timeout):
            return self.queue.join(timeout=timeout)

class NotifyLoggingHandler(logging.Handler):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._initialized = False

    def initialize(self, hub):
        if self._initialized:
            raise RuntimeError()
        self._initialized = True
        self.hub = hub

    def emit(self, record):
        event = Event(
            level=record.levelname,
            message=record.getMessage(),
            extra=getattr(record, 'extra', None),
            exc_info=record.exc_info,
        )
        self.hub.push_event(event)

class LoggingIntegration:

    def __init__(self, logger=None, handler=None, level=None):
        self.initialized = False
        self.handler_added = False
        if handler is None:
            if level is None:
                level = logging.NOTSET
            handler = NotifyLoggingHandler(level=level)
            if logger is None:
                logger = logging.getLogger()
            logger.addHandler(handler)
            self.handler_added = True
        elif logger is not None or level is not None:
            raise ValueError()
        self.logger = logger
        self.handler = handler

    def initialize(self, hub):
        if self.initialized:
            raise RuntimeError()
        self.initialized = True
        self.handler.initialize(hub)

    def finalize(self):
        # To make the tests look nice
        if self.handler_added:
            self.logger.removeHandler(self.handler)

class ExcepthookIntegration:

    def initialize(self, hub):
        import sys
        self.old_excepthook = sys.excepthook
        sys.excepthook = self.new_excepthook = self.get_excepthook(hub, self.old_excepthook)

    def finalize(self):
        if sys.excepthook is self.new_excepthook:
            sys.excepthook = self.old_excepthook
        else:
            logger.warning('excepthook could not be uninstalled because it has been modified')

    @staticmethod
    def get_excepthook(hub, old_excepthook):
        def _excepthook(typ, value, traceback):
            hub.push_event(Event(ERROR, 'Unhandled exception', extra=None, exc_info=(typ, value, traceback)))
            return old_excepthook(typ, value, traceback)
        return _excepthook

class BaseClient:

    def push_event(self, event: Event):
        raise NotImplementedError

    def initialize(self, worker: BaseWorker):
        raise NotImplementedError

class DiscordClient(BaseClient):

    def __init__(self, webhook_url: str, ratelimiter=None):
        self.webhook_url = webhook_url
        self.initialized = False
        self.ratelimiter = ratelimiter or RateLimiter(60, 10, 0.5)

    def initialize(self, worker):
        if self.initialized:
            raise RuntimeError()
        self.initialized = True
        self.hub = hub
        self.worker = worker

    def push_event(self, event):
        func = self.get_post_func(event)
        if func is None:
            return True
        return self.worker.submit(func)

    def get_post_func(self, event):
        import requests

        level_colors = {
            DEBUG: 0x858585,    # Grey
            INFO: 0x0099ff,     # Blue
            WARNING: 0xffa500,  # Orange
            ERROR: 0xff0000,    # Red
            CRITICAL: 0x4b0082, # Indigo
        }
        title = None
        if event.message.strip():
            title = f'{event.level}: {event.message}'
        chunks = []
        if event.exc_info is not None:
            chunks.extend(['```\n', *traceback.format_exception(*event.exc_info), '```'])
        if event.extra:
            chunks.append('\n```\n')
            chunks.append(pprint.pformat(event.extra))
            chunks.append('\n```')
        text = ''.join(chunks).strip()
        payload = {
            "embeds": [
                {
                    "title": title,
                    "description": text,
                    "color": level_colors.get(event.level, 0x000000),
                }
            ],
        }
        sleep_func = self.worker.__class__.sleep_func
        def _post():
            duration = self.ratelimiter.get_wait_duration()
            if duration is not None:
                sleep_func(duration)
            self.ratelimiter.inc()
            response = requests.post(self.webhook_url, json=payload)
            if response.status_code == 204:
                logger.debug("Message sent successfully")
            else:
                logger.warning("Failed to send message, status code: %d", response.status_code)
        return _post

    def flush(self):
        pass

class WsgiIntegration:

    def wrap(self, app):
        def _app(environ, start_response):
            from werkzeug.wrappers import Request
            req = Request(environ)
            self.hub.push_context(url=req.url, method=req.method)
            try:
                return app(environ, start_response)
            except Exception as e:
                self.hub.push_exception(e)
                raise
            finally:
                self.hub.pop_context()
        return _app

    def initialize(self, hub):
        self.hub = hub

    def finalize(self):
        pass

class Hub:

    def __init__(self, *, worker_cls, clients: T.Sequence[BaseClient], integrations=(), termination_seconds: int=10):
        if worker_cls is None:
            if GEVENT_ALREADY_IMPORTED:
                worker_cls = GeventWorker
            else:
                worker_cls = ThreadWorker
        self.clients = clients
        self.local = worker_cls.get_local_object()
        worker_by_client = {}
        for c in clients:
            worker = worker_cls(exception_handler=self.handle_internal_exception)
            worker_by_client[c] = worker
            c.initialize(worker)
        for w in worker_by_client.values():
            w.start()
        self.worker_by_client = worker_by_client
        self.integrations = integrations
        for i in integrations:
            i.initialize(self)
        self.termination_seconds = termination_seconds
        self.closed = False

    def handle_internal_exception(self, e):
        import traceback
        print(f'{__name__}: Internal error:')
        print(''.join(traceback.format_exception(type(e), e, e.__traceback__)))

    def push_event(self, event):
        ctx = self.local.get_ctx()
        new_event = dataclasses.replace(event, extra={
            **ctx,
            **(event.extra or {})
        })
        for c in self.clients:
            success = c.push_event(new_event)
            if not success:
                logger.warning('failed pushing event: {new_event!r}, client: {c!r}')

    def push_exception(self, e):
        self.push_event(Event(ERROR, 'Exception raised', extra=None, exc_info=(type(e), e, e.__traceback__)))

    def push_context(self, **ctx):
        # inherit when spawning a new thread/greenlet?
        # but that requires hooking threading.Thread and such
        self.local.push_context(ctx)

    def pop_context(self):
        self.local.pop_context()

    def close(self):
        if self.closed:
            return
        self.closed = True
        # in parallel?
        for c, w in self.worker_by_client.items():
            nothing_remains = w.flush(self.termination_seconds)
            if not nothing_remains:
                print(f'worker {w!r} for client {c!r} could not clear the queue before exiting')
        for i in self.integrations:
            i.finalize()

    def __enter__(self):
        return self

    def __exit__(self, *args, **kwargs):
        global hub
        self.close()
        hub = None

hub = None

def init(*, client, integrations=(), worker_cls=None, close_on_exit=True):
    global hub
    if hub is not None:
        raise RuntimeError('already initialized')
    if hasattr(client, '__iter__'):
        clients = list(client)
    else:
        clients = [client]
    hub = Hub(worker_cls=worker_cls, clients=clients, integrations=integrations)
    if close_on_exit:
        import atexit
        atexit.register(hub.close)
    return hub
